from typing import Dict, Any, Optional
from Base.Ai.llms.qwenLlm import get_default_qwen_llm
from Base.Models.BaseLLMConversationModel import BaseLLMConversationModel
from Base.Models.VdbLLMConversation import VdbLLMConversation


def save_conversation_from_db_2_vdb(db_instance: BaseLLMConversationModel):
    """
    将对话记录从数据库保存到 VDB
    兼容旧接口，内部调用 save_conversation_from_db_2_vdb_only_data
    """
    data = {
        'id': db_instance.id,
        'session_id': db_instance.session_id,
        'user_id': db_instance.user_id,
        'question': db_instance.question,
        'rewrite_question': db_instance.rewrite_question or '',
        'answer': db_instance.get_answer
    }
    save_conversation_from_db_2_vdb_only_data(data)


def save_conversation_from_db_2_vdb_only_data(data: Dict[str, Any]):
    """
    将对话记录（纯数据字典）保存到 VDB

    使用纯数据而非 model 实例，避免 pickle 错误（cannot pickle '_thread.RLock' object）

    Args:
        data: 对话数据字典，需包含以下字段：
            - id: 对话 ID
            - session_id: 会话 ID
            - user_id: 用户 ID
            - question: 用户问题
            - rewrite_question: 改写后的问题（可选）
            - answer: AI 回答
    """
    llm = get_default_qwen_llm()
    question_embedding = llm.embedding(text=data.get('question', ''), dimensions=1024)

    question_embedding = question_embedding[0] if question_embedding and isinstance(question_embedding[0],
                                                                                    list) else question_embedding

    vdb = VdbLLMConversation(db_id=str(data.get('id', '')),
                             session_id=data.get('session_id', ''),
                             user_id=data.get('user_id', ''),
                             question=data.get('question', ''),
                             rewrite_question=data.get('rewrite_question', ''),
                             answer=data.get('answer', ''),
                             embedding=question_embedding)
    vdb.save()


if __name__ == '__main__':
    # 查询数据库中所有对话记录 存到VDB
    db_instances = BaseLLMConversationModel.find_by()
    for i in db_instances:
        save_conversation_from_db_2_vdb(i)

