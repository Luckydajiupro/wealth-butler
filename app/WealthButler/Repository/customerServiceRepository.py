"""客服业务的 MySQL 数据访问层。"""
import json
from datetime import datetime
from typing import Optional
from uuid import uuid4

from app.Base.Client.mysqlClient import MySQLClient


class CustomerServiceRepository:
    """封装客服工单与会话归档的数据访问，不包含 Agent 决策逻辑。"""

    def __init__(self, client: Optional[MySQLClient] = None):
        self.client = client or MySQLClient()
        self._schema_checked = False

    def ensure_schema(self) -> None:
        """确保现有工单表支持需求文档规定的“客户转介”类型。"""
        if self._schema_checked:
            return
        rows = self.client.execute_sync(
            """
            SELECT COLUMN_NAME, COLUMN_TYPE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=%s AND TABLE_NAME='biz_work_order'
              AND COLUMN_NAME IN ('order_type', 'status')
            """,
            (self.client.database,),
        )
        column_types = {row["COLUMN_NAME"]: row["COLUMN_TYPE"] for row in rows}
        if "客户转介" not in column_types.get("order_type", ""):
            self.client.execute_sync(
                """
                ALTER TABLE biz_work_order
                MODIFY COLUMN order_type
                ENUM('风控预警','投诉','咨询','账户变更','业务申请','系统故障','客户转介')
                NOT NULL COMMENT '工单类型'
                """
            )
        # 兼容早期“待分配/已关闭”状态，新增后续 Agent 共同使用的标准状态。
        if "待处理" not in column_types.get("status", ""):
            self.client.execute_sync(
                """
                ALTER TABLE biz_work_order
                MODIFY COLUMN status
                ENUM('待分配','待处理','处理中','待审核','已完成','已驳回','已关闭')
                NOT NULL DEFAULT '待处理' COMMENT '工单状态'
                """
            )
        self._schema_checked = True

    def customer_exists(self, customer_id: int) -> bool:
        rows = self.client.execute_sync(
            "SELECT 1 AS found FROM base_user WHERE id=%s AND status='active' LIMIT 1",
            (customer_id,),
        )
        return bool(rows)

    def create_customer_referral(
        self,
        customer_id: int,
        intent_summary: str,
        priority: str,
        session_id: str,
    ) -> dict:
        self.ensure_schema()
        order_no = f"CS-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:6].upper()}"
        self.client.execute_sync(
            """
            INSERT INTO biz_work_order
                (order_no, order_type, source, customer_id, title, description,
                 priority, status, related_entity_type, handle_records)
            VALUES (%s, '客户转介', '转人工', %s, %s, %s, %s, '待处理', 'conversation', %s)
            """,
            (
                order_no,
                customer_id,
                "客户转人工服务",
                intent_summary,
                priority,
                json.dumps([{"session_id": session_id, "action": "客服Agent转人工"}], ensure_ascii=False),
            ),
        )
        rows = self.client.execute_sync(
            "SELECT id, order_no, status, created_at FROM biz_work_order WHERE order_no=%s LIMIT 1",
            (order_no,),
        )
        if not rows:
            raise RuntimeError("转人工工单写入后未能查询到记录")
        return rows[0]

    def create_transfer_work_order(
        self,
        customer_id: int,
        intent_summary: str,
        priority: str,
        session_id: str,
    ) -> dict:
        """兼容旧调用方；新的公共入口为 create_customer_referral。"""
        return self.create_customer_referral(
            customer_id=customer_id,
            intent_summary=intent_summary,
            priority=priority,
            session_id=session_id,
        )

    def save_conversation(
        self,
        session_id: str,
        customer_id: int,
        messages: list[dict],
        transferred_to_human: bool,
    ) -> int:
        now = datetime.now()
        archive_reason = "转人工" if transferred_to_human else "会话结束"
        payload = json.dumps(messages, ensure_ascii=False)
        rows = self.client.execute_sync(
            "SELECT id, start_time FROM conversation_archive WHERE session_id=%s LIMIT 1",
            (session_id,),
        )
        if rows:
            archive_id = rows[0]["id"]
            self.client.execute_sync(
                """
                UPDATE conversation_archive
                SET message_count=%s, messages=%s, resolved=%s,
                    transferred_to_human=%s, archive_reason=%s, end_time=%s
                WHERE id=%s
                """,
                (
                    len(messages), payload, int(not transferred_to_human),
                    int(transferred_to_human), archive_reason, now, archive_id,
                ),
            )
            return archive_id

        self.client.execute_sync(
            """
            INSERT INTO conversation_archive
                (session_id, customer_id, agent_type, message_count, messages,
                 resolved, transferred_to_human, archive_reason, start_time, end_time)
            VALUES (%s, %s, 'customer_service', %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session_id, customer_id, len(messages), payload,
                int(not transferred_to_human), int(transferred_to_human),
                archive_reason, now, now,
            ),
        )
        created = self.client.execute_sync(
            "SELECT id FROM conversation_archive WHERE session_id=%s ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        if not created:
            raise RuntimeError("会话归档写入后未能查询到记录")
        return created[0]["id"]

    def get_conversation(self, session_id: str, customer_id: int) -> Optional[dict]:
        rows = self.client.execute_sync(
            """
            SELECT id, session_id, customer_id, messages, transferred_to_human,
                   archive_reason, start_time, end_time
            FROM conversation_archive
            WHERE session_id=%s AND customer_id=%s
            ORDER BY id DESC LIMIT 1
            """,
            (session_id, customer_id),
        )
        if not rows:
            return None
        row = rows[0]
        if isinstance(row.get("messages"), str):
            row["messages"] = json.loads(row["messages"])
        return row

    def close(self) -> None:
        self.client.close()
