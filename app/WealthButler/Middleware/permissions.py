"""
业务操作权限常量定义

用于RBAC权限控制，定义8个业务操作所需的权限标识。
"""

# ==================== 业务操作权限 ====================

# 理财产品操作
OPERATION_PURCHASE = "operation:purchase"           # 申购操作（购买理财产品）
OPERATION_REDEEM = "operation:redeem"               # 赎回操作（赎回理财产品）
OPERATION_TRANSFER = "operation:transfer"           # 转账操作（账户间转账）

# 风险评估
RISK_REASSESS = "risk:reassess"                     # 风险重评（重新评估客户风险等级）

# 客户信息管理
CUSTOMER_INFO_UPDATE = "customer:info_update"       # 客户信息更新（修改客户基本信息）

# 产品查询
PRODUCT_QUERY = "product:query"                     # 产品查询（查询理财产品信息）

# 风控上报
RISK_SUSPICIOUS_REPORT = "risk:suspicious_report"   # 可疑行为上报（上报可疑交易/行为）

# 工单管理
WORKORDER_CREATE = "workorder:create"               # 创建工单（创建业务工单）


# ==================== 角色权限映射 ====================

# 客户权限
CUSTOMER_PERMISSIONS = [
    PRODUCT_QUERY,              # 可查询产品
    WORKORDER_CREATE,           # 可创建工单
]

# 理财顾问权限
ADVISOR_PERMISSIONS = [
    OPERATION_PURCHASE,         # 可代客申购
    OPERATION_REDEEM,           # 可代客赎回
    OPERATION_TRANSFER,         # 可协助转账
    RISK_REASSESS,              # 可触发风险重评
    CUSTOMER_INFO_UPDATE,       # 可更新客户信息
    PRODUCT_QUERY,              # 可查询产品
    RISK_SUSPICIOUS_REPORT,     # 可上报可疑行为
    WORKORDER_CREATE,           # 可创建工单
]

# 风控专员权限
RISK_OFFICER_PERMISSIONS = [
    RISK_REASSESS,              # 可风险重评
    CUSTOMER_INFO_UPDATE,       # 可更新客户风险标记
    PRODUCT_QUERY,              # 可查询产品
    RISK_SUSPICIOUS_REPORT,     # 可上报可疑行为
    WORKORDER_CREATE,           # 可创建工单
]

# 运营专员权限
OPERATOR_PERMISSIONS = [
    OPERATION_PURCHASE,         # 可处理申购
    OPERATION_REDEEM,           # 可处理赎回
    OPERATION_TRANSFER,         # 可处理转账
    CUSTOMER_INFO_UPDATE,       # 可更新客户信息
    PRODUCT_QUERY,              # 可查询产品
    WORKORDER_CREATE,           # 可创建工单
]


# ==================== 权限验证函数 ====================

def check_permission(user_role: str, required_permission: str) -> bool:
    """
    检查用户角色是否具有所需权限

    Args:
        user_role: 用户角色（customer/advisor/risk_officer/operator）
        required_permission: 所需权限标识

    Returns:
        bool: 是否有权限
    """
    role_permissions = {
        'customer': CUSTOMER_PERMISSIONS,
        'advisor': ADVISOR_PERMISSIONS,
        'risk_officer': RISK_OFFICER_PERMISSIONS,
        'operator': OPERATOR_PERMISSIONS,
    }

    permissions = role_permissions.get(user_role, [])
    return required_permission in permissions


def get_role_permissions(user_role: str) -> list:
    """
    获取角色的所有权限列表

    Args:
        user_role: 用户角色

    Returns:
        list: 权限列表
    """
    role_permissions = {
        'customer': CUSTOMER_PERMISSIONS,
        'advisor': ADVISOR_PERMISSIONS,
        'risk_officer': RISK_OFFICER_PERMISSIONS,
        'operator': OPERATOR_PERMISSIONS,
    }

    return role_permissions.get(user_role, [])


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 示例1: 检查权限
    print("客户是否可以申购产品:", check_permission('customer', OPERATION_PURCHASE))
    print("理财顾问是否可以申购产品:", check_permission('advisor', OPERATION_PURCHASE))

    # 示例2: 获取角色权限
    print("\n理财顾问的所有权限:")
    for perm in get_role_permissions('advisor'):
        print(f"  - {perm}")

    print("\n客户的所有权限:")
    for perm in get_role_permissions('customer'):
        print(f"  - {perm}")
