"""
WorkOrder存量数据迁移脚本

功能：
1. 检查biz_work_order表中是否有旧状态数据（待分配/已关闭）
2. 迁移旧状态到新状态（待分配→待处理，已关闭→已完成）
3. 输出迁移报告

执行前提：
- 已修改WorkOrderModel的表结构定义
- 数据库表尚未ALTER，仍保留旧状态数据
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.Base.Client.mysqlClient import mysql_client


def check_existing_data():
    """检查存量数据中的状态分布"""
    print("[Step 1] 检查存量数据")
    print("=" * 60)

    try:
        # 查询状态分布
        sql = """
        SELECT status, COUNT(*) as count
        FROM biz_work_order
        GROUP BY status
        ORDER BY count DESC
        """
        results = mysql_client.query(sql)

        if not results:
            print("[INFO] 表中无数据，无需迁移")
            return None

        print("\n当前状态分布:")
        status_map = {}
        for row in results:
            status = row['status']
            count = row['count']
            status_map[status] = count
            print(f"  {status}: {count} 条")

        return status_map

    except Exception as e:
        print(f"[ERROR] 查询失败: {e}")
        return None


def migrate_status():
    """迁移旧状态到新状态"""
    print("\n[Step 2] 执行状态迁移")
    print("=" * 60)

    migrations = [
        {
            'old': '待分配',
            'new': '待处理',
            'description': '待分配 → 待处理（默认状态统一）'
        },
        {
            'old': '已关闭',
            'new': '已完成',
            'description': '已关闭 → 已完成（状态枚举调整）'
        }
    ]

    total_migrated = 0

    try:
        for migration in migrations:
            old_status = migration['old']
            new_status = migration['new']
            desc = migration['description']

            # 检查是否有该状态的数据
            check_sql = "SELECT COUNT(*) as count FROM biz_work_order WHERE status = %s"
            result = mysql_client.query(check_sql, (old_status,))
            count = result[0]['count'] if result else 0

            if count == 0:
                print(f"\n[SKIP] {desc}")
                print(f"  无'{old_status}'状态数据，跳过")
                continue

            print(f"\n[MIGRATE] {desc}")
            print(f"  受影响行数: {count}")

            # 执行迁移
            update_sql = "UPDATE biz_work_order SET status = %s WHERE status = %s"
            mysql_client.execute(update_sql, (new_status, old_status))

            print(f"  ✓ 迁移完成")
            total_migrated += count

        print(f"\n[SUCCESS] 总计迁移 {total_migrated} 条记录")
        return True

    except Exception as e:
        print(f"\n[ERROR] 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_migration():
    """验证迁移结果"""
    print("\n[Step 3] 验证迁移结果")
    print("=" * 60)

    try:
        # 查询迁移后的状态分布
        sql = """
        SELECT status, COUNT(*) as count
        FROM biz_work_order
        GROUP BY status
        ORDER BY count DESC
        """
        results = mysql_client.query(sql)

        print("\n迁移后状态分布:")
        for row in results:
            status = row['status']
            count = row['count']
            print(f"  {status}: {count} 条")

        # 检查是否还有旧状态
        old_statuses = ['待分配', '已关闭']
        has_old = any(row['status'] in old_statuses for row in results)

        if has_old:
            print("\n[WARNING] 仍有旧状态数据，迁移可能不完整")
            return False
        else:
            print("\n[SUCCESS] 验证通过，所有旧状态已迁移")
            return True

    except Exception as e:
        print(f"\n[ERROR] 验证失败: {e}")
        return False


def main():
    """主函数"""
    print("WorkOrder存量数据迁移")
    print("=" * 60)

    # Step 1: 检查存量数据
    status_map = check_existing_data()

    if status_map is None:
        print("\n[EXIT] 无法读取数据，退出")
        return 1

    # 判断是否需要迁移
    needs_migration = ('待分配' in status_map) or ('已关闭' in status_map)

    if not needs_migration:
        print("\n[INFO] 无需迁移，所有数据状态正确")
        return 0

    # Step 2: 执行迁移
    print("\n" + "=" * 60)
    print("[WARNING] 即将修改数据库，请确认:")
    print("  - 待分配 → 待处理")
    print("  - 已关闭 → 已完成")
    print("=" * 60)

    confirm = input("是否继续？(yes/no): ")
    if confirm.lower() != 'yes':
        print("\n[CANCELLED] 用户取消操作")
        return 0

    success = migrate_status()

    if not success:
        print("\n[FAILED] 迁移失败，请检查错误信息")
        return 1

    # Step 3: 验证结果
    verify_success = verify_migration()

    if verify_success:
        print("\n" + "=" * 60)
        print("[COMPLETED] 迁移完成")
        print("=" * 60)
        print("\n下一步:")
        print("1. 可以执行 ALTER TABLE 修改状态枚举")
        print("2. 重启应用以使用新的 WorkOrderModel")
        return 0
    else:
        print("\n[FAILED] 验证失败")
        return 1


if __name__ == "__main__":
    exit(main())
