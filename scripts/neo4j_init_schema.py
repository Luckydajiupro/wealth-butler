"""Neo4j 图数据库初始化脚本

功能：
    1. 创建节点类型的唯一性约束和索引
    2. 创建示例节点和关系
    3. 验证图谱结构

使用方式：
    python scripts/neo4j_init_schema.py

节点类型（根据需求文档 §2.3）：
    - Customer（客户）：属性 user_id, name, risk_level
    - Product（产品）：属性 product_code, name, risk_level
    - Transaction（交易）：属性 transaction_id, amount, timestamp
    - RiskFactor（风险因子）：属性 factor_type, severity

关系类型：
    - (Customer)-[:HOLDS]->(Product)           # 客户持有产品
    - (Customer)-[:TRANSACTED]->(Transaction)  # 客户发起交易
    - (Transaction)-[:INVOLVES]->(Product)     # 交易涉及产品
    - (Customer)-[:HAS_RISK]->(RiskFactor)     # 客户关联风险因子
"""

import sys
import os
from datetime import datetime
from decimal import Decimal

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app.Base.Client.neo4jClient import Neo4jClient


# ══════════════════════════════════════════════════════════════
# 第一部分：创建约束和索引
# ══════════════════════════════════════════════════════════════

def create_constraints_and_indexes(client: Neo4jClient):
    """创建唯一性约束和索引

    唯一性约束会自动创建对应的索引，提升查询性能
    """
    print("\n" + "="*60)
    print("【步骤 1】创建唯一性约束和索引")
    print("="*60)

    constraints = [
        # Customer 节点：user_id 唯一
        {
            'cypher': 'CREATE CONSTRAINT customer_user_id_unique IF NOT EXISTS '
                     'FOR (c:Customer) REQUIRE c.user_id IS UNIQUE',
            'description': 'Customer.user_id 唯一性约束'
        },
        # Product 节点：product_code 唯一
        {
            'cypher': 'CREATE CONSTRAINT product_code_unique IF NOT EXISTS '
                     'FOR (p:Product) REQUIRE p.product_code IS UNIQUE',
            'description': 'Product.product_code 唯一性约束'
        },
        # Transaction 节点：transaction_id 唯一
        {
            'cypher': 'CREATE CONSTRAINT transaction_id_unique IF NOT EXISTS '
                     'FOR (t:Transaction) REQUIRE t.transaction_id IS UNIQUE',
            'description': 'Transaction.transaction_id 唯一性约束'
        },
    ]

    for constraint in constraints:
        try:
            client.run(constraint['cypher'])
            print(f"✅ {constraint['description']}")
        except Exception as e:
            print(f"⚠️  {constraint['description']} 创建失败或已存在: {e}")

    # 创建索引（用于加速范围查询和排序）
    indexes = [
        # Transaction.timestamp 索引（用于时间范围查询）
        {
            'cypher': 'CREATE INDEX transaction_timestamp IF NOT EXISTS '
                     'FOR (t:Transaction) ON (t.timestamp)',
            'description': 'Transaction.timestamp 索引'
        },
        # Customer.risk_level 索引（用于风险等级筛选）
        {
            'cypher': 'CREATE INDEX customer_risk_level IF NOT EXISTS '
                     'FOR (c:Customer) ON (c.risk_level)',
            'description': 'Customer.risk_level 索引'
        },
        # RiskFactor.severity 索引（用于严重程度筛选）
        {
            'cypher': 'CREATE INDEX risk_factor_severity IF NOT EXISTS '
                     'FOR (r:RiskFactor) ON (r.severity)',
            'description': 'RiskFactor.severity 索引'
        },
    ]

    for index in indexes:
        try:
            client.run(index['cypher'])
            print(f"✅ {index['description']}")
        except Exception as e:
            print(f"⚠️  {index['description']} 创建失败或已存在: {e}")


# ══════════════════════════════════════════════════════════════
# 第二部分：创建示例节点
# ══════════════════════════════════════════════════════════════

