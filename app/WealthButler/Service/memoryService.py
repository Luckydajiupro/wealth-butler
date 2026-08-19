"""MemoryService —— 三层记忆业务层（组E，需求 F4.2）

本模块是"三层记忆架构"的唯一业务入口，供各 Agent 的 MemoryRecallMiddleware 调用：

- 短期记忆（即时）：Redis `session:{session_id}:messages` List，滑动 TTL 30 分钟、绝对上限 24 小时
  （Redis List 无法可靠表达首次创建时间，用显式元数据键 `session:{session_id}:meta` 记录，备案 EB-E-03）
- 中期记忆（画像）：MySQL `fin_customer_profile.memory_units` + Redis `profile:{customer_id}`
  缓存（Cache-Aside，TTL 7 天 = 604800 秒；写后主动失效）
- 长期记忆（语义+关联）：Milvus `fin_customer_memory_collection` 向量召回
  （TopK 默认 5、相似度阈值默认 0.6，均为可配置参数）+ Neo4j `RELATED_TO` 关联增强

分层边界（组E红线）：只**调用**组D三个Tool（MemoryValidator/BaseConfidenceCalc/FinalConfidenceRank），
不复制其公式；不触碰组B/C规则引擎、风控置信度、风险告警/工单/fm_flags/交易阻断、人工上报、
EventBus、ProfileExtract 抽取逻辑；不修改 app/Base。

事实来源优先级：仓库实际可运行代码 > 组A~D已确认报告 > 需求/表设计/Agent设计文档。
关键口径与冲突记录见《组E三层记忆架构开发报告》，此处只写已采用的代码口径。

备案速查（详见组E报告）：
- EB-D-01  memory_units 表设计称"14 字段"实列 13 个 → 本模块按 13 字段补齐，不发明第 14 个（组E延续登记 EB-E-01）
- EB-D-02  MEMORY_TAG_ENUM 完整枚举未确认 → 组D常量仅 4 个，本模块不扩展
- EB-D-03  source→base 映射落点 → 本模块统一维护 SOURCE_TO_BASE（需求 §5.4.1）
- EB-D-04  唯一性生产 provider → 本模块 save_memory_units 从 memory_units 提取 existing_tags；
           无法获得时返回 blocked/cannot_check，绝不假装通过
- EB-E-01  生产 embedding（app.Base ollamaEmbedding）已接线但运行环境未联通验证，召回失败时降级
- EB-E-02  无可用 embedding 时禁止伪造向量：返回 unavailable/degraded，不随机向量、不伪造相似度
- EB-E-03  短期记忆首次创建时间：显式元数据键方案（见类 RedisShortTermStore）
- EB-E-04  customer_id+tag 去重合并的 content/evidence_count/conflict_count/update_time 口径无权威规则
           → 默认返回 merge_required；调用方注入 merge_policy 后才执行合并
- EB-E-05  AgentContext.metadata 无统一 customer_id/agent_type 字段 → 兼容读取顺序（见 MemoryRecallMiddleware）
- EB-E-06  conversation_archive.agent_type 表 ENUM 为 customer_service，API/Agent 侧取值 customer → 由调用方映射
- EB-E-07  Neo4jClient.run 吞掉 Neo4jError 返回 []，图谱不可用与"无关联"无法区分 → 默认存储无法探测，
           注入 fake/其他 client 后才能表达 unavailable
"""
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.WealthButler.Tools.confidenceCalcTool import BaseConfidenceCalc
from app.WealthButler.Tools.confidenceRankTool import FinalConfidenceRank
from app.WealthButler.Tools.memoryValidatorTool import MemoryValidator, SOURCE_WHITELIST

logger = logging.getLogger(__name__)

# ======================================================================
# 常量区（阈值/键名/TTL 单点定义，禁止散落魔法数字）
# ======================================================================

# ---- 短期记忆（Redis 会话层）----
SHORT_TERM_KEY_TEMPLATE = "session:{session_id}:messages"
SHORT_TERM_META_KEY_TEMPLATE = "session:{session_id}:meta"  # 记录首次创建时间（EB-E-03）
SHORT_TERM_SLIDE_SECONDS = 30 * 60      # 滑动窗口：每次写入顺延 30 分钟
SHORT_TERM_MAX_SECONDS = 24 * 60 * 60   # 绝对上限：首条消息起最长 24 小时
SHORT_TERM_DEFAULT_LIMIT = 10
SHORT_TERM_LIMIT_CAP = 50               # limit 上限：禁止无限制读取

# ---- 中期记忆（MySQL 画像 + Redis 缓存）----
PROFILE_CACHE_KEY_TEMPLATE = "profile:{customer_id}"
PROFILE_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 604800 = 7 天

# ---- 长期记忆（Milvus + Neo4j）----
LONG_TERM_DEFAULT_TOP_K = 5
LONG_TERM_DEFAULT_THRESHOLD = 0.6
LONG_TERM_TOP_K_CAP = 100
LONG_TERM_ANN_FIELD = "embedding"
LONG_TERM_RELATION_TYPE = "RELATED_TO"        # 只使用 graphSchema 已定义的关系类型
GRAPH_RELATION_TYPES = ("RELATED_TO",)        # Cypher 关系类型白名单（防注入）
GRAPH_DEFAULT_LIMIT = 10
# 长期记忆候选的场景权重（FinalConfidenceRank 四因子之一）。需求未给权威值，
# 组D登记"四因子权重待最终确认"，本模块取 0.5 中立值并在报告中登记，单点定义。
LONG_TERM_SCENARIO_WEIGHT = 0.5

# ---- 会话归档 ----
ARCHIVE_REASON_ENUM = ("会话结束", "超时", "转人工", "用户主动关闭")  # 表 ENUM 合法值，不新增
ARCHIVE_AGENT_TYPE_ENUM = ("customer_service", "advisor", "analyst", "operator", "risk")
ARCHIVE_SENTIMENT_ENUM = ("positive", "neutral", "negative")

# ---- 时间格式（组A/客服确认④：YYYY-MM-DD HH:MM:SS，MySQL DATETIME 默认格式）----
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# ---- source→base 初始置信度映射（需求 §5.4.1；EB-D-03：组E MemoryService 单点维护）----
SOURCE_TO_BASE: Dict[str, float] = {
    "风评问卷": 0.90,
    "交易行为数据": 0.80,
    "AI从对话中提取": 0.60,
    "用户自述": 0.40,
    "系统默认值": 0.20,
}

# 层级状态取值（对外合同）：ok/empty/degraded/unavailable/error
LAYER_STATUSES = ("ok", "empty", "degraded", "unavailable", "error")


class MemoryStoreUnavailableError(RuntimeError):
    """外部存储能力缺失（未配置/未联通），区别于普通运行异常。

    MemoryService 用它把"能力不可用"与"意外异常"分开表达：
    前者 → 层级状态 unavailable，后者 → 层级状态 error。
    """


class ProfileRowMissingError(RuntimeError):
    """客户画像行不存在。写入 memory_units 需要先有画像行，不得静默建行（组E口径）。"""


# ======================================================================
# 默认存储实现（惰性连接：构造时不连接，首次调用才建立外部连接）
# ======================================================================

