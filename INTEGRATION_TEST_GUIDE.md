# 联调支援验证报告

## 验证时间
2026-08-15

## 验证内容

### 1. Milvus检索功能验证

#### 测试集合
- `fin_faq_collection` - FAQ问答集合
- `fin_product_collection` - 产品资料集合  
- `fin_policy_collection` - 政策法规集合

#### 验证结果
所有集合已创建但**当前无数据**，需要先运行数据摄取脚本。

**问题分析**：
- 集合Schema正常，使用统一的三字段模式（id + text + metadata + embedding）
- 基础连接正常，集合存在
- 需要运行 `scripts/rag_ingestion_full.py` 进行数据摄取

**修复建议**：
```bash
# 先运行数据摄取脚本
python scripts/rag_ingestion_full.py

# 然后验证检索功能
python scripts/verify_milvus_search.py
```

---

### 2. EventBus发布订阅功能验证

#### 测试项目
- Redis连接测试
- EventBus发布功能
- EventBus消费功能
- transaction_risk_consumer.py脚本可用性

#### 验证结果

| 测试项 | 状态 | 说明 |
|-------|------|------|
| Redis连接 | ✓ 正常 | Redis 7.0.15，连接正常 |
| EventBus发布 | ✓ 正常 | XADD命令工作正常，消息已写入Stream |
| EventBus消费 | ✗ 存在问题 | 消费者线程未能正常接收事件 |
| transaction_risk_consumer.py | ✓ 可用 | 脚本文件存在，可正常导入 |

**发现的问题**：

1. **EventBus消费Bug**（已修复）
   - 问题：`eventBus.py`第216行调用了不存在的`get_redis_client()`函数
   - 影响：消费者线程启动时会抛出`NameError`
   - 修复：已改为正确导入`from app.Base.Client.redisClient import redis_client`
   - 位置：`app/WealthButler/EventBus/eventBus.py:216`

2. **Milvus count()方法Bug**
   - 问题：空filter调用query()时需要指定limit参数
   - 错误信息：`empty expression should be used with limit: invalid parameter`
   - 影响：无法正确统计集合数据量
   - 建议修复位置：`app/Base/Repository/base/baseVDB.py:907` count()方法

---

### 3. 遗留问题清单

#### Day 1 EventBus修复回顾
根据git commit `1ef0d31`，Day 1修复的三大bug：
1. ✓ 统一Event Schema（event_type + payload + timestamp + trace_id + source_agent）
2. ✓ 消费者幂等性机制（trace_id去重 + 无条件ACK）
3. ✗ **消费者导入问题未完全修复**（本次发现并修复）

#### 当前遗留问题
1. **Milvus集合无数据** - 需要运行数据摄取
2. **BaseVDBModel.count()方法Bug** - 需要修复空filter时的limit参数

---

## 验证脚本使用指南

### 可用的验证脚本

#### 1. Milvus检索验证
```bash
python scripts/verify_milvus_search.py
```

**功能**：
- 检查三个Milvus集合是否存在
- 统计数据量
- 执行search()方法测试（使用零向量）
- 显示样本检索结果

**输出示例**：
```
======================================================================
  1. 测试 FAQ 集合检索
======================================================================

集合名称: fin_faq_collection
集合存在: True
数据量: 0
[!] 集合存在但无数据
```

---

#### 2. EventBus功能验证
```bash
python scripts/verify_eventbus.py
```

**功能**：
- 测试Redis连接
- 测试EventBus.publish()发布功能
- 测试EventBus.consume()消费功能（独立线程）
- 验证transaction_risk_consumer.py可用性
- 自动清理测试产生的Stream

**输出示例**：
```
======================================================================
  1. 测试 Redis 连接
======================================================================
[OK] Redis 连接正常

Redis 服务器信息:
  - 版本: 7.0.15
  - 运行模式: standalone
  - 运行时间(天): 0
```

---

#### 3. transaction_risk_consumer示例
```bash
python app/WealthButler/EventBus/examples/transaction_risk_consumer.py
```

**功能**：
- 模拟发布大额交易事件
- 启动风控监测消费者
- 应用反洗钱规则RW-001
- 写入fin_risk_alert表
- 完整流程演示

**使用场景**：
- 验证EventBus端到端流程
- 测试风控规则引擎集成
- 演示消费者处理逻辑

---

## 调试指南

### Milvus检索问题排查

#### 症状1：集合不存在
```python
集合存在: False
```

**排查步骤**：
1. 检查Milvus服务是否运行：`docker ps | grep milvus`
2. 检查.env配置：`MILVUS_HOST`, `MILVUS_PORT`
3. 检查集合名称是否正确（collection_alias）

