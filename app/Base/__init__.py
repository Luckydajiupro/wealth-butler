from app.Base.Ai.llms.deepseekLlm import create_deepseek_llm
from app.Base.Config.setting import settings

default_deepseek_llm = create_deepseek_llm()

__all__ = ['settings','default_deepseek_llm']