def _default_redis_client():
    """惰性获取 Redis 原生连接（redis-py client）。

    优先使用 RedisClient().client 原生 List/KV 操作（开发计划差异6确认可用）；
    原生连接在 Redis 不可达时抛 redis.RedisError，由上层捕获转 degraded，
    不会被 RedisClient.set/get 的吞错包装静默掉。
    """
    from app.Base.Client.redisClient import RedisClient
    return RedisClient().client


def _default_profile_model():
    from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
    return CustomerProfileModel


def _default_archive_model():
    from app.WealthButler.Models.conversationArchiveModel import ConversationArchiveModel
    return ConversationArchiveModel


def _default_embedding_fn(text: str) -> List[float]:
    """生产默认 embedding：仓库已有的本地 Ollama bge-m3 封装（1024 维）。

    惰性导入 + 调用即联网：Ollama 未运行时抛异常，由 MemoryService 捕获
    转 degraded/unavailable（EB-E-01），绝不伪造向量（EB-E-02）。
    """
    from app.Base.Ai.llms.ollamaEmbedding import ollama_embedding
    return ollama_embedding(text)


def _default_neo4j_client():
    from app.Base.Client.neo4jClient import Neo4jClient
    return Neo4jClient()


class RedisShortTermStore:
    """短期记忆 Redis 存储（session:{sid}:messages List + 元数据键）。

    滑动 TTL 方案（EB-E-03，可验证实现）：
    - `session:{sid}:meta` 记录首条消息的 created_at（epoch），与消息键同 TTL；
    - 每次写入：若 elapsed >= 24h 则整段作废重开；否则 TTL = min(30min, 24h - elapsed)；
    - 因此"滑动 30 分钟但不超过 24 小时"成立：活跃会话每次写入顺延 30 分钟，
      但任何时刻消息键的存活时间都不会越过首条消息后 24 小时的绝对上限。
    """

    def __init__(self, redis_factory: Callable, time_fn: Callable = None):
        self._redis_factory = redis_factory
        self._time_fn = time_fn or time.time

    def _client(self):
        return self._redis_factory()

    def _resolve_created_at(self, client, key: str, meta_key: str, now: float) -> float:
        """解析会话首次创建时间锚点。

        元数据键缺失/损坏（历史数据或异常）时退回"视为新会话"口径并重写锚点
        （EB-E-03 备案的兼容路径：宁可从当前时刻重算 24h 上限，不假装知道更早的创建时间）。
        """
        raw_meta = client.get(meta_key)
        if raw_meta is not None:
            try:
                if isinstance(raw_meta, (bytes, bytearray)):
                    raw_meta = raw_meta.decode("utf-8")
                created = float(json.loads(raw_meta).get("created_at", now))
                if created > 0:
                    return created
            except (ValueError, TypeError, AttributeError):
                pass
        return now

    def append(self, session_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """RPUSH 一条 JSON 消息，并按滑动窗口刷新 TTL。"""
        client = self._client()
        key = SHORT_TERM_KEY_TEMPLATE.format(session_id=session_id)
        meta_key = SHORT_TERM_META_KEY_TEMPLATE.format(session_id=session_id)
        now = self._time_fn()
        created = self._resolve_created_at(client, key, meta_key, now)
        elapsed = now - created
        if elapsed >= SHORT_TERM_MAX_SECONDS:
            # 会话已达 24h 绝对上限：整段作废重开（先删后写，避免新旧消息混存）
            client.delete(key)
            client.delete(meta_key)
            created = now
            elapsed = 0.0
        new_ttl = int(min(SHORT_TERM_SLIDE_SECONDS, SHORT_TERM_MAX_SECONDS - elapsed))
        client.rpush(key, json.dumps(message, ensure_ascii=False))
        client.expire(key, new_ttl)
        client.set(meta_key, json.dumps({"created_at": created}), ex=new_ttl)
        return {"appended": True, "ttl_seconds": new_ttl, "created_at": created}

    def read(self, session_id: str, limit: int) -> List[Dict[str, Any]]:
        """LRANGE 最近 limit 条（保持时间顺序）。"""
        client = self._client()
        key = SHORT_TERM_KEY_TEMPLATE.format(session_id=session_id)
        raw = client.lrange(key, -int(limit), -1)
        messages = []
        for item in raw:
            if isinstance(item, (bytes, bytearray)):
                item = item.decode("utf-8")
            messages.append(json.loads(item))
        return messages

    def delete(self, session_id: str) -> bool:
        """删除会话消息键与元数据键（24h 作废重开/测试清理用）。"""
        client = self._client()
        key = SHORT_TERM_KEY_TEMPLATE.format(session_id=session_id)
        meta_key = SHORT_TERM_META_KEY_TEMPLATE.format(session_id=session_id)
        client.delete(key)
        client.delete(meta_key)
        return True


class RedisCacheStore:
    """画像缓存 Redis 存取（profile:{customer_id}，TTL 7 天）。

    注意：RedisClient.set/get 内部吞错（返回 False/None）会让"Redis 故障"与
    "缓存未命中"无法区分（备案 EB-E-08）；本存储走 RedisClient().client 原生
    连接，故障时抛异常，由 MemoryService 记录 degraded 诊断并回源 MySQL。
    """

    def __init__(self, redis_factory: Callable):
        self._redis_factory = redis_factory

    def _client(self):
        return self._redis_factory()

    def get(self, key: str) -> Optional[str]:
        value = self._client().get(key)
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        return value

    def set(self, key: str, value: str, ex: int) -> bool:
        self._client().set(key, value, ex=ex)
        return True

    def delete(self, key: str) -> bool:
        self._client().delete(key)
        return True


class CustomerProfileMemoryStore:
    """中期记忆 MySQL 存取（默认实现，懒加载 CustomerProfileModel）。

    get_units 必须区分三种情况（EB-D-04 红线）：
    - 连接不可用 → 抛 MemoryStoreUnavailableError（上层 blocked/cannot_check，不假装通过唯一性校验）
    - 无画像行 → 返回 ([], None)（合法空，唯一性可按空集合检查）
    - 有画像行 → 返回 (units, row)
    """

    def __init__(self, model_provider: Callable = None):
        self._model_provider = model_provider or _default_profile_model

    def get_units(self, customer_id: int) -> Tuple[List[Dict[str, Any]], Optional[Any]]:
        model_cls = self._model_provider()
        if model_cls.get_db_connection() is None:
            raise MemoryStoreUnavailableError(
                "fin_customer_profile 数据库连接不可用（未注册或不可达），无法读取既有 memory_units"
            )
        row = model_cls.find_by_customer_id(customer_id)
        if row is None:
            return [], None
        units = row.memory_units if isinstance(row.memory_units, list) else []
        if not isinstance(row.memory_units, list) and row.memory_units is not None:
            logger.warning("customer_id=%s 的 memory_units 不是列表，按空处理", customer_id)
        return units, row

    def set_units(self, customer_id: int, units: List[Dict[str, Any]]) -> bool:
        model_cls = self._model_provider()
        if model_cls.get_db_connection() is None:
            raise MemoryStoreUnavailableError(
                "fin_customer_profile 数据库连接不可用（未注册或不可达），无法写回 memory_units"
            )
        row = model_cls.find_by_customer_id(customer_id)
        if row is None:
            raise ProfileRowMissingError(
                f"customer_id={customer_id} 画像行不存在，不能写入 memory_units（不静默建行）"
            )
        if not row.update(memory_units=units):
            raise RuntimeError(f"customer_id={customer_id} 的 memory_units 写回失败")
        return True


class MilvusLongTermStore:
    """长期记忆向量召回存储（默认实现，懒加载 CustomerMemoryCollectionModel）。

    - 查询按 customer_id 过滤（filter_expr 参数化整数，防注入）；
    - TopK/阈值由调用方传入（默认 5/0.6，禁止复制 MemoryV1Service 的 0.5 硬编码）；
    - embedding 提供器未配置 → MemoryStoreUnavailableError（EB-E-01/E-02，不伪造向量）。
    """

    def __init__(self, embedding_fn: Callable = None, model_provider: Callable = None,
                 connection_getter: Callable = None):
        self._embedding_fn = embedding_fn
        self._model_provider = model_provider
        self._connection_getter = connection_getter

    def _model(self):
        if self._model_provider is None:
            from app.WealthButler.Repository.customerMemoryCollectionModel import (
                CustomerMemoryCollectionModel,
            )
            return CustomerMemoryCollectionModel
        return self._model_provider()

    def _connection(self):
        if self._connection_getter is not None:
            return self._connection_getter()
        return self._model().get_connection()

    @staticmethod
    def _customer_filter(connection: Any, collection_name: str, customer_id: int) -> str:
        """兼容旧集合 VARCHAR customer_id 与 v2 INT64，切换期间不伪造类型。"""
        description = connection.describe_collection(collection_name)
        fields = {
            str(field.get("name")): field
            for field in (description.get("fields", []) or [])
        }
        customer_field = fields.get("customer_id")
        if customer_field is None:
            raise MemoryStoreUnavailableError("长期记忆集合缺少 customer_id 字段")
        field_type = str(customer_field.get("type", "")).upper()
        if field_type == "21" or field_type.endswith("VARCHAR"):
            return f'customer_id == "{int(customer_id)}"'
        return f"customer_id == {int(customer_id)}"

    def search(self, customer_id: int, query: str, top_k: int,
               threshold: float) -> List[Dict[str, Any]]:
        if self._embedding_fn is None:
            raise MemoryStoreUnavailableError(
                "长期记忆不可用：未配置 embedding 提供器（EB-E-01/E-02，禁止伪造向量）"
            )
        connection = self._connection()
        if connection is None:
            raise MemoryStoreUnavailableError(
                "长期记忆不可用：Milvus 连接未注册或不可达"
            )
        vector = self._embedding_fn(query)
        if not isinstance(vector, (list, tuple)) or not vector:
            raise MemoryStoreUnavailableError(
                "长期记忆不可用：embedding 返回空/非法向量（EB-E-02，禁止随机向量）"
            )
        collection_name = self._model().get_collection_name()
        results = connection.search(
            collection_name=collection_name,
            data=[list(vector)],
            anns_field=LONG_TERM_ANN_FIELD,
            limit=int(top_k),
            filter=self._customer_filter(connection, collection_name, customer_id),
            search_params={"metric_type": "COSINE", "params": {"nprobe": 10}},
            output_fields=["customer_id", "memory_type", "content", "session_id",
                           "agent_type", "importance", "created_at", "last_accessed_at",
                           "access_count"],
        )
        return self._normalize_hits(results)

    @staticmethod
    def _normalize_hits(results: Any) -> List[Dict[str, Any]]:
        """把 Milvus 返回（Hit 对象或 dict）统一成 dict 列表。

        兼容真实 pymilvus Hit（属性访问）与测试注入的 dict/简单对象。
        """
        if not results:
            return []
        # 真实返回为"每查询一个命中列表"，取第一个查询
        first = results[0] if isinstance(results, (list, tuple)) else results
        hits = []
        for hit in first if isinstance(first, (list, tuple)) else [first]:
            if hit is None:
                continue
            get = (lambda name: getattr(hit, name, None)) if not isinstance(hit, dict) \
                else (lambda name: hit.get(name))
            entity = get("entity")
            if entity is not None:
                get_entity = (lambda name: getattr(entity, name, None)) \
                    if not isinstance(entity, dict) else (lambda name: entity.get(name))
            else:
                get_entity = get
            hits.append({
                "id": get("id"),
                "distance": get("distance"),
                "customer_id": get_entity("customer_id"),
                "memory_type": get_entity("memory_type"),
                "content": get_entity("content"),
                "session_id": get_entity("session_id"),
                "agent_type": get_entity("agent_type"),
                "importance": get_entity("importance"),
                "created_at": get_entity("created_at"),
            })
        return hits


class Neo4jGraphStore:
    """长期记忆关联增强存储（Neo4j RELATED_TO）。

    - 关系类型白名单校验（防 Cypher 注入）；
    - 查询限定 customer 范围 + 关系类型 + LIMIT，不改 graphSchema；
    - 默认走 Neo4jClient.run：其内部吞掉 Neo4jError 返回 []，因此"图谱不可用"
      与"无关联结果"无法区分（EB-E-07 备案，见模块说明）。
    """

    def __init__(self, client_factory: Callable = None):
        self._client_factory = client_factory or _default_neo4j_client

    def related_customers(self, customer_id: int, relation_type: str,
                          limit: int) -> List[Dict[str, Any]]:
        if relation_type not in GRAPH_RELATION_TYPES:
            raise ValueError(f"关系类型只允许 {GRAPH_RELATION_TYPES}，收到: {relation_type!r}")
        client = self._client_factory()
        cypher = (
            "MATCH (c:Customer {customer_id: $customer_id})"
            f"-[r:{relation_type}]-(other:Customer) "
            "RETURN other.customer_id AS related_customer_id, r.relation_type AS relation_type "
            "LIMIT $limit"
        )
        rows = client.run(cypher, {"customer_id": int(customer_id), "limit": int(limit)})
        return [
            {
                "related_customer_id": row.get("related_customer_id"),
                "relation_type": row.get("relation_type"),
            }
            for row in (rows or [])
        ]


class ConversationArchiveStore:
    """会话归档存储（conversation_archive 表，默认实现）。

    幂等责任在 MemoryService.archive_session（先查 find_by_session_id 再建），
    本存储只提供原子化的查询与创建。
    """

    def __init__(self, model_provider: Callable = None):
        self._model_provider = model_provider or _default_archive_model

    def _model_cls(self):
        model_cls = self._model_provider()
        if model_cls.get_db_connection() is None:
            raise MemoryStoreUnavailableError(
                "conversation_archive 数据库连接不可用（未注册或不可达）"
            )
        return model_cls

    def find_by_session_id(self, session_id: str):
        return self._model_cls().find_by_session_id(session_id)

    def create(self, archive_data: Dict[str, Any]) -> int:
        model_cls = self._model_cls()
        instance = model_cls(**archive_data)
        new_id = instance.save()
        if not new_id or new_id < 0:
            raise RuntimeError(f"conversation_archive 写入失败（session_id={archive_data.get('session_id')}）")
        return new_id


# ======================================================================
# 参数校验（服务方法直接调用合同：非法参数抛 ValueError，与组C/D一致）
# ======================================================================

def _validate_customer_id(customer_id) -> None:
    if isinstance(customer_id, bool) or not isinstance(customer_id, int) or customer_id <= 0:
        raise ValueError(f"customer_id 必须是正整数（bool 不被接受），收到: {customer_id!r}")


def _validate_session_id(session_id) -> None:
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id 必须是非空字符串")


def _validate_short_limit(limit) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit 必须是 >=1 的整数（bool 不被接受），收到: {limit!r}")
    if limit > SHORT_TERM_LIMIT_CAP:
        raise ValueError(f"limit 不能超过上限 {SHORT_TERM_LIMIT_CAP}，收到: {limit!r}")
    return limit


def _validate_long_params(top_k, threshold):
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError(f"top_k 必须是 >=1 的整数（bool 不被接受），收到: {top_k!r}")
    if top_k > LONG_TERM_TOP_K_CAP:
        raise ValueError(f"top_k 不能超过上限 {LONG_TERM_TOP_K_CAP}，收到: {top_k!r}")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError(f"threshold 必须是数值（bool 不被接受），收到: {threshold!r}")
    threshold = float(threshold)
    if not (0.0 < threshold <= 1.0):
        raise ValueError(f"threshold 必须在 (0,1] 内，收到: {threshold!r}")
    return top_k, threshold


# ======================================================================
# MemoryService —— 三层记忆业务层
# ======================================================================

class MemoryService:
    """三层记忆业务服务（组E）。

    所有外部依赖（Redis/MySQL/Milvus/Neo4j/归档表）均可注入替换 provider，
    单元测试不依赖真实外部服务；默认 provider 全部惰性连接，导入模块或
    构造实例不会连接任何外部服务。

    对外方法（返回结构均为 JSON 可序列化 dict，层级状态 ∈ LAYER_STATUSES）：
    - recall(...)                   三源召回 + 合并 + 长期候选重排（中间件主入口）
    - get_short_term_memory(...)    短期单层召回
    - get_profile_memory(...)       中期单层召回（含缓存）
    - get_long_term_memory(...)     长期单层召回（Milvus+Neo4j+重排）
    - save_memory_units(...)        写入链路：校验→补齐→置信度→去重/合并→写库→失效缓存
    - append_session_message(...)   短期消息追加（滑动 TTL）
    - archive_session(...)          会话归档（幂等）
    - invalidate_profile_cache(...) 画像缓存主动失效
    """

    def __init__(
        self,
        short_term_store=None,
        cache_store=None,
        profile_store=None,
        vector_store=None,
        graph_store=None,
        archive_store=None,
        validator=None,
        confidence_calc=None,
        ranker=None,
        merge_policy=None,
        now_fn: Callable = None,
    ):
        # 默认 provider 均为惰性工厂：此处不建立任何真实连接
        self.short_term_store = short_term_store or RedisShortTermStore(_default_redis_client)
        self.cache_store = cache_store or RedisCacheStore(_default_redis_client)
        self.profile_store = profile_store or CustomerProfileMemoryStore()
        self.vector_store = vector_store or MilvusLongTermStore(embedding_fn=_default_embedding_fn)
        self.graph_store = graph_store or Neo4jGraphStore()
        self.archive_store = archive_store or ConversationArchiveStore()
        # 组D 三个 Tool 的调用点（只调用，不复制公式）
        self.validator = validator or MemoryValidator
        self.confidence_calc = confidence_calc or BaseConfidenceCalc
        self.ranker = ranker or FinalConfidenceRank
        # customer_id+tag 合并策略：默认 None → merge_required（EB-E-04，不静默发明合并口径）
        self.merge_policy = merge_policy
        self._now_fn = now_fn or datetime.now

    # ------------------------------------------------------------------
    # 召回主入口
    # ------------------------------------------------------------------

    def recall(self, customer_id, query, session_id=None, agent_type=None,
               short_term_limit: int = SHORT_TERM_DEFAULT_LIMIT,
               long_term_top_k: int = LONG_TERM_DEFAULT_TOP_K,
               long_term_threshold: float = LONG_TERM_DEFAULT_THRESHOLD,
               use_profile_cache: bool = True) -> Dict[str, Any]:
        """三源召回 + 合并 + 长期重排（MemoryRecallMiddleware 主入口）。

        单层不可用不阻断整体：其他层结果保留，整体状态降为 degraded 并携带错误信息。
        customer_id/session_id/query 缺失时对应层返回 unavailable（结构化状态，不抛异常）。
        同一输入、同一底层数据下两次调用结果一致（无跨请求状态，稳定排序）。
        """
        short_layer = self._recall_short_term(session_id, short_term_limit)
        mid_layer = self._recall_mid_term(customer_id, use_cache=use_profile_cache)
        long_layer = self._recall_long_term(customer_id, query, long_term_top_k,
                                            long_term_threshold)
        layers = [short_layer, mid_layer, long_layer]
        errors: List[str] = []
        for layer in layers:
            errors.extend(layer.get("errors", []))
        merged = self._merge_layers(short_layer, mid_layer, long_layer)
        return {
            "status": _aggregate_status(layers),
            "customer_id": customer_id,
            "query": query,
            "session_id": session_id,
            "agent_type": agent_type,
            "short_term": short_layer,
            "mid_term": mid_layer,
            "long_term": long_layer,
            "merged": merged,
            "ranked": long_layer.get("ranked", []),
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # 短期记忆
    # ------------------------------------------------------------------

    def get_short_term_memory(self, session_id: str,
                              limit: int = SHORT_TERM_DEFAULT_LIMIT) -> Dict[str, Any]:
        """短期单层召回（直接调用合同：非法参数抛 ValueError）。"""
        _validate_session_id(session_id)
        _validate_short_limit(limit)
        return self._recall_short_term(session_id, limit)

    def _recall_short_term(self, session_id, limit) -> Dict[str, Any]:
        if not isinstance(session_id, str) or not session_id.strip():
            return _layer("unavailable", messages=[],
                          errors=["短期记忆不可用：缺少 session_id"])
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > SHORT_TERM_LIMIT_CAP:
            return _layer("unavailable", messages=[],
                          errors=[f"短期记忆 limit 非法（1~{SHORT_TERM_LIMIT_CAP}）: {limit!r}"])
        try:
            messages = self.short_term_store.read(session_id, limit)
        except Exception as exc:
            return _layer("degraded", errors=[f"短期记忆读取失败（Redis 异常）: {exc}"])
        return _layer("ok" if messages else "empty", messages=messages)

    def append_session_message(self, session_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """追加一条消息到短期记忆（Redis 错误 → degraded，不抛异常阻断 Agent）。

        message 至少包含 role/content；timestamp 缺省时按服务时间补
        （YYYY-MM-DD HH:MM:SS，组A/客服确认④），request_id/session_id 等扩展键原样保留。
        """
        _validate_session_id(session_id)
        if not isinstance(message, dict):
            raise ValueError(f"message 必须是 dict，收到: {type(message)!r}")
        normalized = dict(message)
        role = normalized.get("role")
        if not isinstance(role, str) or not role.strip():
            raise ValueError("message 必须包含非空 role 字符串")
        content = normalized.get("content")
        if not isinstance(content, str):
            raise ValueError("message 必须包含 content 字符串")
        normalized.setdefault("timestamp", self._now_fn().strftime(TIME_FORMAT))
        try:
            meta = self.short_term_store.append(session_id, normalized)
        except Exception as exc:
            return _layer("degraded", action="not_appended", session_id=session_id,
                          errors=[f"短期记忆写入失败（Redis 异常）: {exc}"])
        return _layer("ok", action="appended", session_id=session_id,
                      ttl_seconds=meta.get("ttl_seconds"))

    # ------------------------------------------------------------------
    # 中期记忆（画像 + 缓存）
    # ------------------------------------------------------------------

    def get_profile_memory(self, customer_id: int, use_cache: bool = True) -> Dict[str, Any]:
        """中期单层召回（直接调用合同：非法 customer_id 抛 ValueError）。"""
        _validate_customer_id(customer_id)
        return self._recall_mid_term(customer_id, use_cache=use_cache)

    def _recall_mid_term(self, customer_id, use_cache: bool) -> Dict[str, Any]:
        if isinstance(customer_id, bool) or not isinstance(customer_id, int) or customer_id <= 0:
            return _layer("unavailable", units=[], cache_hit=False,
                          errors=["中期记忆不可用：缺少合法 customer_id"])
        errors: List[str] = []
        cache_hit = False
        units: Optional[List[Dict[str, Any]]] = None
        key = PROFILE_CACHE_KEY_TEMPLATE.format(customer_id=customer_id)
        if use_cache:
            try:
                raw = self.cache_store.get(key)
            except Exception as exc:
                errors.append(f"画像缓存读取失败（回源 MySQL）: {exc}")
            else:
                if raw is not None:
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, list):
                            units, cache_hit = parsed, True
                        else:
                            errors.append("画像缓存内容不是列表，忽略缓存并回源")
                    except (ValueError, TypeError):
                        errors.append("画像缓存 JSON 损坏，忽略缓存并回源")
        if units is None:
            try:
                units, _row = self.profile_store.get_units(customer_id)
            except MemoryStoreUnavailableError as exc:
                return _layer("unavailable", units=[], cache_hit=False,
                              errors=[f"中期记忆不可用：{exc}"] + errors)
            except Exception as exc:
                return _layer("error", units=[], cache_hit=False,
                              errors=[f"中期记忆读取异常：{exc}"] + errors)
            if use_cache:
                try:
                    self.cache_store.set(key, json.dumps(units, ensure_ascii=False),
                                         ex=PROFILE_CACHE_TTL_SECONDS)
                except Exception as exc:
                    errors.append(f"画像缓存回填失败: {exc}")
        status = "empty"
        if units:
            status = "degraded" if errors else "ok"
        return _layer(status, units=units or [], cache_hit=cache_hit, errors=errors)

    def invalidate_profile_cache(self, customer_id: int) -> Dict[str, Any]:
        """画像缓存主动失效（写库后调用；Redis 异常 → degraded）。"""
        _validate_customer_id(customer_id)
        key = PROFILE_CACHE_KEY_TEMPLATE.format(customer_id=customer_id)
        try:
            self.cache_store.delete(key)
        except Exception as exc:
            return _layer("degraded", action="not_invalidated",
                          errors=[f"画像缓存失效失败: {exc}"])
        return _layer("ok", action="invalidated")

    # ------------------------------------------------------------------
    # 长期记忆（Milvus + Neo4j）
    # ------------------------------------------------------------------

    def get_long_term_memory(self, customer_id: int, query: str,
                             top_k: int = LONG_TERM_DEFAULT_TOP_K,
                             threshold: float = LONG_TERM_DEFAULT_THRESHOLD) -> Dict[str, Any]:
        """长期单层召回（直接调用合同：非法参数抛 ValueError）。"""
        _validate_customer_id(customer_id)
        top_k, threshold = _validate_long_params(top_k, threshold)
        return self._recall_long_term(customer_id, query, top_k, threshold)

    def _recall_long_term(self, customer_id, query, top_k, threshold) -> Dict[str, Any]:
        if isinstance(customer_id, bool) or not isinstance(customer_id, int) or customer_id <= 0:
            return _layer("unavailable", items=[], graph=[], ranked=[],
                          errors=["长期记忆不可用：缺少合法 customer_id"])
        if not isinstance(query, str) or not query.strip():
            return _layer("unavailable", items=[], graph=[], ranked=[],
                          errors=["长期记忆不可用：缺少 query"])
        try:
            top_k, threshold = _validate_long_params(top_k, threshold)
        except ValueError as exc:
            return _layer("unavailable", items=[], graph=[], ranked=[],
                          errors=[f"长期记忆参数非法: {exc}"])
        errors: List[str] = []
        # ---- Milvus 向量召回（失败不掩盖 Neo4j 结果，反之亦然）----
        items: List[Dict[str, Any]] = []
        items_status = "empty"
        try:
            hits = self.vector_store.search(customer_id, query, top_k, threshold)
        except MemoryStoreUnavailableError as exc:
            items_status = "unavailable"
            errors.append(f"长期记忆（Milvus）不可用：{exc}")
        except Exception as exc:
            items_status = "error"
            errors.append(f"长期记忆（Milvus）召回异常：{exc}")
        else:
            items = self._build_long_items(hits, threshold)
            items_status = "ok" if items else "empty"
        # ---- Neo4j 关联增强（RELATED_TO，限定 customer 范围/关系类型/数量）----
        graph: List[Dict[str, Any]] = []
        graph_status = "empty"
        try:
            rows = self.graph_store.related_customers(customer_id, LONG_TERM_RELATION_TYPE,
                                                      GRAPH_DEFAULT_LIMIT)
        except MemoryStoreUnavailableError as exc:
            graph_status = "unavailable"
            errors.append(f"长期记忆（Neo4j）不可用：{exc}")
        except Exception as exc:
            graph_status = "error"
            errors.append(f"长期记忆（Neo4j）关联增强异常：{exc}")
        else:
            graph = [
                {"related_customer_id": row.get("related_customer_id"),
                 "relation_type": row.get("relation_type"), "source_layer": "graph"}
                for row in rows
            ]
            graph_status = "ok" if graph else "empty"
        # ---- 组D FinalConfidenceRank 重排（final_score 不回写 confidence）----
        ranked: List[Dict[str, Any]] = []
        rank_failed = False
        if items:
            try:
                ranked = self.ranker.rank(self._build_rank_candidates(items))
            except Exception as exc:
                rank_failed = True
                errors.append(f"长期记忆候选重排失败（FinalConfidenceRank）: {exc}")
        layer_status = _combine_sub_status(items_status, graph_status)
        if rank_failed and layer_status == "ok":
            layer_status = "degraded"
        return _layer(
            layer_status,
            items=items, graph=graph, ranked=ranked,
            top_k=top_k, threshold=threshold, errors=errors,
        )

    def _build_long_items(self, hits: List[Dict[str, Any]],
                          threshold: float) -> List[Dict[str, Any]]:
        """按相似度阈值过滤并归一化长期记忆条目。

        COSINE 相似度即 Milvus 返回的 distance（MemoryV1Service 的 distance>0.5
        硬编码不复制，阈值来自参数，默认 0.6）。
        """
        items = []
        for hit in hits:
            raw_distance = hit.get("distance")
            if raw_distance is None:
                continue
            try:
                similarity = max(0.0, min(1.0, float(raw_distance)))
            except (TypeError, ValueError):
                continue
            if similarity < threshold:
                continue
            items.append({
                "id": hit.get("id"),
                "content": hit.get("content"),
                "memory_type": hit.get("memory_type"),
                "session_id": hit.get("session_id"),
                "agent_type": hit.get("agent_type"),
                "importance": hit.get("importance"),
                "created_at": hit.get("created_at"),
                "similarity": round(similarity, 4),
                "source_layer": "long_term",
            })
        return items

    def _build_rank_candidates(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """把长期记忆条目转换为 FinalConfidenceRank 候选。

        semantic_score=相似度；confidence=importance（该字段即模型定义的重要性评分，
        不用 final_score 回写）；age_days 由 created_at（epoch 秒）推导；
        scenario_weight=0.5（无权威值，模块常量，见头部说明）。
        """
        now_ts = self._now_fn().timestamp()
        candidates = []
        for item in items:
            importance = item.get("importance")
            confidence = float(importance) if isinstance(importance, (int, float)) \
                and not isinstance(importance, bool) else 0.5
            created_at = item.get("created_at")
            if isinstance(created_at, (int, float)) and not isinstance(created_at, bool) \
                    and created_at > 0:
                age_days = int((now_ts - float(created_at)) // 86400)
            else:
                age_days = 0
            candidates.append({
                "content": item.get("content") or "",
                "semantic_score": float(item.get("similarity", 0.0)),
                "confidence": confidence,
                "age_days": max(0, age_days),
                "scenario_weight": LONG_TERM_SCENARIO_WEIGHT,
            })
        return candidates

    # ------------------------------------------------------------------
    # 三源合并
    # ------------------------------------------------------------------

    def _merge_layers(self, short_layer, mid_layer, long_layer) -> List[Dict[str, Any]]:
        """三源合并（参考 MemoryV1Service 多源合并模式，但不照搬其字段/阈值）。

        规则：
        - 保留来源标记 source_layer（short_term/mid_term/long_term），保证可追溯；
        - 对明确唯一标识的记录去重：中期按 unit_id、长期按 Milvus id；短期消息无
          唯一标识不去重；**不得**以 content 文本去重替代业务键；
        - 顺序稳定：短期（时间序）→ 中期（画像序）→ 长期（向量序），同一输入两次
          调用结果一致；不使用模块级可变状态。
        """
        merged: List[Dict[str, Any]] = []
        seen_mid: set = set()
        seen_long: set = set()
        for message in short_layer.get("messages", []):
            item = dict(message)
            item["source_layer"] = "short_term"
            merged.append(item)
        for unit in mid_layer.get("units", []):
            unit_id = unit.get("unit_id")
            if unit_id is not None:
                if unit_id in seen_mid:
                    continue
                seen_mid.add(unit_id)
            item = dict(unit)
            item["source_layer"] = "mid_term"
            merged.append(item)
        for long_item in long_layer.get("items", []):
            item_id = long_item.get("id")
            if item_id is not None:
                if item_id in seen_long:
                    continue
                seen_long.add(item_id)
            item = dict(long_item)
            item["source_layer"] = "long_term"
            merged.append(item)
        return merged

    # ------------------------------------------------------------------
    # 写入链路：ProfileExtract 六业务字段 → MemoryValidator → 补齐 → 置信度 → 写库
    # ------------------------------------------------------------------

    def save_memory_units(self, customer_id: int, extracted_units) -> Dict[str, Any]:
        """中期记忆写入链路（组A第13节客服确认②③⑤ + 组D 处置矩阵）。

        流程：读取既有 memory_units（唯一性前置，EB-D-04）→ 逐条
        MemoryValidator.validate → accept/demote 补齐 8 个技术字段并写库 →
        reject 不写（时间/必填/数值/内容非法）→ customer_id+tag 重复走去重/合并
        （无 merge_policy 时 merge_required，EB-E-04）→ 写回
        fin_customer_profile.memory_units → 失效画像缓存。

        BaseConfidenceCalc 的调用位置：①调用方未给 confidence 且 source 在
        SOURCE_TO_BASE 内时，以 base=映射值、counts=0、age=0 计算初始置信度；
        ②调用方给了 confidence 时，计算 source→base 参考值（base_confidence_ref）
        用于"确认初始置信度"，不回写覆盖调用方/校验后的值。
        """
        _validate_customer_id(customer_id)
        if not isinstance(extracted_units, (list, tuple)) or not extracted_units:
            raise ValueError("extracted_units 必须是非空列表（ProfileExtract 输出）")
        for index, unit in enumerate(extracted_units):
            if not isinstance(unit, dict):
                raise ValueError(f"extracted_units[{index}] 必须是 dict，收到: {type(unit)!r}")

        # ---- 1. 读取既有 units：唯一性校验前置（EB-D-04：拿不到就阻断，不假装通过）----
        try:
            existing_units, _row = self.profile_store.get_units(customer_id)
        except MemoryStoreUnavailableError as exc:
            return {
                "status": "blocked", "action": "cannot_check", "customer_id": customer_id,
                "results": [], "written_count": 0, "demoted_count": 0,
                "rejected_count": 0, "merge_required_count": 0, "blocked_count": len(extracted_units),
                "errors": [f"无法获得既有 memory_units，唯一性校验阻断（EB-D-04）: {exc}"],
            }
        except Exception as exc:
            return {
                "status": "error", "action": "not_written", "customer_id": customer_id,
                "results": [], "written_count": 0, "demoted_count": 0,
                "rejected_count": 0, "merge_required_count": 0, "blocked_count": 0,
                "errors": [f"读取既有 memory_units 异常: {exc}"],
            }
        existing_tags = [u.get("tag") for u in existing_units
                         if isinstance(u, dict) and u.get("tag") is not None]

        now = self._now_fn()
        now_str = now.strftime(TIME_FORMAT)
        written_units: List[Dict[str, Any]] = list(existing_units)
        results: List[Dict[str, Any]] = []
        errors: List[str] = []
        written = demoted = rejected = merge_required = blocked = 0

        for unit in extracted_units:
            prepared = dict(unit)
            confidence_origin = "caller"
            # confidence 缺失且 source 可映射时，用 BaseConfidenceCalc 计算初始置信度
            if prepared.get("confidence") is None:
                base = SOURCE_TO_BASE.get(prepared.get("source"))
                if base is not None:
                    try:
                        prepared["confidence"] = self.confidence_calc.calculate(
                            base, 0, 0, 0)
                        confidence_origin = "source_base_calc"
                    except ValueError:
                        pass  # 映射值恒合法，理论不可达；保持防御
            tag = prepared.get("tag")

            # ---- 2. 同 customer_id+tag 去重/合并（不同客户同名 tag 不受影响）----
            if tag is not None and tag in existing_tags:
                if self.merge_policy is None:
                    merge_required += 1
                    results.append({
                        "tag": tag, "action": "merge_required", "valid": False,
                        "violations": [
                            f"customer_id={customer_id} 已存在 tag '{tag}'，"
                            "需进入去重/合并流程（EB-E-04：合并口径未确认，未提供 merge_policy）"
                        ],
                    })
                    continue
                try:
                    old_unit = next(u for u in written_units
                                    if isinstance(u, dict) and u.get("tag") == tag)
                    merged_unit = self.merge_policy(
                        existing_unit=dict(old_unit), incoming_unit=dict(prepared),
                        customer_id=customer_id)
                except Exception as exc:
                    results.append({"tag": tag, "action": "merge_failed", "valid": False,
                                    "violations": [f"merge_policy 执行失败: {exc}"]})
                    errors.append(f"tag '{tag}' 合并失败: {exc}")
                    continue
                if not isinstance(merged_unit, dict):
                    results.append({"tag": tag, "action": "merge_failed", "valid": False,
                                    "violations": ["merge_policy 必须返回 dict"]})
                    errors.append(f"tag '{tag}' 合并失败：merge_policy 返回 {type(merged_unit)!r}")
                    continue
                index = written_units.index(old_unit)
                written_units[index] = merged_unit
                written += 1
                results.append({"tag": tag, "action": "merged", "valid": True,
                                "violations": [], "unit_id": merged_unit.get("unit_id")})
                continue

            # ---- 3. 组D 六维校验（只调用，不复制逻辑）----
            validation = self.validator.validate(customer_id, prepared,
                                                 existing_tags=existing_tags, now=now)
            action = validation["action"]
            violations = validation["violations"]

            if action in ("accept", "demote"):
                final_unit = self._fill_technical_fields(
                    validation["normalized_memory_unit"], action,
                    validation.get("adjusted_confidence"), now_str)
                # ---- 4. BaseConfidenceCalc 确认初始置信度（source→base 单点映射）----
                source = final_unit.get("source")
                base_ref = None
                if source in SOURCE_TO_BASE:
                    try:
                        base_ref = self.confidence_calc.calculate(SOURCE_TO_BASE[source], 0, 0, 0)
                    except ValueError:
                        base_ref = None
                written_units.append(final_unit)
                if final_unit.get("tag") is not None:
                    existing_tags.append(final_unit["tag"])
                written += 1
                if action == "demote":
                    demoted += 1
                results.append({
                    "tag": final_unit.get("tag"), "action": action,
                    "valid": validation["valid"], "violations": violations,
                    "unit_id": final_unit.get("unit_id"),
                    "confidence": final_unit.get("confidence"),
                    "base_confidence_ref": base_ref,
                    "confidence_origin": confidence_origin,
                })
            elif action == "reject":
                rejected += 1
                results.append({"tag": tag, "action": "reject", "valid": False,
                                "violations": violations})
            else:  # cannot_check（本链路已在读取前置阻断，理论兜底）
                blocked += 1
                results.append({"tag": tag, "action": "cannot_check", "valid": False,
                                "violations": violations})

        # ---- 5. 写回 + 缓存失效 ----
        if written == 0:
            return {
                "status": "merge_required" if merge_required else
                          ("blocked" if blocked else "rejected"),
                "action": "not_written", "customer_id": customer_id,
                "results": results, "written_count": 0, "demoted_count": 0,
                "rejected_count": rejected, "merge_required_count": merge_required,
                "blocked_count": blocked, "errors": errors,
            }
        try:
            self.profile_store.set_units(customer_id, written_units)
        except MemoryStoreUnavailableError as exc:
            return {
                "status": "error", "action": "not_written", "customer_id": customer_id,
                "results": results, "written_count": 0, "demoted_count": 0,
                "rejected_count": rejected, "merge_required_count": merge_required,
                "blocked_count": blocked,
                "errors": errors + [f"写回 memory_units 失败：{exc}"],
            }
        except ProfileRowMissingError as exc:
            return {
                "status": "error", "action": "not_written", "customer_id": customer_id,
                "results": results, "written_count": 0, "demoted_count": 0,
                "rejected_count": rejected, "merge_required_count": merge_required,
                "blocked_count": blocked,
                "errors": errors + [f"写回 memory_units 失败：{exc}"],
            }
        except Exception as exc:
            return {
                "status": "error", "action": "not_written", "customer_id": customer_id,
                "results": results, "written_count": 0, "demoted_count": 0,
                "rejected_count": rejected, "merge_required_count": merge_required,
                "blocked_count": blocked,
                "errors": errors + [f"写回 memory_units 异常：{exc}"],
            }
        try:
            self.cache_store.delete(PROFILE_CACHE_KEY_TEMPLATE.format(customer_id=customer_id))
        except Exception as exc:
            errors.append(f"写后画像缓存失效失败（缓存可能陈旧）: {exc}")
        status = "blocked" if blocked else (
            "merge_required" if merge_required else (
                "degraded" if errors else "ok"))
        return {
            "status": status, "action": "written", "customer_id": customer_id,
            "results": results, "written_count": written, "demoted_count": demoted,
            "rejected_count": rejected, "merge_required_count": merge_required,
            "blocked_count": blocked, "errors": errors,
        }

    def _fill_technical_fields(self, normalized: Dict[str, Any], action: str,
                               adjusted_confidence, now_str: str) -> Dict[str, Any]:
        """写入方补齐 8 个技术字段（组A第13节客服确认②，13 字段口径 EB-D-01）。

        - unit_id：UUID（除非调用方已提供）；
        - evidence/conflict/recall_count：默认 0（调用方已提供且通过校验则保留）；
        - create_time/update_time：当前统一时间；valid_until：默认 None；
        - status：active；MemoryValidator 降级时为 demoted；
        - confidence：校验后值（accept=原值，demote=×0.8，来自组D adjusted_confidence）。
        """
        unit = dict(normalized)
        unit.setdefault("unit_id", str(uuid.uuid4()))
        unit.setdefault("evidence_count", 0)
        unit.setdefault("conflict_count", 0)
        unit.setdefault("recall_count", 0)
        unit.setdefault("create_time", now_str)
        unit.setdefault("update_time", now_str)
        unit.setdefault("valid_until", None)
        if action == "demote":
            unit["status"] = "demoted"
        else:
            unit.setdefault("status", "active")
        if adjusted_confidence is not None:
            unit["confidence"] = adjusted_confidence
        return unit

    # ------------------------------------------------------------------
    # 会话归档
    # ------------------------------------------------------------------

    def archive_session(self, session_id: str, customer_id: int, agent_type: str,
                        messages, archive_reason: str,
                        summary: Optional[str] = None,
                        sentiment: Optional[str] = None,
                        resolved: bool = False,
                        transferred_to_human: bool = False,
                        start_time=None, end_time=None) -> Dict[str, Any]:
        """会话归档（conversation_archive 表，字段与模型逐一核对）。

        - archive_reason 仅允许表 ENUM 四值；agent_type 仅允许表 ENUM 五值
          （API 侧取值 customer 需调用方映射为 customer_service，EB-E-06）；
        - message_count 恒等于 len(messages)；start_time/end_time 由消息 timestamp
          推导（缺时间戳且未显式提供 → ValueError，不静默补时间，EB-E-07 相关口径）；
        - 幂等：同 session 已归档 → already_archived，不重复建行；
        - 触发时机不属于本方法（现有业务无明确"何时归档"合同）：由调用方显式调用
          archive_session 完成（备案 EB-E-09），process_response 不无条件建归档。
        """
        _validate_session_id(session_id)
        _validate_customer_id(customer_id)
        if not isinstance(agent_type, str) or agent_type not in ARCHIVE_AGENT_TYPE_ENUM:
            raise ValueError(
                f"agent_type 必须是 {ARCHIVE_AGENT_TYPE_ENUM} 之一（表 ENUM；"
                f"API 值 customer 需映射为 customer_service，EB-E-06），收到: {agent_type!r}"
            )
        if archive_reason not in ARCHIVE_REASON_ENUM:
            raise ValueError(f"archive_reason 只允许 {ARCHIVE_REASON_ENUM}，收到: {archive_reason!r}")
        if not isinstance(messages, (list, tuple)) or not messages:
            raise ValueError("messages 必须是非空消息列表（归档要求消息完整保存）")
        if sentiment is not None and sentiment not in ARCHIVE_SENTIMENT_ENUM:
            raise ValueError(f"sentiment 只允许 {ARCHIVE_SENTIMENT_ENUM}，收到: {sentiment!r}")

        resolved_start = _coerce_datetime(start_time) if start_time is not None else None
        resolved_end = _coerce_datetime(end_time) if end_time is not None else None
        if resolved_start is None or resolved_end is None:
            derived_start, derived_end = _derive_time_range(messages)
            resolved_start = resolved_start or derived_start
            resolved_end = resolved_end or derived_end
        if resolved_start > resolved_end:
            raise ValueError(
                f"start_time 不能晚于 end_time: {resolved_start!r} > {resolved_end!r}"
            )

        # 幂等：同 session 重复归档不新建行
        try:
            existing = self.archive_store.find_by_session_id(session_id)
        except MemoryStoreUnavailableError as exc:
            return _layer("unavailable", action="not_archived", session_id=session_id,
                          errors=[f"归档幂等检查不可用：{exc}"])
        except Exception as exc:
            return _layer("error", action="not_archived", session_id=session_id,
                          errors=[f"归档幂等检查异常：{exc}"])
        if existing is not None:
            return _layer("ok", action="already_archived", session_id=session_id,
                          archived_id=getattr(existing, "id", None))

        archive_data = {
            "session_id": session_id,
            "customer_id": customer_id,
            "agent_type": agent_type,
            "message_count": len(messages),
            "messages": list(messages),
            "summary": summary,
            "sentiment": sentiment,
            "resolved": bool(resolved),
            "transferred_to_human": bool(transferred_to_human),
            "archive_reason": archive_reason,
            "start_time": resolved_start,
            "end_time": resolved_end,
        }
        try:
            new_id = self.archive_store.create(archive_data)
        except MemoryStoreUnavailableError as exc:
            return _layer("unavailable", action="not_archived", session_id=session_id,
                          errors=[f"归档写入不可用：{exc}"])
        except Exception as exc:
            return _layer("error", action="not_archived", session_id=session_id,
                          errors=[f"归档写入异常：{exc}"])
        return _layer("ok", action="archived", session_id=session_id, archived_id=new_id,
                      message_count=len(messages))


# ======================================================================
# 内部辅助
# ======================================================================

def _layer(status: str, errors: List[str] = None, **payload) -> Dict[str, Any]:
    """统一层级结果结构：{status, errors, ...payload}（JSON 可序列化）。"""
    result: Dict[str, Any] = {"status": status, "errors": list(errors or [])}
    result.update(payload)
    return result


def _aggregate_status(layers) -> str:
    """整体状态聚合：单层不可用/异常不阻断整体，降为 degraded 并保留可用层结果。"""
    statuses = [layer.get("status") for layer in layers]
    if all(status == "unavailable" for status in statuses):
        return "unavailable"
    if all(status == "error" for status in statuses):
        return "error"
    if any(status in ("degraded", "unavailable", "error") for status in statuses):
        return "degraded"
    if any(status == "ok" for status in statuses):
        return "ok"
    return "empty"


def _combine_sub_status(items_status: str, graph_status: str) -> str:
    """长期记忆两个子源（Milvus/Neo4j）的状态合并。

    "empty"（无数据，正常情况）不降级也不提级：一侧 empty 时保留另一侧状态；
    只有 unavailable/error/degraded 与 ok 混存时才降级。
    """
    if items_status == "ok" and graph_status == "ok":
        return "ok"
    if items_status == "ok" or graph_status == "ok":
        other = graph_status if items_status == "ok" else items_status
        if other in ("degraded", "unavailable", "error"):
            return "degraded"
        return "ok"
    if "empty" in (items_status, graph_status):
        other = graph_status if items_status == "empty" else items_status
        return other  # empty 一侧不改变另一侧（unavailable/error/degraded 原样保留）
    if items_status == "unavailable" and graph_status == "unavailable":
        return "unavailable"
    if items_status == "error" and graph_status == "error":
        return "error"
    return "degraded"  # 其余组合：unavailable/error/degraded 两两混合


def _coerce_datetime(value) -> datetime:
    """时间输入统一为 datetime：接受 datetime 或 YYYY-MM-DD HH:MM:SS 字符串。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, TIME_FORMAT)
        except ValueError as exc:
            raise ValueError(
                f"时间必须是 {TIME_FORMAT} 格式字符串或 datetime，收到: {value!r}"
            ) from exc
    raise ValueError(f"时间必须是 {TIME_FORMAT} 格式字符串或 datetime，收到: {value!r}")


def _derive_time_range(messages) -> Tuple[datetime, datetime]:
    """从消息 timestamp 推导归档时间范围（全部缺失且未显式提供 → 拒绝，不静默补）。"""
    stamps: List[datetime] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("messages 每项必须是 dict")
        ts = message.get("timestamp")
        if ts is None:
            continue
        stamps.append(_coerce_datetime(ts))
    if not stamps:
        raise ValueError(
            "messages 缺少 timestamp 且未提供 start_time/end_time，无法推导归档时间范围"
        )
    return min(stamps), max(stamps)


__all__ = [
    "MemoryService",
    "RedisShortTermStore", "RedisCacheStore", "CustomerProfileMemoryStore",
    "MilvusLongTermStore", "Neo4jGraphStore", "ConversationArchiveStore",
    "MemoryStoreUnavailableError", "ProfileRowMissingError",
    "SOURCE_TO_BASE", "SOURCE_WHITELIST",
    "SHORT_TERM_DEFAULT_LIMIT", "SHORT_TERM_LIMIT_CAP",
    "SHORT_TERM_SLIDE_SECONDS", "SHORT_TERM_MAX_SECONDS",
    "PROFILE_CACHE_TTL_SECONDS",
    "LONG_TERM_DEFAULT_TOP_K", "LONG_TERM_DEFAULT_THRESHOLD",
    "ARCHIVE_REASON_ENUM", "ARCHIVE_AGENT_TYPE_ENUM", "TIME_FORMAT", "LAYER_STATUSES",
]
