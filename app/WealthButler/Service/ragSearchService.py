"""
RAG检索服务统一封装

职责：
- 封装产品、政策、FAQ三类知识库的混合检索
- 统一检索参数和返回格式
- 提供来源引用格式化
- 供Agent调用的标准接口

使用V2集合（支持BM25混合检索）
"""
import logging
from typing import List, Dict, Any, Optional, Literal
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2
from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.Base.Client.ollamaClient import ollama_client
from app.WealthButler.Utils.ragFormatter import (
    format_search_results_with_citation,
    format_search_results_simple,
    format_search_results_json
)

logger = logging.getLogger(__name__)


class RagSearchService:
    """RAG检索服务统一封装"""

    # 默认检索参数
    DEFAULT_DENSE_WEIGHT = 0.7
    DEFAULT_SPARSE_WEIGHT = 0.3
    DEFAULT_TOP_K = 5

    @staticmethod
    def search_product(
        query: str,
        top_k: int = DEFAULT_TOP_K,
        dense_weight: float = DEFAULT_DENSE_WEIGHT,
        sparse_weight: float = DEFAULT_SPARSE_WEIGHT,
        filter_expr: str = "",
        format_type: Literal["citation", "simple", "json"] = "simple"
    ) -> Any:
        """
        检索产品知识库（混合检索：稠密向量 + BM25）

        Args:
            query: 查询文本
            top_k: 返回结果数量
            dense_weight: 稠密向量权重
            sparse_weight: BM25稀疏向量权重
            filter_expr: Milvus过滤表达式
            format_type: 返回格式（citation=带引用/simple=纯文本/json=结构化）

        Returns:
            根据format_type返回不同格式的结果
        """
        try:
            # 生成稠密向量
            embedding = ollama_client.get_embedding(query, model="bge-m3")

            # 执行混合检索
            results = ProductCollectionModelV2.hybrid_search(
                dense_vector=embedding,
                query_text=query,
                dense_weight=dense_weight,
                sparse_weight=sparse_weight,
                limit=top_k,
                filter=filter_expr,
                output_fields=['text', 'metadata']
            )

            if not results or not results[0]:
                return RagSearchService._format_empty_result(format_type)

            # 格式化结果
            return RagSearchService._format_results(
                results[0], "product", format_type
            )

        except Exception as e:
            logger.error(f"产品检索失败: {e}", exc_info=True)
            return RagSearchService._format_error_result(str(e), format_type)

    @staticmethod
    def search_policy(
        query: str,
        top_k: int = DEFAULT_TOP_K,
        dense_weight: float = DEFAULT_DENSE_WEIGHT,
        sparse_weight: float = DEFAULT_SPARSE_WEIGHT,
        filter_expr: str = "",
        format_type: Literal["citation", "simple", "json"] = "simple"
    ) -> Any:
        """
        检索政策法规知识库（混合检索：稠密向量 + BM25）

        Args:
            query: 查询文本
            top_k: 返回结果数量
            dense_weight: 稠密向量权重
            sparse_weight: BM25稀疏向量权重
            filter_expr: Milvus过滤表达式
            format_type: 返回格式

        Returns:
            根据format_type返回不同格式的结果
        """
        try:
            # 生成稠密向量
            embedding = ollama_client.get_embedding(query, model="bge-m3")

            # 执行混合检索
            results = PolicyCollectionModelV2.hybrid_search(
                dense_vector=embedding,
                query_text=query,
                dense_weight=dense_weight,
                sparse_weight=sparse_weight,
                limit=top_k,
                filter=filter_expr,
                output_fields=['text', 'metadata']
            )

            if not results or not results[0]:
                return RagSearchService._format_empty_result(format_type)

            # 格式化结果
            return RagSearchService._format_results(
                results[0], "policy", format_type
            )

        except Exception as e:
            logger.error(f"政策检索失败: {e}", exc_info=True)
            return RagSearchService._format_error_result(str(e), format_type)

    @staticmethod
    def search_faq(
        query: str,
        top_k: int = 3,
        threshold: float = 0.75,
        format_type: Literal["citation", "simple", "json"] = "simple"
    ) -> Any:
        """
        检索FAQ知识库（纯稠密向量检索，相似度阈值过滤）

        Args:
            query: 查询文本
            top_k: 返回结果数量
            threshold: 相似度阈值（低于此值过滤）
            format_type: 返回格式

        Returns:
            根据format_type返回不同格式的结果
        """
        try:
            # 生成稠密向量
            embedding = ollama_client.get_embedding(query, model="bge-m3")

            # 执行稠密向量检索
            results = FaqCollectionModelV2.search(
                data=embedding,
                anns_field='embedding',
                limit=top_k,
                output_fields=['text', 'metadata']
            )

            if not results or not results[0]:
                return RagSearchService._format_empty_result(format_type)

            # 过滤低相似度结果
            filtered_results = [
                r for r in results[0]
                if r.get('distance', 0) >= threshold
            ]

            if not filtered_results:
                return RagSearchService._format_empty_result(format_type)

            # 格式化结果
            return RagSearchService._format_results(
                filtered_results, "faq", format_type
            )

        except Exception as e:
            logger.error(f"FAQ检索失败: {e}", exc_info=True)
            return RagSearchService._format_error_result(str(e), format_type)

    @staticmethod
    def search_all(
        query: str,
        top_k_per_collection: int = 3,
        format_type: Literal["citation", "simple", "json"] = "simple"
    ) -> Dict[str, Any]:
        """
        跨知识库检索（产品 + 政策 + FAQ）

        Args:
            query: 查询文本
            top_k_per_collection: 每个集合返回的结果数
            format_type: 返回格式

        Returns:
            {
                "product": 产品检索结果,
                "policy": 政策检索结果,
                "faq": FAQ检索结果
            }
        """
        return {
            "product": RagSearchService.search_product(
                query, top_k_per_collection, format_type=format_type
            ),
            "policy": RagSearchService.search_policy(
                query, top_k_per_collection, format_type=format_type
            ),
            "faq": RagSearchService.search_faq(
                query, top_k_per_collection, format_type=format_type
            )
        }

    @staticmethod
    def _format_results(
        results: List[Dict],
        collection_type: str,
        format_type: str
    ) -> Any:
        """格式化检索结果"""
        if format_type == "citation":
            return format_search_results_with_citation(results, collection_type)
        elif format_type == "simple":
            return format_search_results_simple(results, collection_type)
        elif format_type == "json":
            return format_search_results_json(results, collection_type)
        else:
            return format_search_results_simple(results, collection_type)

    @staticmethod
    def _format_empty_result(format_type: str) -> Any:
        """格式化空结果"""
        if format_type == "json":
            return []
        else:
            return "未找到相关信息。"

    @staticmethod
    def _format_error_result(error_msg: str, format_type: str) -> Any:
        """格式化错误结果"""
        if format_type == "json":
            return [{"error": error_msg}]
        else:
            return f"检索失败：{error_msg}"


