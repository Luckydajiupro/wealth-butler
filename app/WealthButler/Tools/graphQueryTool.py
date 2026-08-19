"""GraphRAG 图谱查询工具。

投顾 Agent 通过本工具把自然语言查询转换为只读 Cypher，再交给 Neo4j
客户端执行。LLM 只负责生成查询草稿，真正执行前必须经过图谱 schema、
只读关键字、标签/关系和客户范围校验。
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.Base.Ai.base.baseTool import BaseTool
from app.Base.Client.neo4jClient import Neo4jClient
from app.WealthButler.Knowledge.graphSchema import Neo4jGraphSchema

logger = logging.getLogger(__name__)


class GraphQueryArgs(BaseModel):
    """GraphQuery 的 Function Calling 参数。"""

    customer_id: int = Field(..., gt=0, description="需要分析的客户 ID")
    depth: int = Field(default=2, ge=1, le=3, description="图谱查询跳数，范围 1-3")
    query_intent: str = Field(
        default="行业分散度",
        min_length=1,
        max_length=100,
        description="查询意图，例如行业分散度、持仓关联产品",
    )


class GraphQueryTool(BaseTool):
    """生成并执行客户范围内的只读 GraphRAG 查询。"""

    name = "GraphQuery"
    description = (
        "根据客户ID和查询意图生成Neo4j只读Cypher，查询客户持仓、产品、行业、"
        "风险等级等关系，并返回节点、边和行业分散度信号。禁止写入图谱。"
    )
    args_schema = GraphQueryArgs

    _allowed_params = {"customer_id", "depth", "limit"}
    _forbidden_query_tokens = (
        "UNION", "FOREACH", "LOAD CSV", "USE", "SHOW", "TERMINATE",
        "APOC", "DBMS", "TRANSACTION",
    )

    def __init__(self, client: Optional[Neo4jClient] = None, llm: Any = None):
        super().__init__()
        self.client = client
        self.llm = llm

    def execute(self, customer_id: int, depth: int = 2, query_intent: str = "行业分散度") -> Dict[str, Any]:
        """生成、校验并执行 Cypher；失败时返回结构化错误，不向 Agent 泄漏异常堆栈。"""
        try:
            generated = self._generate_query(customer_id, depth, query_intent)
            cypher = generated["cypher"]
            parameters = generated.get("parameters") or {}
            parameters["customer_id"] = customer_id
            parameters.setdefault("depth", depth)
            parameters.setdefault("limit", 50)

            valid, reason = self.validate_query(cypher, parameters, customer_id)
            if not valid:
                return {"success": False, "error": reason, "cypher": cypher}

            client = self.client or Neo4jClient()
            rows = client.run(cypher, parameters)
            normalized = self._normalize_rows(rows)
            normalized.update(
                {
                    "success": True,
                    "cypher": cypher,
                    "query_intent": query_intent,
                    "row_count": len(rows),
                }
            )
            return normalized
        except Exception as exc:  # 工具必须返回可序列化结果，供 Agent 降级处理
            logger.warning("GraphQuery 执行失败: %s", exc)
            return {"success": False, "error": f"图谱查询暂不可用: {exc}"}

    def _generate_query(self, customer_id: int, depth: int, query_intent: str) -> Dict[str, Any]:
        """Build the only graph shape needed by advisor ranking without an LLM round trip."""
        return {
            "cypher": (
                "MATCH (c:Customer {customer_id: $customer_id})"
                "-[h:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry) "
                "RETURN p.product_id AS product_id, p.product_code AS product_code, "
                "p.product_name AS product_name, i.industry_name AS industry_name, "
                "h.market_value AS market_value LIMIT $limit"
            ),
            "parameters": {"customer_id": customer_id, "depth": depth, "limit": 50},
        }

    @staticmethod
    def _parse_generation(content: str) -> Dict[str, Any]:
        """兼容 JSON、Markdown code fence 和纯 JSON 文本三种常见模型输出。"""
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM 未返回合法 JSON Cypher") from exc
        if isinstance(payload, str):
            payload = {"cypher": payload, "parameters": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("cypher"), str):
            raise ValueError("LLM 返回缺少 cypher 字段")
        if not isinstance(payload.get("parameters", {}), dict):
            raise ValueError("LLM 返回的 parameters 必须是对象")
        return payload

    @classmethod
    def validate_query(cls, cypher: str, parameters: Dict[str, Any], customer_id: int) -> tuple[bool, str]:
        """校验只读语句、图谱范围与参数，防止 LLM 生成越权或写操作。"""
        if not cypher or ";" in cypher.rstrip(";"):
            return False, "Cypher 必须是单条语句"
        valid, reason = Neo4jGraphSchema.validate_cypher_read_only(cypher)
        if not valid:
            return False, reason
        upper_cypher = re.sub(r"\s+", " ", cypher.upper()).strip()
        if any(re.search(rf"\b{re.escape(token)}\b", upper_cypher) for token in cls._forbidden_query_tokens):
            return False, "Cypher 包含未允许的查询指令"

        if "`" in cypher:
            return False, "Cypher 不允许使用反引号标识符"
        if len(re.findall(r"\bMATCH\b", upper_cypher)) != 1:
            return False, "Cypher 只允许一条以目标客户为根的 MATCH 路径"

        node_patterns = re.findall(r"\([^)]*\)", cypher)
        labels = set()
        customer_patterns = []
        for node_pattern in node_patterns:
            node_prefix = node_pattern.split("{", 1)[0]
            pattern_labels = re.findall(r":\s*([A-Za-z_]\w*)", node_prefix)
            if not pattern_labels:
                return False, "Cypher 中每个节点都必须声明白名单标签"
            labels.update(pattern_labels)
            if "Customer" in pattern_labels:
                customer_patterns.append(node_pattern)
        allowed_labels = set(Neo4jGraphSchema.NODE_LABELS)
        if labels - allowed_labels:
            return False, f"Cypher 使用了未允许的节点标签: {sorted(labels - allowed_labels)}"
        if len(customer_patterns) != 1:
            return False, "投顾图查询只能包含当前目标客户节点"
        relationships = set()
        for relationship_pattern in re.findall(r"\[[^\]]*\]", cypher):
            relationship_prefix = relationship_pattern.split("{", 1)[0]
            relationships.update(re.findall(r":\s*([A-Z_]\w*)", relationship_prefix))
        allowed_relationships = set(Neo4jGraphSchema.RELATIONSHIP_TYPES)
        if relationships - allowed_relationships:
            return False, f"Cypher 使用了未允许的关系类型: {sorted(relationships - allowed_relationships)}"
        if "RELATED_TO" in relationships:
            return False, "投顾图查询不允许扩展到关联客户"

        # A bare `$customer_id` predicate is not enough: bind it to a
        # Customer node so the query cannot return every customer.
        customer_scope = re.search(
            r"\(\s*[A-Za-z_]\w*\s*:\s*Customer\b[^)]*\bcustomer_id\s*:\s*\$customer_id\b",
            cypher,
        ) or re.search(
            r"\b[A-Za-z_]\w*\.customer_id\s*=\s*\$customer_id\b",
            cypher,
        )
        if not customer_scope:
            return False, "Cypher 必须将 Customer.customer_id 绑定到 $customer_id"
        if parameters.get("customer_id") != customer_id:
            return False, "Cypher 的 customer_id 参数与请求客户不一致"
        unknown = set(parameters) - cls._allowed_params
        if unknown:
            return False, f"Cypher 参数不在白名单内: {sorted(unknown)}"
        if not isinstance(parameters.get("limit", 50), int) or not 1 <= parameters.get("limit", 50) <= 100:
            return False, "Cypher limit 必须在 1-100 之间"
        if not isinstance(parameters.get("depth", 2), int) or not 1 <= parameters.get("depth", 2) <= 3:
            return False, "Cypher depth 必须在 1-3 之间"

        return True, ""

    @classmethod
    def _normalize_rows(cls, rows: list[Dict[str, Any]]) -> Dict[str, Any]:
        """把 Neo4j 行结果整理成 Agent 可消费的节点/边和分散度信号。"""
        nodes: list[Dict[str, Any]] = []
        edges: list[Dict[str, Any]] = []
        industry_weights: Dict[str, float] = {}
        product_industries: Dict[str, str] = {}

        def visit(value: Any):
            if isinstance(value, dict):
                if "industry_name" in value:
                    industry = str(value["industry_name"])
                    industry_weights[industry] = industry_weights.get(industry, 0.0) + float(value.get("market_value", 1) or 1)
                    if value.get("product_code"):
                        product_industries[str(value["product_code"])] = industry
                if "type" in value and value.get("type") in Neo4jGraphSchema.RELATIONSHIP_TYPES:
                    edges.append(value)
                elif any(key in value for key in ("id", "labels", "properties", "product_id", "customer_id")):
                    nodes.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(rows)
        if industry_weights:
            total = sum(industry_weights.values())
            proportions = [weight / total for weight in industry_weights.values()]
            diversity = 1.0 - sum(item * item for item in proportions)
        else:
            diversity = 0.0
        product_scores = {}
        if industry_weights:
            total = sum(industry_weights.values())
            product_scores = {
                code: round(max(0.0, min(1.0, 1.0 - industry_weights[industry] / total)), 4)
                for code, industry in product_industries.items()
            }
        return {
            "nodes": nodes,
            "edges": edges,
            "industry_weights": industry_weights,
            "diversity_score": round(max(0.0, min(1.0, diversity)), 4),
            "graph_score": round(max(0.0, min(1.0, diversity)), 4),
            "product_scores": product_scores,
            "rows": rows,
        }
