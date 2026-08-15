# EventBus 问题修复方案

**文档编号**: TECH-FIX-002  
**创建时间**: 2026-08-15  
**负责人**: 李清华  
**反馈来源**: 聂柏（风控Agent负责人）  
**状态**: 待审批

---

## 一、问题汇总

### 1.1 Bug 清单

| Bug ID | 位置 | 严重程度 | 描述 |
|--------|------|----------|------|
| BUG-1 | eventBus.py:178 | 🔴 高 | bytes键解析失败，redisClient开启decode_responses导致返回str键 |
| BUG-2 | eventBus.py:145 | 🔴 高 | PEL从未重放，消费者重启丢失未ACK消息 |
| BUG-3 | eventBus.py:191-200 | 🟡 中 | 条件ACK与需求文档§2.4冲突（要求无条件ACK+幂等检查）|

### 1.2 Schema冲突

三处payload定义不一致：

| 来源 | customer_id | transaction_id | amount类型 | transaction_type | 其他字段 |
|------|-------------|----------------|------------|------------------|----------|
| **schemas.py** | ✅ int | tx_id | float | "purchase\|redeem" | product_id, timestamp |
| **examples** | ✅ int | transaction_id | float | "buy" | customer_name, product_name |
| **Group A冻结合约** | ✅ int | transaction_id | **string** | 中文 | product_id可选 |

### 1.3 待决策架构问题

1. **是否添加 `source_agent` 字段**？时间戳格式用毫秒字符串还是ISO8601？
2. **`publish()` 最终签名**确定？
3. **ACK/幂等策略**：条件ACK（当前实现）vs 无条件ACK+幂等检查（需求文档）？
4. **Payload统一方案**：强制Group A合约 vs 逐步迁移 vs 多版本兼容？

---

## 二、Bug根因分析与修复方案

### 2.1 BUG-1: bytes键解析失败

**根因**：
```python
# app/WealthButler/middleware/redisClient.py (推测)
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True  # ← 开启自动解码，xreadgroup返回str键
)

# eventBus.py:178
fields.get(b'event_type', b'')  # ← 永远取不到，因为实际键是 'event_type' (str)
```

**影响**：所有事件的 `event_type` 和 `payload` 都解析为空字符串，handler收到空payload。

**修复方案**：
```python
# eventBus.py:178-181 修改前
event_type = fields.get(b'event_type', b'').decode('utf-8')
payload_str = fields.get(b'payload', b'{}').decode('utf-8')
trace_id = fields.get(b'trace_id', b'').decode('utf-8')
timestamp = fields.get(b'timestamp', b'').decode('utf-8')

# 修改后
event_type = fields.get('event_type', '')
payload_str = fields.get('payload', '{}')
trace_id = fields.get('trace_id', '')
timestamp = fields.get('timestamp', '')
```

---

### 2.2 BUG-2: PEL从未重放

**根因**：
- Line 145: `{stream_key: '>'}` 只读取新消息
- Line 129 docstring声称"消费者重启后会自动重放Pending List"，但代码未实现

**Redis Streams PEL机制**：
```
id='0'  → 重放该消费者的所有Pending消息（未ACK）
id='>'  → 只读取Stream中的新消息
```

**当前后果**：
消费者进程重启时，所有未ACK消息永久丢失（违反at-least-once保证）。

**修复方案**：
```python
def consume(stream_key: str, consumer_group: str, consumer_name: str, 
            handler, block_ms: int = 0, count: int = 10):
    """消费事件流
    
    首次启动时：
    1. 先以 id='0' 重放该消费者的 Pending List
    2. 处理完PEL后，切换到 id='>' 读取新消息
    """
    redis_client = get_redis_client()
    
    # ═══════════════════════════════════════════════════════════
    # 步骤1: 重放 Pending List（重启恢复）
    # ═══════════════════════════════════════════════════════════
    logger.info(f"[EventBus] 检查 Pending List: {stream_key}:{consumer_group}:{consumer_name}")
    
    while True:
        # 读取pending消息
        pending_messages = redis_client.client.xreadgroup(
            groupname=consumer_group,
            consumername=consumer_name,
            streams={stream_key: '0'},  # ← id='0' 重放PEL
            count=count,
            block=0  # 非阻塞，立即返回
        )
        
        if not pending_messages or not pending_messages[0][1]:
            logger.info(f"[EventBus] Pending List 已清空，切换到新消息模式")
            break
        
        # 处理pending消息
        for stream, messages in pending_messages:
            for msg_id, fields in messages:
                logger.warning(f"[EventBus] 重放PEL消息: {msg_id}")
                _process_message(stream_key, consumer_group, msg_id, fields, handler)
    
    # ═══════════════════════════════════════════════════════════
    # 步骤2: 持续消费新消息
    # ═══════════════════════════════════════════════════════════
    logger.info(f"[EventBus] 开始消费新消息: {stream_key}")
    
    while True:
        messages = redis_client.client.xreadgroup(
            groupname=consumer_group,
            consumername=consumer_name,
            streams={stream_key: '>'},  # ← id='>' 读取新消息
            count=count,
            block=block_ms
        )
        
        if not messages:
            continue
        
        for stream, msg_list in messages:
            for msg_id, fields in msg_list:
                _process_message(stream_key, consumer_group, msg_id, fields, handler)
```