# 便捷函数
def search_product(query: str, top_k: int = 5, format_type: str = "simple") -> Any:
    """便捷函数：产品检索"""
    return RagSearchService.search_product(query, top_k, format_type=format_type)


def search_policy(query: str, top_k: int = 5, format_type: str = "simple") -> Any:
    """便捷函数：政策检索"""
    return RagSearchService.search_policy(query, top_k, format_type=format_type)


def search_faq(query: str, top_k: int = 3, format_type: str = "simple") -> Any:
    """便捷函数：FAQ检索"""
    return RagSearchService.search_faq(query, top_k, format_type=format_type)


# 使用示例
if __name__ == "__main__":
    test_query = "货币基金的收益率"

    print("=== 产品检索（简单格式）===")
    result = search_product(test_query, top_k=3, format_type="simple")
    print(result)

    print("\n=== 产品检索（带引用格式）===")
    result = search_product(test_query, top_k=3, format_type="citation")
    print(result)

    print("\n=== 产品检索（JSON格式）===")
    import json
    result = search_product(test_query, top_k=3, format_type="json")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    print("\n=== 跨知识库检索 ===")
    results = RagSearchService.search_all(test_query, top_k_per_collection=2)
    for collection, result in results.items():
        print(f"\n[{collection.upper()}]")
        print(result)
