"""
Neo4j图谱Schema定义与初始化
包含6种节点、7种关系的建模，以及唯一性约束、索引创建
"""
from typing import ClassVar


class Neo4jGraphSchema:
    """
    Neo4j图谱Schema定义
    用于GraphRAG增强检索、持仓关系查询、关联账户识别
    """

    # 节点定义
    NODE_LABELS: ClassVar[list[str]] = [
        "Customer",      # 客户节点（对齐base_user.id）
        "Product",       # 产品节点（对齐fin_product.id）
        "RiskLevel",     # 风险等级节点（C1-C5客户等级/R1-R5产品等级）
        "Industry",      # 行业节点
        "Market",        # 市场节点（A股/港股/美股/债券市场）
        "FundManager"    # 基金管理人节点
    ]

    # 关系定义
    RELATIONSHIP_TYPES: ClassVar[list[str]] = [
        "HAS_RISK_LEVEL",  # Customer→RiskLevel，客户当前风险分级
        "INVESTS_IN",      # Customer→Product，持仓关系（含shares/market_value）
        "BELONGS_TO",      # Product→Industry，产品所属行业
        "MANAGED_BY",      # Product→FundManager，基金管理人
        "SUITABLE_FOR",    # Product→RiskLevel，适当性匹配
        "LOCATED_IN",      # Industry→Market，行业所属市场
        "RELATED_TO"       # Customer→Customer，关联账户（家庭成员/同一控制人等）
    ]

    # 节点属性定义
    NODE_PROPERTIES: ClassVar[dict] = {
        "Customer": ["customer_id", "name", "risk_level"],
        "Product": ["product_id", "product_code", "product_name", "risk_level"],
        "RiskLevel": ["level"],  # C1-C5 或 R1-R5
        "Industry": ["industry_name"],
        "Market": ["market_name"],
        "FundManager": ["manager_name"]
    }

    # 关系属性定义
    RELATIONSHIP_PROPERTIES: ClassVar[dict] = {
        "HAS_RISK_LEVEL": [],
        "INVESTS_IN": ["shares", "market_value"],  # 对齐fin_holdings
        "BELONGS_TO": [],
        "MANAGED_BY": [],
        "SUITABLE_FOR": [],
        "LOCATED_IN": [],
        "RELATED_TO": ["relation_type"]  # 家庭成员/同一控制人/共用设备等
    }

    # 唯一性约束Cypher（避免重复节点）
    UNIQUE_CONSTRAINTS: ClassVar[list[str]] = [
        "CREATE CONSTRAINT customer_id_unique IF NOT EXISTS FOR (c:Customer) REQUIRE c.customer_id IS UNIQUE",
        "CREATE CONSTRAINT product_id_unique IF NOT EXISTS FOR (p:Product) REQUIRE p.product_id IS UNIQUE",
        "CREATE CONSTRAINT risk_level_unique IF NOT EXISTS FOR (r:RiskLevel) REQUIRE r.level IS UNIQUE",
        "CREATE CONSTRAINT industry_name_unique IF NOT EXISTS FOR (i:Industry) REQUIRE i.industry_name IS UNIQUE",
        "CREATE CONSTRAINT market_name_unique IF NOT EXISTS FOR (m:Market) REQUIRE m.market_name IS UNIQUE",
        "CREATE CONSTRAINT manager_name_unique IF NOT EXISTS FOR (f:FundManager) REQUIRE f.manager_name IS UNIQUE"
    ]

    # 索引定义Cypher（加速查询）
    INDEXES: ClassVar[list[str]] = [
        "CREATE INDEX customer_risk_level_idx IF NOT EXISTS FOR (c:Customer) ON (c.risk_level)",
        "CREATE INDEX product_risk_level_idx IF NOT EXISTS FOR (p:Product) ON (p.risk_level)",
        "CREATE INDEX product_code_idx IF NOT EXISTS FOR (p:Product) ON (p.product_code)"
    ]

    # 静态风险等级节点初始化Cypher
    INIT_RISK_LEVELS: ClassVar[list[str]] = [
        # 客户风险等级
        "MERGE (r:RiskLevel {level: 'C1'})",
        "MERGE (r:RiskLevel {level: 'C2'})",
        "MERGE (r:RiskLevel {level: 'C3'})",
        "MERGE (r:RiskLevel {level: 'C4'})",
        "MERGE (r:RiskLevel {level: 'C5'})",
        # 产品风险等级
        "MERGE (r:RiskLevel {level: 'R1'})",
        "MERGE (r:RiskLevel {level: 'R2'})",
        "MERGE (r:RiskLevel {level: 'R3'})",
        "MERGE (r:RiskLevel {level: 'R4'})",
        "MERGE (r:RiskLevel {level: 'R5'})"
    ]

    # Mock市场节点初始化Cypher
    INIT_MARKETS: ClassVar[list[str]] = [
        "MERGE (m:Market {market_name: 'A股'})",
        "MERGE (m:Market {market_name: '港股'})",
        "MERGE (m:Market {market_name: '美股'})",
        "MERGE (m:Market {market_name: '债券市场'})",
        "MERGE (m:Market {market_name: '货币市场'})"
    ]

    # NL2Cypher安全校验：只读白名单（不含写操作关键字）
    CYPHER_READ_ONLY_KEYWORDS: ClassVar[list[str]] = [
        "MATCH", "RETURN", "WHERE", "WITH", "LIMIT", "SKIP",
        "ORDER BY", "COUNT", "SUM", "AVG", "COLLECT"
    ]

    # NL2Cypher危险关键字黑名单
    CYPHER_DANGEROUS_KEYWORDS: ClassVar[list[str]] = [
        "DETACH DELETE", "DELETE", "CREATE", "MERGE", "SET",
        "REMOVE", "DROP", "CALL"
    ]

    @classmethod
    def get_init_cypher_list(cls) -> list[str]:
        """
        获取图谱初始化Cypher语句列表
        包含：唯一性约束 + 索引 + 静态节点

        Returns:
            Cypher语句列表，按顺序执行
        """
        return (
            cls.UNIQUE_CONSTRAINTS +
            cls.INDEXES +
            cls.INIT_RISK_LEVELS +
            cls.INIT_MARKETS
        )

    @classmethod
    def validate_cypher_read_only(cls, cypher: str) -> tuple[bool, str]:
        """
        校验Cypher是否为只读查询（NL2Cypher安全校验层）

        Args:
            cypher: 待校验的Cypher语句

        Returns:
            (is_valid, error_message)
        """
        cypher_upper = cypher.upper()

        # 检查危险关键字
        for keyword in cls.CYPHER_DANGEROUS_KEYWORDS:
            if keyword in cypher_upper:
                return False, f"禁止使用写操作关键字: {keyword}"

        # 必须包含至少一个只读关键字
        has_read_keyword = any(
            keyword in cypher_upper
            for keyword in ["MATCH", "RETURN"]
        )
        if not has_read_keyword:
            return False, "Cypher必须包含MATCH或RETURN关键字"

        return True, ""