def create_sample_nodes(client: Neo4jClient):
    """创建示例节点（客户、产品、交易、风险因子）"""
    print("\n" + "="*60)
    print("【步骤 2】创建示例节点")
    print("="*60)

    # ────────────── Customer 节点 ──────────────
    customers = [
        {'user_id': 1001, 'name': '张三', 'risk_level': 'low', 'age': 35, 'city': '上海'},
        {'user_id': 1002, 'name': '李四', 'risk_level': 'medium', 'age': 42, 'city': '北京'},
        {'user_id': 1003, 'name': '王五', 'risk_level': 'high', 'age': 28, 'city': '深圳'},
    ]

    print("\n创建 Customer 节点：")
    for customer in customers:
        client.create_node('Customer', customer)
        print(f"  ✅ {customer['name']} (ID: {customer['user_id']}, 风险等级: {customer['risk_level']})")

    # ────────────── Product 节点 ──────────────
    products = [
        {
            'product_code': 'FUND_005827',
            'name': '易方达蓝筹精选混合',
            'risk_level': 'R3',
            'category': 'fund',
            'expected_return': 0.08
        },
        {
            'product_code': 'BOND_110052',
            'name': '中国国债ETF',
            'risk_level': 'R1',
            'category': 'bond',
            'expected_return': 0.03
        },
        {
            'product_code': 'STOCK_600519',
            'name': '贵州茅台',
            'risk_level': 'R4',
            'category': 'stock',
            'expected_return': 0.15
        },
    ]

    print("\n创建 Product 节点：")
    for product in products:
        client.create_node('Product', product)
        print(f"  ✅ {product['name']} (代码: {product['product_code']}, 风险等级: {product['risk_level']})")

    # ────────────── Transaction 节点 ──────────────
    transactions = [
        {
            'transaction_id': 202408150001,
            'amount': 60000.00,
            'timestamp': '2024-08-15 10:30:00',
            'type': 'buy',
            'channel': 'mobile_app'
        },
        {
            'transaction_id': 202408150002,
            'amount': 20000.00,
            'timestamp': '2024-08-15 14:15:00',
            'type': 'buy',
            'channel': 'web'
        },
        {
            'transaction_id': 202408150003,
            'amount': 150000.00,
            'timestamp': '2024-08-15 16:45:00',
            'type': 'sell',
            'channel': 'mobile_app'
        },
    ]

    print("\n创建 Transaction 节点：")
    for transaction in transactions:
        client.create_node('Transaction', transaction)
        print(f"  ✅ 交易 {transaction['transaction_id']} "
              f"(金额: ¥{transaction['amount']:,.2f}, 类型: {transaction['type']})")

    # ────────────── RiskFactor 节点 ──────────────
    risk_factors = [
        {
            'factor_id': 'RF001',
            'factor_type': 'large_transaction',
            'severity': 'high',
            'description': '单日大额交易（≥5万）',
            'threshold': 50000.00
        },
        {
            'factor_id': 'RF002',
            'factor_type': 'high_risk_product',
            'severity': 'medium',
            'description': '持有高风险产品（R4/R5）',
            'threshold': None
        },
        {
            'factor_id': 'RF003',
            'factor_type': 'frequent_trading',
            'severity': 'low',
            'description': '频繁交易（日均交易次数 ≥10）',
            'threshold': 10
        },
    ]

    print("\n创建 RiskFactor 节点：")
    for risk_factor in risk_factors:
        client.create_node('RiskFactor', risk_factor)
        print(f"  ✅ {risk_factor['description']} "
              f"(ID: {risk_factor['factor_id']}, 严重程度: {risk_factor['severity']})")


# ══════════════════════════════════════════════════════════════
# 第三部分：创建示例关系
# ══════════════════════════════════════════════════════════════