---

#### 症状2：集合无数据
```python
集合存在: True
数据量: 0
```

**解决方案**：
```bash
# 运行完整数据摄取
python scripts/rag_ingestion_full.py

# 或者分别运行各集合摄取
python scripts/product_ingestion_v2.py
```

---

#### 症状3：search()方法报错
```python
MilvusException: dimension mismatch
```

**排查步骤**：
1. 确认embedding维度：bge-m3模型为1024维
2. 检查模型配置中的dim参数
3. 验证Ollama服务是否运行

---

### EventBus问题排查

#### 症状1：Redis连接失败
```python
[X] Redis 连接失败
```

**排查步骤**：
1. 检查Redis服务：`redis-cli ping`
2. 检查.env配置：`REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
3. 检查防火墙规则

---

#### 症状2：消费者未接收到事件
```python
[!] 消费者未接收到事件（可能是超时或消费者未正常启动）
```

**排查步骤**：
1. 检查消费者线程是否正常启动（查看日志）
2. 检查消费组是否创建：`redis-cli XINFO GROUPS stream:test_consume`
3. 检查Pending List：`redis-cli XPENDING stream:test_consume verify_group`
4. 增加block_ms超时时间

---

#### 症状3：NameError: get_redis_client
```python
NameError: name 'get_redis_client' is not defined
```

**解决方案**：
已在`app/WealthButler/EventBus/eventBus.py:216`修复，改为：
```python
from app.Base.Client.redisClient import redis_client
```

---

### Redis Streams调试命令

#### 查看Stream信息
```bash
# 查看Stream长度
redis-cli XLEN stream:large_transaction

# 查看Stream内容（最后10条）
redis-cli XREVRANGE stream:large_transaction + - COUNT 10

# 查看消费组信息
redis-cli XINFO GROUPS stream:large_transaction

# 查看Pending List
redis-cli XPENDING stream:large_transaction risk_monitor_group
```

#### 清理测试数据
```bash
# 删除测试Stream
redis-cli DEL stream:test_verify stream:test_consume

# 删除消费组
redis-cli XGROUP DESTROY stream:test_consume verify_group
```

---

## 数据摄取脚本说明

### 完整数据摄取
```bash
python scripts/rag_ingestion_full.py
```

**包含内容**：
- FAQ数据摄取（从MySQL读取）
- 产品数据摄取（从data目录读取）
- 政策法规数据摄取（从data目录读取）

### 分步摄取（推荐用于调试）
```bash
# 仅摄取产品数据
python scripts/product_ingestion_v2.py

# 清理所有RAG数据
python scripts/clean_all_rag_data.py

# 清理并重新摄取
bash scripts/clean_and_reingest.sh
```

---

## 性能基准

### Milvus检索性能
- 向量维度：1024维（bge-m3）
- 索引类型：HNSW（M=16, efConstruction=200）
- 预期延迟：<50ms（本地部署）

### EventBus吞吐量
- Redis Streams理论吞吐：>100k msg/s
- 单消费者处理速度：取决于handler逻辑
- 推荐block_ms：5000ms（生产环境）

---

## 团队成员快速上手

### 前置条件检查
```bash
# 1. 检查服务状态
docker ps | grep -E 'milvus|redis|mysql|neo4j'

# 2. 检查Python环境
python --version  # 应为3.11+
pip list | grep -E 'pymilvus|redis|pymysql'

# 3. 检查.env配置
cat .env | grep -E 'MILVUS|REDIS|MYSQL'
```

### 快速验证流程
```bash
# Step 1: 验证EventBus
python scripts/verify_eventbus.py

# Step 2: 运行数据摄取（如果Milvus无数据）
python scripts/rag_ingestion_full.py

# Step 3: 验证Milvus检索
python scripts/verify_milvus_search.py

# Step 4: 测试完整EventBus流程
python app/WealthButler/EventBus/examples/transaction_risk_consumer.py
```

---

## 联系与支持

如果遇到问题，请按优先级检查：
1. 本文档的"调试指南"章节
2. git commit历史中的相关修复（特别是Day 1-2的EventBus修复）
3. 验证脚本的详细输出日志

---

## 附录：已修复的Bug列表

| Bug ID | 描述 | 修复位置 | 修复日期 |
|--------|------|---------|---------|
| EB-001 | EventBus消费者导入错误 | eventBus.py:216 | 2026-08-15 |
| MV-001 | Milvus count()空filter bug | baseVDB.py:907 | 待修复 |

---

**文档版本**: v1.0  
**最后更新**: 2026-08-15  
**维护者**: AI开发团队
