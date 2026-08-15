"""
业务操作权限常量定义（已整合到Base.Models.roleModel）

此文件保留作为兼容层，实际权限定义在 app/Base/Models/roleModel.py 的 Permission 类中。

使用方式：
    from app.Base.Models.roleModel import Permission, RoleModel

    # 检查权限
    role = RoleModel.find_by_name('advisor')
    if role.has_permission(Permission.OPERATION_PURCHASE):
        # 允许申购操作
        pass
"""

# 导入统一的权限类
from app.Base.Models.roleModel import Permission, RoleModel, BUILTIN_ROLES

# 兼容性别名（旧代码可能使用这些常量）
OPERATION_PURCHASE = Permission.OPERATION_PURCHASE
OPERATION_REDEEM = Permission.OPERATION_REDEEM
OPERATION_TRANSFER = Permission.OPERATION_TRANSFER
RISK_REASSESS = Permission.RISK_REASSESS
CUSTOMER_INFO_UPDATE = Permission.CUSTOMER_INFO_UPDATE
PRODUCT_QUERY = Permission.PRODUCT_QUERY
RISK_SUSPICIOUS_REPORT = Permission.RISK_SUSPICIOUS_REPORT
WORKORDER_CREATE = Permission.WORKORDER_CREATE


def check_permission(user_role: str, required_permission: str) -> bool:
    """
    检查用户角色是否具有所需权限

    Args:
        user_role: 用户角色名（customer/advisor/risk_officer/operator）
        required_permission: 所需权限标识

    Returns:
        bool: 是否有权限
    """
    # 从内置角色定义中获取权限
    role_config = BUILTIN_ROLES.get(user_role)
    if not role_config:
        return False

    permissions = role_config.get('permissions', [])
    return required_permission in permissions


def get_role_permissions(user_role: str) -> list:
    """
    获取角色的所有权限列表

    Args:
        user_role: 用户角色名

    Returns:
        list: 权限列表
    """
    role_config = BUILTIN_ROLES.get(user_role)
    if not role_config:
        return []

    return role_config.get('permissions', [])


# 使用示例
if __name__ == "__main__":
    print("业务权限已整合到 app.Base.Models.roleModel.Permission")
    print("\n财富管家业务角色:")
    for role_name in ['customer', 'advisor', 'risk_officer', 'operator']:
        perms = get_role_permissions(role_name)
        print(f"\n{role_name}: {len(perms)} 个权限")
        for perm in perms:
            print(f"  - {perm}")
