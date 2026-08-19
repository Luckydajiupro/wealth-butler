"""
本地 Ollama 嵌入封装（原生 API 接口）

本项目 RAG 文本向量化统一走本地 Ollama 的 bge-m3（固定 1024 维），不走云端 API。
配置项见 app/Config/setting.py 的 OllamaSettings，对应 .env 里的
OLLAMA_BASE_URL / OLLAMA_EMBEDDING_MODEL（模板见项目根目录 .env.example）。

使用方式（RAG 入库/检索时替代 Qwen 的 embedding 调用）：
    from Ai.llms.ollamaEmbedding import ollama_embedding
    vec = ollama_embedding("客户问题原文")
"""
from typing import List
import requests

from app.Base.Config.setting import settings


def ollama_embedding(text: str) -> List[float]:
    """
    调用本地 Ollama 的原生 /api/embeddings 接口，返回 bge-m3 向量。

    bge-m3 输出固定 1024 维，与 Milvus 各集合的 embedding 字段 dim=1024 一致。

    Args:
        text: 待向量化的单条文本（RAG 场景通常是用户提问或知识库切片原文）

    Returns:
        1024 维 float 列表
    """
    url = f"{settings.ollama.base_url}/api/embeddings"
    payload = {
        "model": settings.ollama.embedding_model,
        "prompt": text
    }

    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    return result['embedding']