**验证方法**：
```bash
# 1. 启动消费者
python examples/transaction_risk_consumer.py

# 2. 发布3条消息
redis-cli XADD stream:large_transaction * event_type test payload "{}"

# 3. 强制杀死消费者进程（Ctrl+C不够，用 kill -9）
kill -9 <pid>

# 4. 重启消费者，观察日志
# 预期输出：
# [EventBus] 检查 Pending List: stream:large_transaction:risk_monitor_group:worker-1
# [EventBus] 重放PEL消息: 1692345678901-0
# [EventBus] 重放PEL消息: 1692345678902-0
# [EventBus] Pending List 已清空，切换到新消息模式
```

---

### 2.3 BUG-3: 条件ACK vs 无条件ACK+幂等

**冲突点**：

| 维度 | 当前实现 | 需求文档§2.4 & F4.1 |
|------|----------|---------------------|
| ACK时机 | handler返回True才ACK | **无条件ACK**（消息取出后立即ACK） |
| 失败处理 | 保留在PEL，无限重试 | **幂等检查**（trace_id去重）+ 死信队列 |
| 优点 | 简单，保证at-least-once | 避免PEL堆积，支持精确一次语义 |
| 缺点 | 毒消息会卡死队列 | 需要额外存储（Redis SET记录trace_id） |

**建议决策**：**采用需求文档方案（无条件ACK+幂等）**

**理由**：
1. **业务特性**：风控告警、客服记录等操作具有天然幂等性（同一trace_id重复执行结果相同）
2. **PEL堆积风险**：条件ACK下，一条毒消息会阻塞整个消费者（Redis Streams串行消费特性）
3. **监控需求**：需求文档F4.1明确要求"trace_id去重"和"死信队列"

**修复方案**：
```python
def _process_message(stream_key, consumer_group, msg_id, fields: Dict, handler):
    """处理单条消息（无条件ACK + 幂等检查）"""
    redis_client = get_redis_client()
    
    try:
        # ═══════════════════════════════════════════════════════
        # 步骤1: 立即ACK（无条件）
        # ═══════════════════════════════════════════════════════
        redis_client.client.xack(stream_key, consumer_group, msg_id)
        logger.info(f"[EventBus] ACK消息: {msg_id}")
        
        # ═══════════════════════════════════════════════════════
        # 步骤2: 幂等检查（trace_id去重）
        # ═══════════════════════════════════════════════════════
        trace_id = fields.get('trace_id', '')
        idempotent_key = f"eventbus:processed:{trace_id}"
        
        # SET NX EX 86400 → 如果key不存在则设置，过期时间24小时
        is_first_time = redis_client.client.set(idempotent_key, '1', nx=True, ex=86400)
        
        if not is_first_time:
            logger.warning(f"[EventBus] 重复消息，跳过: trace_id={trace_id}")
            return
        
        # ═══════════════════════════════════════════════════════
        # 步骤3: 调用业务handler
        # ═══════════════════════════════════════════════════════
        event_type = fields.get('event_type', '')
        payload_str = fields.get('payload', '{}')
        payload = json.loads(payload_str)
        
        logger.info(f"[EventBus] 处理消息: type={event_type}, trace_id={trace_id}")
        success = handler(event_type, payload, trace_id)
        
        if not success:
            # ═══════════════════════════════════════════════════
            # 步骤4: 失败写入死信队列
            # ═══════════════════════════════════════════════════
            dead_letter_key = f"{stream_key}:dead_letter"
            redis_client.client.xadd(dead_letter_key, {
                'original_stream': stream_key,
                'original_msg_id': msg_id,
                'event_type': event_type,
                'payload': payload_str,
                'trace_id': trace_id,
                'error_time': datetime.now().isoformat(),
                'handler_name': handler.__name__
            })
            logger.error(f"[EventBus] 处理失败，已写入死信队列: {dead_letter_key}")
    
    except Exception as e:
        logger.error(f"[EventBus] 消息处理异常: {msg_id}, error={e}")
        # 异常也写入死信队列（可选）
```

