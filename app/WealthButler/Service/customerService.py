"""客服 Agent 的确定性业务服务。"""
from typing import Optional

from app.WealthButler.Repository.customerServiceRepository import CustomerServiceRepository


class CustomerService:
    """处理客户校验、工单创建和会话归档。"""

    def __init__(self, repository: Optional[CustomerServiceRepository] = None):
        self.repository = repository or CustomerServiceRepository()

    def validate_customer(self, customer_id: int) -> None:
        if not self.repository.customer_exists(customer_id):
            raise ValueError(f"客户不存在或不可用: {customer_id}")

    def archive_conversation(
        self,
        session_id: str,
        customer_id: int,
        messages: list[dict],
        transferred_to_human: bool,
    ) -> int:
        return self.repository.save_conversation(
            session_id=session_id,
            customer_id=customer_id,
            messages=messages,
            transferred_to_human=transferred_to_human,
        )

    def get_conversation(self, session_id: str, customer_id: int) -> Optional[dict]:
        return self.repository.get_conversation(session_id, customer_id)
