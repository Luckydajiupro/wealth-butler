"""客服知识检索使用的本地 Ollama 嵌入服务。"""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from app.Base.Config.setting import settings


class OllamaEmbeddingService:
    """使用 Ollama 原生接口，绕开部分版本的 OpenAI 兼容嵌入接口 502 问题。"""

    @staticmethod
    def embed(text: str) -> list[float]:
        if not text.strip():
            raise ValueError("嵌入文本不能为空")

        ollama = settings.ollama
        configured_url = urlsplit(getattr(ollama, "base_url"))
        endpoint = f"{configured_url.scheme}://{configured_url.netloc}/api/embed"
        payload = json.dumps({
            "model": getattr(ollama, "embedding_model"),
            "input": text,
        }).encode("utf-8")
        request = Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama 嵌入请求失败: HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"无法连接本地 Ollama 嵌入服务: {error.reason}") from error

        embeddings = data.get("embeddings") or []
        if not embeddings or not isinstance(embeddings[0], list):
            raise RuntimeError("Ollama 嵌入响应缺少 embeddings")
        return embeddings[0]
