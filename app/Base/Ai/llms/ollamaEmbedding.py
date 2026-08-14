"""
本地 Ollama 嵌入封装（OpenAI 兼容接口）

本项目 RAG 文本向量化统一走本地 Ollama 的 bge-m3（固定 1024 维），不走云端 API。
配置项见 app/Config/setting.py 的 OllamaSettings，对应 .env 里的
OLLAMA_BASE_URL / OLLAMA_EMBEDDING_MODEL（模板见项目根目录 .env.example）。

使用方式（RAG 入库/检索时替代 Qwen 的 embedding 调用）：
    from Ai.llms.ollamaEmbedding import ollama_embedding
    vec = ollama_embedding("客户问题原文")
"""
from typing import List

from openai import OpenAI

from Base.Config.setting import settings


def ollama_embedding(text: str) -> List[float]:
    """
    调用本地 Ollama 的 OpenAI 兼容 /v1/embeddings 接口，返回 bge-m3 向量。

    bge-m3 输出固定 1024 维，与 Milvus 各集合的 embedding 字段 dim=1024 一致，
    因此不传 dimensions 参数（Ollama 兼容接口对 dim 处理与云端不同，传了反而可能报错）。

    Args:
        text: 待向量化的单条文本（RAG 场景通常是用户提问或知识库切片原文）

    Returns:
        1024 维 float 列表
    """
    client = OpenAI(
        base_url=settings.ollama.base_url,
        api_key="ollama",  # 本地 Ollama 无鉴权，占位即可，代码不校验真实性
    )
    resp = client.embeddings.create(
        model=settings.ollama.embedding_model,
        input=text,
        encoding_format="float",
    )
    return resp.data[0].embedding
