"""知识库管理服务。

上传接口只负责建立待审核元数据；后台任务复用现有 Ollama
Embedding、Milvus 集合模型和 MinIO 客户端完成入库。
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel

logger = logging.getLogger(__name__)


class KnowledgeAdminService:
    """知识文档的元数据和向量入库编排。"""

    TYPE_TO_COLLECTION = {
        "FAQ": "fin_faq_collection",
        "产品说明": "fin_product_collection",
        "产品说明书": "fin_product_collection",
        "政策法规": "fin_policy_collection",
    }
    MAX_UPLOAD_BYTES = 10 * 1024 * 1024
    ALLOWED_EXTENSIONS = {".txt", ".md", ".docx"}

    @classmethod
    def create_pending(
        cls,
        *,
        knowledge_type: str,
        title: str,
        source_file: str,
        uploaded_by: int,
    ) -> KnowledgeMetaModel:
        collection = cls.TYPE_TO_COLLECTION.get(knowledge_type)
        if collection is None:
            raise ValueError("知识类型必须是 FAQ、产品说明或政策法规")
        normalized_type = "产品说明书" if knowledge_type == "产品说明" else knowledge_type
        record = KnowledgeMetaModel(
            knowledge_type=normalized_type,
            collection_name=collection,
            title=title.strip(),
            source=source_file,
            source_file=source_file,
            milvus_collection=collection,
            file_path=None,
            chunk_count=0,
            status="待审核",
            uploaded_by=uploaded_by,
        )
        record_id = record.save()
        if record_id <= 0:
            raise RuntimeError("知识元数据创建失败")
        return record

    @classmethod
    def ingest_bytes(
        cls,
        *,
        record_id: int,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        """后台入库；任一外部存储失败时保留待审核记录以便重试。"""
        record = KnowledgeMetaModel.get_by_id(record_id)
        if record is None:
            logger.error("知识入库失败：元数据 %s 不存在", record_id)
            return
        try:
            text = cls._extract_text(filename, content)
            chunks = cls._chunk_text(text)
            if not chunks:
                raise ValueError("文档没有可入库的文本")

            object_name = cls._archive_raw_file(filename, content, content_type)
            cls._insert_vectors(record, chunks)
            if not record.update(
                file_path=f"fin-knowledge-raw/{object_name}",
                minio_object_key=object_name,
                chunk_count=len(chunks),
                status="已上线",
            ):
                raise RuntimeError("知识元数据状态更新失败")
        except Exception:
            logger.exception("知识文档后台入库失败: record_id=%s", record_id)

    @staticmethod
    def _extract_text(filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix in {".txt", ".md"}:
            return content.decode("utf-8-sig")
        if suffix == ".docx":
            from docx import Document

            with tempfile.NamedTemporaryFile(suffix=".docx") as handle:
                handle.write(content)
                handle.flush()
                return "\n".join(p.text for p in Document(handle.name).paragraphs if p.text.strip())
        raise ValueError("仅支持 txt、md 和 docx 文档")

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not normalized:
            return []
        chunks = []
        start = 0
        while start < len(normalized):
            chunks.append(normalized[start:start + chunk_size])
            if start + chunk_size >= len(normalized):
                break
            start += chunk_size - overlap
        return chunks

    @staticmethod
    def _archive_raw_file(filename: str, content: bytes, content_type: str | None) -> str:
        from app.Base.Client.minioClient import default_minio_client

        safe_name = Path(filename).name
        with tempfile.NamedTemporaryFile(suffix=Path(safe_name).suffix) as handle:
            handle.write(content)
            handle.flush()
            object_name = default_minio_client.upload_file(
                "fin-knowledge-raw",
                f"uploads/{safe_name}",
                handle.name,
                content_type or "application/octet-stream",
            )
        if not object_name:
            raise RuntimeError("MinIO 原始文档归档失败")
        return object_name

    @staticmethod
    def _insert_vectors(record: KnowledgeMetaModel, chunks: list[str]) -> None:
        from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
        from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2
        from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
        from app.WealthButler.Service.ollamaEmbeddingService import OllamaEmbeddingService

        models: dict[str, Any] = {
            "fin_faq_collection": FaqCollectionModelV2,
            "fin_product_collection": ProductCollectionModelV2,
            "fin_policy_collection": PolicyCollectionModelV2,
        }
        model = models[record.collection_name]
        instances = []
        for index, text in enumerate(chunks, start=1):
            metadata = {
                "title": record.title,
                "source_file": record.source,
                "knowledge_type": record.knowledge_type,
                "chunk_index": index,
            }
            if record.collection_name == "fin_faq_collection":
                metadata = json.dumps(metadata, ensure_ascii=False)
            instances.append(model(text=text, metadata=metadata, embedding=OllamaEmbeddingService.embed(text)))
        result = model.insert(instances)
        inserted = result.get("insert_count", len(result.get("ids", []))) if isinstance(result, dict) else 0
        if inserted != len(instances):
            raise RuntimeError(f"Milvus 入库数不一致: expected={len(instances)}, actual={inserted}")
