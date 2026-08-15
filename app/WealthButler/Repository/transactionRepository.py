from typing import List, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from app.WealthButler.Models.transactionModel import TransactionModel


class TransactionRepository:
    """
    交易流水Repository层
    封装交易记录的查询与创建操作，供风控规则引擎使用
    """

    @staticmethod
    def get_by_user_id(
        customer_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> List[TransactionModel]:
        """
        根据客户ID查询交易记录

        Args:
            customer_id: 客户ID
            limit: 返回条数
            offset: 偏移量

        Returns:
            交易记录列表
        """
        return TransactionModel.find_by_customer_id(customer_id, limit=limit, offset=offset)

    @staticmethod
    def get_recent_transactions(
        customer_id: int,
        days: int = 7,
        transaction_type: Optional[str] = None
    ) -> List[TransactionModel]:
        """
        查询客户最近N天的交易记录

        Args:
            customer_id: 客户ID
            days: 最近天数
            transaction_type: 交易类型筛选（可选）

        Returns:
            交易记录列表
        """
        TransactionModel._ensure_table_exists()
        db = TransactionModel.get_db_connection()
        if db is None:
            return []

        if transaction_type:
            sql = f"""SELECT * FROM {TransactionModel.table_alias}
                      WHERE customer_id = %s
                      AND transaction_type = %s
                      AND transaction_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
                      ORDER BY transaction_time DESC"""
            results = db.execute(sql, (customer_id, transaction_type, days))
        else:
            sql = f"""SELECT * FROM {TransactionModel.table_alias}
                      WHERE customer_id = %s
                      AND transaction_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
                      ORDER BY transaction_time DESC"""
            results = db.execute(sql, (customer_id, days))

        return [TransactionModel(**row) for row in results]

    @staticmethod
    def get_large_transactions(
        customer_id: int,
        min_amount: Decimal,
        days: int = 7
    ) -> List[TransactionModel]:
        """
        查询大额交易（供RW-001规则使用）

        Args:
            customer_id: 客户ID
            min_amount: 最小金额阈值
            days: 查询天数

        Returns:
            大额交易列表
        """
        return TransactionModel.find_large_transactions(customer_id, min_amount, days)

    @staticmethod
    def count_recent_transactions(customer_id: int, days: int = 7) -> int:
        """
        统计最近N天的交易笔数（供RW-002蚂蚁搬家规则使用）

        Args:
            customer_id: 客户ID
            days: 查询天数

        Returns:
            交易笔数
        """
        return TransactionModel.count_by_customer_and_days(customer_id, days)

    @staticmethod
    def create(
        customer_id: int,
        transaction_type: str,
        amount: Decimal,
        transaction_time: datetime,
        **kwargs
    ) -> Optional[TransactionModel]:
        """
        创建交易记录

        Args:
            customer_id: 客户ID
            transaction_type: 交易类型
            amount: 交易金额
            transaction_time: 交易时间
            **kwargs: 其他字段（product_id, shares, nav, fee等）

        Returns:
            创建的交易对象，失败返回None
        """
        transaction = TransactionModel(
            customer_id=customer_id,
            transaction_type=transaction_type,
            amount=amount,
            transaction_time=transaction_time,
            **kwargs
        )
        transaction_id = transaction.save()
        if transaction_id > 0:
            return transaction
        return None
