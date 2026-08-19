"""
数据库表结构修复脚本

修复问题：
1. conversation_archive 表缺少 start_time 字段
2. 确保所有表结构与Model定义一致

运行方式：
    cd D:/lqh/金融
    python scripts/fix_database_schema.py
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Base.Client.mysqlClient import MySQLClient


def check_table_exists(client: MySQLClient, table_name: str) -> bool:
    """检查表是否存在"""
    result = client.execute_sync(
        "SELECT COUNT(*) as cnt FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = %s",
        (table_name,)
    )
    return result[0]['cnt'] > 0


def check_column_exists(client: MySQLClient, table_name: str, column_name: str) -> bool:
    """检查字段是否存在"""
    result = client.execute_sync(
        "SELECT COUNT(*) as cnt FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table_name, column_name)
    )
    return result[0]['cnt'] > 0


def fix_conversation_archive_table(client: MySQLClient):
    """修复 conversation_archive 表"""
    print("=" * 60)
    print("修复 conversation_archive 表")
    print("=" * 60)

    # 检查表是否存在
    if not check_table_exists(client, 'conversation_archive'):
        print("[创建] conversation_archive 表不存在，执行创建...")
        from app.WealthButler.Models.conversationArchiveModel import ConversationArchiveModel
        client.execute_sync(ConversationArchiveModel.create_table_sql)
        print("[成功] 表创建成功")
        return

    print("[检查] 表已存在，检查字段...")

    # 检查并添加 start_time 字段
    if not check_column_exists(client, 'conversation_archive', 'start_time'):
        print("[修复] 缺少 start_time 字段，添加中...")
        client.execute_sync("""
            ALTER TABLE conversation_archive
            ADD COLUMN `start_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '会话开始时间'
            AFTER archive_reason
        """)
        print("[成功] start_time 字段已添加")
    else:
        print("[正常] start_time 字段已存在")

    # 检查并添加 end_time 字段
    if not check_column_exists(client, 'conversation_archive', 'end_time'):
        print("[修复] 缺少 end_time 字段，添加中...")
        client.execute_sync("""
            ALTER TABLE conversation_archive
            ADD COLUMN `end_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '会话结束时间'
            AFTER start_time
        """)
        print("[成功] end_time 字段已添加")
    else:
        print("[正常] end_time 字段已存在")

    # 添加索引（如果不存在）
    try:
        client.execute_sync("""
            ALTER TABLE conversation_archive
            ADD INDEX idx_start_time (start_time)
        """)
        print("[成功] idx_start_time 索引已添加")
    except Exception as e:
        if "Duplicate key name" in str(e):
            print("[正常] idx_start_time 索引已存在")
        else:
            print(f"[警告] 索引添加失败: {e}")

    print()


def verify_table_structure(client: MySQLClient):
    """验证表结构"""
    print("=" * 60)
    print("验证 conversation_archive 表结构")
    print("=" * 60)

    result = client.execute_sync("DESCRIBE conversation_archive")

    print(f"{'字段名':<30} {'类型':<30} {'允许NULL':<10} {'默认值'}")
    print("-" * 90)
    for row in result:
        field = row['Field']
        type_ = row['Type']
        null = row['Null']
        default = row['Default'] or ''
        print(f"{field:<30} {type_:<30} {null:<10} {default}")

    print()

    # 检查必需字段
    required_fields = ['id', 'session_id', 'customer_id', 'agent_type', 'message_count',
                       'messages', 'start_time', 'end_time', 'created_at']

    existing_fields = [row['Field'] for row in result]
    missing_fields = [f for f in required_fields if f not in existing_fields]

    if missing_fields:
        print(f"[错误] 缺少必需字段: {', '.join(missing_fields)}")
        return False
    else:
        print("[成功] 所有必需字段都存在")
        return True


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("数据库表结构修复脚本")
    print("=" * 60)
    print()

    try:
        # 连接数据库
        client = MySQLClient()
        print("[连接] MySQL 数据库连接成功")
        print()

        # 修复 conversation_archive 表
        fix_conversation_archive_table(client)

        # 验证表结构
        if verify_table_structure(client):
            print("\n" + "=" * 60)
            print("[完成] 数据库表结构修复成功！")
            print("=" * 60)
            return 0
        else:
            print("\n" + "=" * 60)
            print("[失败] 表结构验证失败，请检查日志")
            print("=" * 60)
            return 1

    except Exception as e:
        print(f"\n[错误] 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