def create_sample_relationships(client: Neo4jClient):
    """创建示例关系（客户-产品-交易-风险因子）"""
    print("\n" + "="*60)
    print("【步骤 3】创建示例关系")
    print("="*60)

    # ────────────── (Customer)-[:HOLDS]->(Product) ──────────────
    print("\n创建 HOLDS 关系（客户持有产品）：")

    holds_relationships = [
        {
            'customer': {'user_id': 1001},
            'product': {'product_code': 'FUND_005827'},
            'properties': {'quantity': 10000, 'purchase_date': '2024-07-01', 'cost': 50000.00}
        },
        {
            'customer': {'user_id': 1002},
            'product': {'product_code': 'BOND_110052'},
            'properties': {'quantity': 5000, 'purchase_date': '2024-06-15', 'cost': 20000.00}
        },
        {
            'customer': {'user_id': 1003},
            'product': {'product_code': 'STOCK_600519'},
            'properties': {'quantity': 100, 'purchase_date': '2024-08-01', 'cost': 180000.00}
        },
    ]

    for rel in holds_relationships:
        client.create_relationship(
            from_label='Customer',
            from_props=rel['customer'],
            to_label='Product',
            to_props=rel['product'],
            rel_type='HOLDS',
            rel_props=rel['properties']
        )
        print(f"  ✅ Customer({rel['customer']['user_id']}) -[:HOLDS]-> "
              f"Product({rel['product']['product_code']})")

    # ────────────── (Customer)-[:TRANSACTED]->(Transaction) ──────────────
    print("\n创建 TRANSACTED 关系（客户发起交易）：")

    transacted_relationships = [
        {
            'customer': {'user_id': 1001},
            'transaction': {'transaction_id': 202408150001}
        },
        {
            'customer': {'user_id': 1002},
            'transaction': {'transaction_id': 202408150002}
        },
        {
            'customer': {'user_id': 1003},
            'transaction': {'transaction_id': 202408150003}
        },
    ]

    for rel in transacted_relationships:
        client.create_relationship(
            from_label='Customer',
            from_props=rel['customer'],
            to_label='Transaction',
            to_props=rel['transaction'],
            rel_type='TRANSACTED'
        )
        print(f"  ✅ Customer({rel['customer']['user_id']}) -[:TRANSACTED]-> "
              f"Transaction({rel['transaction']['transaction_id']})")

    # ────────────── (Transaction)-[:INVOLVES]->(Product) ──────────────
    print("\n创建 INVOLVES 关系（交易涉及产品）：")

    involves_relationships = [
        {
            'transaction': {'transaction_id': 202408150001},
            'product': {'product_code': 'FUND_005827'}
        },
        {
            'transaction': {'transaction_id': 202408150002},
            'product': {'product_code': 'BOND_110052'}
        },
        {
            'transaction': {'transaction_id': 202408150003},
            'product': {'product_code': 'STOCK_600519'}
        },
    ]

    for rel in involves_relationships:
        client.create_relationship(
            from_label='Transaction',
            from_props=rel['transaction'],
            to_label='Product',
            to_props=rel['product'],
            rel_type='INVOLVES'
        )
        print(f"  ✅ Transaction({rel['transaction']['transaction_id']}) -[:INVOLVES]-> "
              f"Product({rel['product']['product_code']})")

    # ────────────── (Customer)-[:HAS_RISK]->(RiskFactor) ──────────────
    print("\n创建 HAS_RISK 关系（客户关联风险因子）：")

    has_risk_relationships = [
        {
            'customer': {'user_id': 1001},
            'risk_factor': {'factor_id': 'RF001'},
            'properties': {'detected_at': '2024-08-15 10:35:00', 'confidence': 0.95}
        },
        {
            'customer': {'user_id': 1003},
            'risk_factor': {'factor_id': 'RF002'},
            'properties': {'detected_at': '2024-08-15 16:50:00', 'confidence': 0.88}
        },
    ]

    for rel in has_risk_relationships:
        client.create_relationship(
            from_label='Customer',
            from_props=rel['customer'],
            to_label='RiskFactor',
            to_props=rel['risk_factor'],
            rel_type='HAS_RISK',
            rel_props=rel['properties']
        )
        print(f"  ✅ Customer({rel['customer']['user_id']}) -[:HAS_RISK]-> "
              f"RiskFactor({rel['risk_factor']['factor_id']})")


# ══════════════════════════════════════════════════════════════
# 第四部分：验证图谱结构
# ══════════════════════════════════════════════════════════════