**对比测试**：
```python
# 场景1: 正常消息
publish(stream_key, 'event_A', {...})
# 预期: handler执行1次，ACK成功

# 场景2: 重复消息（网络重传/PEL重放）
publish(stream_key, 'event_A', {...})  # 同一trace_id
# 预期: handler执行0次（幂等去重），ACK成功

# 场景3: 毒消息（handler抛异常）
publish(stream_key, 'event_B', {...})
# 预期: handler抛异常，ACK成功，消息进入死信队列
```

---

## 三、架构决策

### 决策1: 是否添加 `source_agent` 字段？时间戳格式？

**建议**: ✅ **添加 `source_agent`，时间戳用毫秒字符串**

**理由**：
- **source_agent**: 分布式链路追踪需求（客服Agent→风控Agent→通知Agent），死信队列排查需要源头信息
- **timestamp格式**: 
  - ISO8601(`2026-08-15T14:30:00+08:00`) 可读性好但解析慢
  - 毫秒字符串(`"1692345678901"`) 高性能，Python `int(ts)` 即可转换
  - **推荐毫秒字符串**（Event-Driven架构注重吞吐量）

**统一格式**：
```python
# publish() 自动注入
{
    'event_type': 'large_transaction_detected',
    'trace_id': 'uuid4-string',
    'timestamp': '1692345678901',  # 毫秒时间戳字符串
    'source_agent': 'TransactionAgent',  # 发布者标识
    'payload': {...}  # 业务数据
}
```

---

### 决策2: `publish()` 最终签名

**建议签名**：
```python
@staticmethod
def publish(
    stream_key: str,
    event_type: str,
    payload: dict,
    source_agent: str = 'unknown',  # 新增：发布者标识
    trace_id: Optional[str] = None   # 可选：支持传递上游trace_id
) -> str:
    """发布事件到指定Stream
    
    Args:
        stream_key: Redis Stream键名（如 'stream:large_transaction'）
        event_type: 事件类型（如 'large_transaction_detected'）
        payload: 业务数据（dict，会序列化为JSON）
        source_agent: 发布者Agent名称（默认'unknown'）
        trace_id: 分布式跟踪ID（不传则自动生成UUID）
    
    Returns:
        str: Redis消息ID（如 '1692345678901-0'）
    """
```

**向后兼容**：原有调用 `publish(stream_key, event_type, payload)` 仍然有效（source_agent默认'unknown'）。

---

### 决策3: ACK/幂等策略

**最终决策**: ✅ **无条件ACK + 幂等检查**（见2.3节详细方案）

**实施要点**：
- Redis SET NX存储已处理trace_id，过期时间24小时
- handler返回False时写入死信队列 `{stream_key}:dead_letter`
- 死信队列手动排查或定时告警（Day 3监控任务）

---

### 决策4: Payload统一方案

**建议**: ✅ **强制Group A冻结合约 + 兼容层**

**统一Schema**（基于Group A合约）：
```python
# schemas.py 修改后

class LargeTransactionEvent(BaseModel):
    """大额交易事件（≥5万）
    
    注意：发布者不过滤金额，消费者自行判断阈值
    """
    customer_id: int
    transaction_id: int  # 统一用 transaction_id（不是 tx_id）
    
    # 可选字段（发布者尽量提供，消费者容错处理）
    product_id: Optional[int] = None
    amount: Optional[str] = None  # 字符串类型（如 "60000.00"）
    transaction_type: Optional[str] = None  # 中文（如 "申购"/"赎回"）
    
    # 扩展字段（放在这里，不影响核心合约）
    customer_name: Optional[str] = None
    product_name: Optional[str] = None
    channel: Optional[str] = None
    transaction_time: Optional[str] = None

class SuspiciousIntentEvent(BaseModel):
    """可疑意图事件"""
    customer_id: int
    session_id: str
    intent_type: str  # "money_laundering" | "fraud" | "phishing"
    confidence: str  # 字符串（如 "0.85"）
    evidence: Optional[dict] = None
    detected_at: Optional[str] = None

class RiskAlertEvent(BaseModel):
    """风控告警事件"""
    customer_id: int
    alert_id: int
    rule_id: str
    severity: str  # "low" | "medium" | "high" | "critical"
    trigger_details: Optional[dict] = None
    created_at: Optional[str] = None
```

