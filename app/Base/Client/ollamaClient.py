"""Ollama 客户端（本地 Embedding 模型调用）

用途：
- 调用本地 Ollama 服务生成文本向量
- 支持 bge-m3 等 Embedding 模型（1024维）
- 用于 RAG 知识库向量化

配置：
- OLLAMA_BASE_URL: Ollama 服务地址（默认 http://localhost:11434）
"""
import logging
import os
import requests
from typing import List
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

# 读取 Ollama 配置
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


class OllamaClient:
    """Ollama 客户端（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(OllamaClient, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.base_url = OLLAMA_BASE_URL
        self._initialized = True
        logger.info(f"OllamaClient 初始化: {self.base_url}")

    def get_embedding(self, text: str, model: str = 'bge-m3') -> List[float]:
        """调用 Ollama 生成文本向量

        Args:
            text: 待向量化的文本
            model: Embedding 模型名称（默认 bge-m3）

        Returns:
            向量列表（1024维）

        Raises:
            Exception: 调用失败或模型不可用
        """
        url = f"{self.base_url}/api/embeddings"
        payload = {
            "model": model,
            "prompt": text
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            embedding = result.get('embedding', [])

            if not embedding:
                raise ValueError(f"Ollama 返回空向量: {result}")

            logger.debug(f"生成向量成功: 维度={len(embedding)}")
            return embedding

        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama 调用失败: {e}")
            raise Exception(f"Ollama 服务不可用: {e}")
        except Exception as e:
            logger.error(f"生成向量异常: {e}")
            raise


# 全局单例
ollama_client = OllamaClient()