def verify_graph_structure(client: Neo4jClient):
    """验证图谱结构（统计节点和关系数量）"""
    print("\n" + "="*60)
    print("【步骤 4】验证图谱结构")
    print("="*60)

    # 统计节点数量
    print("\n节点统计：")
    node_labels = ['Customer', 'Product', 'Transaction', 'RiskFactor']

    for label in node_labels:
        count_result = client.run(f'MATCH (n:{label}) RETURN count(n) as count')
        count = count_result[0]['count'] if count_result else 0
        print(f"  • {label}: {count} 个")

    # 统计关系数量
    print("\n关系统计：")
    rel_types = ['HOLDS', 'TRANSACTED', 'INVOLVES', 'HAS_RISK']

    for rel_type in rel_types:
        count_result = client.run(f'MATCH ()-[r:{rel_type}]->() RETURN count(r) as count')
        count = count_result[0]['count'] if count_result else 0
        print(f"  • {rel_type}: {count} 条")

    # 示例查询：查找张三的所有持仓和交易
    print("\n" + "-"*60)
    print("示例查询：查找张三的持仓和交易")
    print("-"*60)

    cypher = """
    MATCH (c:Customer {name: '张三'})-[:HOLDS]->(p:Product)
    RETURN c.name as customer_name, p.name as product_name, p.risk_level as risk_level
    """
    holdings = client.run(cypher)

    if holdings:
        print("\n持仓产品：")
        for holding in holdings:
            print(f"  • {holding['product_name']} (风险等级: {holding['risk_level']})")

    cypher = """
    MATCH (c:Customer {name: '张三'})-[:TRANSACTED]->(t:Transaction)-[:INVOLVES]->(p:Product)
    RETURN t.transaction_id as txn_id, t.amount as amount, t.type as type, p.name as product_name
    """
    transactions = client.run(cypher)

    if transactions:
        print("\n交易记录：")
        for txn in transactions:
            print(f"  • 交易 {txn['txn_id']}: {txn['type']} {txn['product_name']} "
                  f"¥{txn['amount']:,.2f}")

    # 示例查询：查找所有高风险客户
    print("\n" + "-"*60)
    print("示例查询：查找所有关联风险因子的客户")
    print("-"*60)

    cypher = """
    MATCH (c:Customer)-[r:HAS_RISK]->(rf:RiskFactor)
    RETURN c.name as customer_name, c.risk_level as risk_level,
           rf.factor_type as factor_type, rf.severity as severity,
           r.confidence as confidence
    ORDER BY rf.severity DESC, r.confidence DESC
    """
    risk_customers = client.run(cypher)

    if risk_customers:
        for risk in risk_customers:
            print(f"  • {risk['customer_name']} (风险等级: {risk['risk_level']})")
            print(f"    关联风险: {risk['factor_type']} (严重程度: {risk['severity']}, "
                  f"置信度: {risk['confidence']})")


# ══════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════

def main():
    """主函数：执行完整的图谱初始化流程"""
    print("\n" + "╔" + "="*58 + "╗")
    print("║" + " "*15 + "Neo4j 图数据库初始化" + " "*16 + "║")
    print("╚" + "="*58 + "╝")

    with Neo4jClient() as client:
        # 步骤 1：创建约束和索引
        create_constraints_and_indexes(client)

        # 步骤 2：创建示例节点
        create_sample_nodes(client)

        # 步骤 3：创建示例关系
        create_sample_relationships(client)

        # 步骤 4：验证图谱结构
        verify_graph_structure(client)

    print("\n" + "="*60)
    print("【初始化完成】")
    print("="*60)
    print("\n提示：")
    print("  1. 可通过 Neo4j Browser 查看图谱：http://localhost:7474")
    print("  2. 使用 MATCH (n) RETURN n LIMIT 25 查看所有节点")
    print("  3. 使用 CALL db.schema.visualization() 查看图谱结构")
    print("  4. 开发者可参考本脚本添加自己的节点和关系\n")


if __name__ == '__main__':
    main()
