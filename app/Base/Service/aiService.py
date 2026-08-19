import json
from typing import Literal

from app.Base.Ai.llms.deepseekLlm import get_default_deepseek_llm, DeepSeekLlm
from app.Base.Ai.llms.ollamaEmbedding import ollama_embedding
from app.Base.Ai.prompt.commonPrompt import text_auditing_prompt_v1
from app.Base.Ai.service.commonService import RewriteQuestionParams, rewrite_question
from app.Base.Ai.utils.common import jinja2_prompt_render
from app.Base.Client.tencent.text_audting import ci_auditing_text_submit, is_normal
from app.Base.Models.BaseLLMConversationModel import BaseLLMConversationModel
from app.Base.Models.VdbLLMConversation import VdbLLMConversation


class AuditingTextError(Exception):
    pass


class AiService:

    @staticmethod
    def rewrite_question(question: str, user_id: str, session_id: str):
        llm = DeepSeekLlm()
        # 使用本地Ollama的bge-m3模型生成向量（DeepSeek不支持embedding）
        question_embedding = ollama_embedding(text=question)
        similarity = VdbLLMConversation.search(data=question_embedding, output_fields=['question'])
        history = BaseLLMConversationModel.get_last_n_turns_context(user_id, session_id, 5)
        history = BaseLLMConversationModel.db_res_2_messages(history, is_rewrite=True)
        return rewrite_question(RewriteQuestionParams(question=question, similarity=similarity, history=history))

    @staticmethod
    def auditing_text(text: str, auditing_type: Literal['local', 'tencent'] = 'local'):
        """
        文本审核
        text: 文本
        type: local 本地审核，tencent 腾讯云审核

        : return: 审核结果
        {"status": 1, "reason": ""}
        {"status": 0, "reason": "包含敏感政治元素【敏感政治人物】"}
        """
        if auditing_type == 'local':
            llm = DeepSeekLlm()
            prompt = jinja2_prompt_render(prompt=text_auditing_prompt_v1, params={'text': text})
            response = llm.invoke(prompt=prompt)
            res_dict = json.loads(response)
            return res_dict
        else:
            response = ci_auditing_text_submit(text)
            return {'status': 1 if is_normal(response) else 0,
                    'reason': '腾讯云审核' + ('成功' if is_normal(response) else '失败，内容包含敏感词')}


if __name__ == '__main__':
    # question_new = AiService.rewrite_question(question="一百个 奥特曼呢", user_id='string',
    #                                           session_id='string')
    # print(question_new)

    test_res = AiService.auditing_text(text="我日你大爷的")
    print(test_res)
