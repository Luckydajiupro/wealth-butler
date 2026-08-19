"""
RAG检索结果来源引用格式化工具

功能：
1. 将检索结果格式化为带来源引用的文本
2. 支持产品和政策两种集合
3. 提供markdown格式输出
"""
import json
from typing import List, Dict, Any


def format_search_results_with_citation(
    results: List[Dict],
    collection_type: str = "product",
    max_results: int = 3
) -> str:
    """
    格式化检索结果并添加来源引用

    Args:
        results: 检索结果列表（来自hybrid_search返回的results[0]）
        collection_type: 集合类型（product/policy）
        max_results: 最多展示结果数

    Returns:
        格式化后的markdown文本，包含来源引用
    """
    if not results:
        return "未找到相关信息。"

    formatted_parts = []
    citations = []

    for i, result in enumerate(results[:max_results], 1):
        entity = result.get('entity', {})
        text = entity.get('text', '')
        metadata = entity.get('metadata', {})
        score = result.get('distance', 0)

        # 解析metadata（可能是JSON字符串）
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}

        # 提取来源信息
        if collection_type == "product":
            source_name = metadata.get('product_name', '未知产品')
            chunk_type = metadata.get('chunk_type', '基本信息')
            source_label = f"{source_name} - {chunk_type}"
        else:  # policy
            source_name = metadata.get('document_name', '未知文档')
            chunk_type = metadata.get('chunk_type', '正文')
            source_label = f"{source_name} - {chunk_type}"

        # 格式化文本（添加上标引用）
        formatted_parts.append(f"{text} [{i}]")

        # 添加引用信息
        citations.append(f"[{i}] {source_label} (相似度: {score:.4f})")

    # 组合结果
    content = "\n\n".join(formatted_parts)
    citation_text = "\n".join(citations)

    result_text = f"{content}\n\n**来源：**\n{citation_text}"

    return result_text


def format_search_results_simple(
    results: List[Dict],
    collection_type: str = "product"
) -> str:
    """
    简化格式：只返回文本内容，不带引用（适用于对话流式输出）

    Args:
        results: 检索结果列表
        collection_type: 集合类型

    Returns:
        纯文本内容
    """
    if not results:
        return "未找到相关信息。"

    texts = []
    for result in results[:3]:
        entity = result.get('entity', {})
        text = entity.get('text', '')
        if text:
            texts.append(text)

    return "\n\n".join(texts)


def format_search_results_json(
    results: List[Dict],
    collection_type: str = "product",
    max_results: int = 5
) -> List[Dict[str, Any]]:
    """
    结构化格式：返回JSON对象列表（适用于API响应）

    Returns:
        [
            {
                "rank": 1,
                "text": "...",
                "source": "产品名称 - 基本信息",
                "score": 0.8542,
                "metadata": {...}
            },
            ...
        ]
    """
    if not results:
        return []

    formatted_results = []

    for i, result in enumerate(results[:max_results], 1):
        entity = result.get('entity', {})
        text = entity.get('text', '')
        metadata = entity.get('metadata', {})
        score = result.get('distance', 0)

        # 解析metadata
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}

        # 提取来源
        if collection_type == "product":
            source_name = metadata.get('product_name', '未知产品')
            chunk_type = metadata.get('chunk_type', '基本信息')
        else:
            source_name = metadata.get('document_name', '未知文档')
            chunk_type = metadata.get('chunk_type', '正文')

        formatted_results.append({
            "rank": i,
            "text": text,
            "source": f"{source_name} - {chunk_type}",
            "score": round(score, 4),
            "metadata": metadata
        })

    return formatted_results
