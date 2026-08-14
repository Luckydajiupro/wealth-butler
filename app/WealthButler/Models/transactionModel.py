from app.Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime
from decimal import Decimal


class TransactionModel(BaseDBModel):
    """
    交易流水表
    包含反洗钱字段（is_cash, counterparty_*, payer_account_name, device_fingerprint等）
    """

    table_alias: ClassVar[str] = "fin_transaction"

    create_table_sql: ClassVar[str] = f"""
    CREATE TABLE `fin_transaction` (
      `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
      `customer_id` INT NOT NULL COMMENT '客户ID',
      `product_id` INT COMMENT '产品ID（转账类交易可为空）',
      `transaction_type` ENUM('申购','赎回','转账','分红','定投') NOT NULL COMMENT '交易类型',
      `amount` DECIMAL(14,2) NOT NULL COMMENT '交易金额',
      `shares` DECIMAL(14,4) COMMENT '份额（申购/赎回适用）',
      `nav` DECIMAL(10,4) COMMENT '成交净值',
      `fee` DECIMAL(10,2) DEFAULT 0 COMMENT '手续费',
      `is_cash` TINYINT(1) DEFAULT 0 COMMENT '是否现金交易',
      `counterparty_account` VARCHAR(64) COMMENT '对手方账号',
      `counterparty_name` VARCHAR(100) COMMENT '对手方名称',
      `counterparty_region` VARCHAR(50) COMMENT '对手方注册地/地区',
      `payer_account_name` VARCHAR(100) COMMENT '资金来源账户实际付款人姓名',
      `device_fingerprint` VARCHAR(100) COMMENT '发起交易的设备指纹',
      `channel` VARCHAR(30) COMMENT '交易渠道（APP/柜台/网银等）',
      `status` ENUM('待确认','成交','失败','已撤销') DEFAULT '成交' COMMENT '交易状态',
      `transaction_time` DATETIME NOT NULL COMMENT '交易发生时间',
      `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
      PRIMARY KEY (`id`),
      KEY `idx_customer_id` (`customer_id`),
      KEY `idx_product_id` (`product_id`),
      KEY `idx_transaction_type` (`transaction_type`),
      KEY `idx_transaction_time` (`transaction_time`),
      KEY `idx_counterparty_account` (`counterparty_account`),
      KEY `idx_device_fingerprint` (`device_fingerprint`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='交易流水表';
    """

    # Pydantic字段定义
    id: Optional[int] = None
    customer_id: int
    product_id: Optional[int] = None
    transaction_type: str
    amount: Decimal
    shares: Optional[Decimal] = None
    nav: Optional[Decimal] = None
    fee: Decimal = Decimal("0")
    is_cash: bool = False
    counterparty_account: Optional[str] = None
    counterparty_name: Optional[str] = None
    counterparty_region: Optional[str] = None
    payer_account_name: Optional[str] = None
    device_fingerprint: Optional[str] = None
    channel: Optional[str] = None
    status: str = "成交"
    transaction_time: datetime
    created_at: Optional[datetime] = None

    @classmethod
    def find_by_customer_id(cls, customer_id: int, limit: int = 100, offset: int = 0):
        """根据客户ID查询交易记录"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE customer_id = %s
                  ORDER BY transaction_time DESC
                  LIMIT %s OFFSET %s"""
        results = db.execute(sql, (customer_id, limit, offset))
        return [cls(**row) for row in results]

    @classmethod
    def find_large_transactions(cls, customer_id: int, min_amount: Decimal, days: int = 7):
        """查询指定天数内的大额交易（支持RW-001规则）"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"""SELECT * FROM {cls.table_alias}
                  WHERE customer_id = %s
                  AND amount >= %s
                  AND transaction_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
                  ORDER BY transaction_time DESC"""
        results = db.execute(sql, (customer_id, min_amount, days))
        return [cls(**row) for row in results]

    @classmethod
    def count_by_customer_and_days(cls, customer_id: int, days: int = 7):
        """统计指定天数内的交易笔数（支持RW-002蚂蚁搬家规则）"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return 0
        sql = f"""SELECT COUNT(*) as cnt FROM {cls.table_alias}
                  WHERE customer_id = %s
                  AND transaction_time >= DATE_SUB(NOW(), INTERVAL %s DAY)"""
        results = db.execute(sql, (customer_id, days))
        return results[0]['cnt'] if results else 0