**兼容层实现**（可选，支持旧代码平滑迁移）：
```python
# eventBus.py 新增

def _normalize_payload(event_type: str, payload: dict) -> dict:
    """Payload规范化（兼容旧字段名）"""
    normalized = payload.copy()
    
    # 兼容1: tx_id → transaction_id
    if 'tx_id' in normalized and 'transaction_id' not in normalized:
        normalized['transaction_id'] = normalized.pop('tx_id')
    
    # 兼容2: amount 转字符串
    if 'amount' in normalized and isinstance(normalized['amount'], (int, float)):
        normalized['amount'] = str(normalized['amount'])
    
    # 兼容3: tx_type → transaction_type（英文转中文）
    if 'tx_type' in normalized:
        type_map = {'purchase': '申购', 'redeem': '赎回', 'buy': '申购', 'sell': '赎回'}
        normalized['transaction_type'] = type_map.get(normalized['tx_type'], normalized['tx_type'])
        normalized.pop('tx_type')
    
    return normalized
```

**迁移计划**：
1. **Day 2上午**：更新 schemas.py，添加兼容层
2. **Day 2下午**：更新 examples 使用新schema
3. **Day 3**：各Agent实际接入时统一使用新schema

---

## 四、实施计划

### 4.1 修改文件清单

| 文件 | 修改内容 | 预计耗时 |
|------|----------|----------|
| `eventBus.py` | 1. 修复bytes键bug<br>2. 新增PEL重放逻辑<br>3. 实现无条件ACK+幂等 | 30分钟 |
| `schemas.py` | 统一三个Event的payload定义 | 10分钟 |
| `examples/transaction_risk_consumer.py` | 更新payload字段名（tx_id→transaction_id等） | 5分钟 |

**总耗时**: 约 45 分钟

### 4.2 测试验证

#### 测试1: bytes键修复
```bash
# 1. 发布事件
redis-cli XADD stream:test * event_type "test_event" payload '{"foo":"bar"}' trace_id "test-123"

# 2. 消费验证
python -c "
from app.WealthButler.EventBus.eventBus import EventBus
def handler(event_type, payload, trace_id):
    assert event_type == 'test_event', f'Expected test_event, got {event_type}'
    assert payload == {'foo': 'bar'}, f'Expected {{foo:bar}}, got {payload}'
    print('✅ bytes键修复验证通过')
    return True
EventBus.consume('stream:test', 'test_group', 'worker1', handler, block_ms=1000, count=1)
"
```

#### 测试2: PEL重放
```bash
# 1. 启动消费者但不ACK（模拟crash）
redis-cli XADD stream:test2 * event_type "test" payload "{}" trace_id "pel-test"
# 手动kill消费者进程

# 2. 检查PEL
redis-cli XPENDING stream:test2 test_group2
# 预期输出: 1条pending消息

# 3. 重启消费者
# 预期日志: [EventBus] 重放PEL消息: <msg_id>
```

#### 测试3: 幂等性
```python
# 相同trace_id发送2次
EventBus.publish('stream:test3', 'dup_test', {'data': 1}, trace_id='same-trace-id')
EventBus.publish('stream:test3', 'dup_test', {'data': 2}, trace_id='same-trace-id')

# 预期: handler只执行1次
```

---

## 五、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 幂等存储Redis压力 | 中 | 低 | 24小时TTL自动清理，预估10万trace_id仅占10MB |
| 死信队列堆积 | 低 | 中 | Day 3接入监控告警，定期人工排查 |
| 旧代码兼容性 | 低 | 中 | 提供兼容层 `_normalize_payload()` |
| PEL重放性能 | 低 | 低 | 启动时一次性重放，非热路径 |

---

## 六、后续优化（Day 3+）

1. **监控面板**：Grafana展示死信队列长度、消费延迟、幂等命中率
2. **死信重试**：人工审核后重新投递到原Stream
3. **Consumer水平扩展**：同一consumer_group部署多个worker实例（Redis Streams天然支持）
4. **Schema版本管理**：event_type加版本号（如`large_transaction_detected.v2`）

---

## 七、批准签字

- [ ] **李清华**（开发）- 2026-08-15
- [ ] **聂柏**（风控Agent负责人/需求方）- 待确认
- [ ] **架构师审核**（如有）- 待确认

**预计开始实施时间**: 审批通过后立即开始（预计2026-08-15下午）
