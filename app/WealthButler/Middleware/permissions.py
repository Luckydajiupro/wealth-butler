"""
权限定义模块 - 兼容层

统一从 app.Base.Models.roleModel.Permission 导入权限常量，
此模块作为兼容层保留旧代码的导入路径。

权限定义对应需求文档3.3节权限矩阵：
- product:query          产品查询（员工专用）
- product:recommend      产品推荐
- operation:purchase     申购操作
- operation:redeem       赎回操作
- operation:transfer     转账操作
- risk:reassess          风评重做
- risk:suspicious_report 可疑交易上报
- risk:override          风控规则人工复核/处置
- customer:info_update   客户信息更新
- workorder:create       工单创建
- data:nl2sql_query      NL2SQL数据查询
"""

from app.Base.Models.roleModel import Permission

# 导出所有业务权限常量
PRODUCT_QUERY = Permission.PRODUCT_QUERY
PRODUCT_RECOMMEND = Permission.PRODUCT_RECOMMEND
OPERATION_PURCHASE = Permission.OPERATION_PURCHASE
OPERATION_REDEEM = Permission.OPERATION_REDEEM
OPERATION_TRANSFER = Permission.OPERATION_TRANSFER
RISK_REASSESS = Permission.RISK_REASSESS
RISK_SUSPICIOUS_REPORT = Permission.RISK_SUSPICIOUS_REPORT
RISK_OVERRIDE = Permission.RISK_OVERRIDE
CUSTOMER_INFO_UPDATE = Permission.CUSTOMER_INFO_UPDATE
WORKORDER_CREATE = Permission.WORKORDER_CREATE
DATA_NL2SQL_QUERY = Permission.DATA_NL2SQL_QUERY


def check_permission(user_permissions: list, required_permission: str) -> bool:
    """
    检查用户是否拥有指定权限

    Args:
        user_permissions: 用户权限列表
        required_permission: 需要的权限

    Returns:
        bool: 是否拥有权限
    """
    return required_permission in user_permissions


def get_role_permissions(role_name: str) -> list:
    """
    获取角色的权限列表

    Args:
        role_name: 角色名称

    Returns:
        list: 权限列表
    """
    from app.Base.Models.roleModel import BUILTIN_ROLES

    role_config = BUILTIN_ROLES.get(role_name)
    if role_config:
        return role_config.get("permissions", [])
    return []
