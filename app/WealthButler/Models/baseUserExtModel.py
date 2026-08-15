from app.Base.Repository.base.baseDBModel import BaseDBModel
from typing import Optional, ClassVar
from datetime import datetime
import json


class BaseUserExtModel(BaseDBModel):
    """
    base_user表扩展模型（理财业务字段）
    不修改脚手架原有UserModel，通过ALTER TABLE补列方式扩展
    """

    table_alias = "base_user"

    # 扩展字段的ALTER TABLE SQL
    create_table_sql = """
    -- 此SQL仅用于补列，base_user表本体由脚手架UserModel创建
    ALTER TABLE `base_user`
    ADD COLUMN IF NOT EXISTS `user_type` ENUM('CUSTOMER','EMPLOYEE') NOT NULL DEFAULT 'CUSTOMER' COMMENT '用户大类',
    ADD COLUMN IF NOT EXISTS `employee_role` ENUM('理财顾问','风控专员','客户经理','业务管理员') COMMENT '员工主角色',
    ADD COLUMN IF NOT EXISTS `advisor_level` ENUM('初级','中级','高级') COMMENT '理财顾问执业等级',
    ADD COLUMN IF NOT EXISTS `customer_level` ENUM('普通','金卡','白金','钻石','私行') DEFAULT '普通' COMMENT '客户等级';

    -- 添加索引
    ALTER TABLE `base_user` ADD INDEX IF NOT EXISTS `idx_user_type` (`user_type`);
    """

    # Pydantic字段定义（完整字段，包含脚手架原有+新增）
    id: Optional[int] = None
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    password_hash: str
    source_module: str = "fin"
    status: str = "active"
    last_login_at: Optional[datetime] = None
    extra_data: Optional[dict] = None

    # 新增业务字段
    user_type: str = "CUSTOMER"
    employee_role: Optional[str] = None
    advisor_level: Optional[str] = None
    customer_level: str = "普通"

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    def model_dump(self, **kwargs):
        """重写model_dump，序列化JSON字段"""
        data = super().model_dump(**kwargs)
        # 将extra_data字典序列化为JSON字符串
        if 'extra_data' in data and isinstance(data['extra_data'], dict):
            data['extra_data'] = json.dumps(data['extra_data'], ensure_ascii=False)
        return data

    @classmethod
    def find_by_user_type(cls, user_type: str, limit: int = None, offset: int = 0):
        """按用户类型查询"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"SELECT * FROM {cls.table_alias} WHERE user_type = %s AND deleted_at IS NULL"
        params = [user_type]

        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        if offset:
            sql += " OFFSET %s"
            params.append(offset)

        results = db.execute(sql, tuple(params))
        return [cls(**row) for row in results]

    @classmethod
    def find_by_employee_role(cls, role: str):
        """按员工角色查询（用于路由分发）"""
        cls._ensure_table_exists()
        db = cls.get_db_connection()
        if db is None:
            return []
        sql = f"SELECT * FROM {cls.table_alias} WHERE employee_role = %s AND deleted_at IS NULL"
        results = db.execute(sql, (role,))
        return [cls(**row) for row in results]
