# Day 2 工作总结

**日期**: 2026-08-15  
**负责人**: 李清华  
**工作时间**: 下午

---

## 完成工作概览

### 1. EventBus问题修复 ✅ 100%完成

**问题来源**: 聂柏（风控Agent负责人）反馈三个bug

**修复内容**:
- **Bug-1**: bytes键解析失败 → 修改为str键访问
- **Bug-2**: PEL从未重放 → 实现启动时重放Pending List
- **Bug-3**: 条件ACK机制冲突 → 改为无条件ACK + 幂等检查（trace_id去重）

**架构优化**:
- 统一Event Schema（基于Group A冻结合约）
- publish()新增source_agent参数
- timestamp改为毫秒字符串格式
- 失败消息写入死信队列

**交付物**:
- 修改文件：eventBus.py, schemas.py, transaction_risk_consumer.py
- 新增文档：docs/EventBus问题修复方案.md

---

### 2. Milvus优化 ✅ 100%完成

**问题来源**: 客服Agent负责人反馈FAQ/产品数据质量问题

**数据清洗**:
- FAQ去重：39条数据验证无重复
- 产品数据清洗：生成11个产品的风险等级+产品代码映射表

**V2集合设计**:
- 采用三字段Schema（id/text/metadata/embedding）
- metadata使用JSON存储业务字段（Schema灵活易扩展）
- 支持jieba中文分词（text字段预留）

**数据迁移**:
- 产品集合V2：19条记录迁移成功
- 政策集合V2：117条记录迁移成功
- 旧集合保留完整（回滚方案）

**技术决策**:
- 暂时不使用BM25稀疏向量（Milvus Function Output机制尚未成熟）
- 当前V2仍使用纯稠密向量检索
- Schema已为未来混合检索做好准备

**交付物**:
- 新增模型：productCollectionModelV2.py, policyCollectionModelV2.py
- 新增脚本：migrate_to_v2_collections_simple.py, drop_v2_collections.py
- 新增文档：3个方案文档

---

## Git提交记录

1. **修复 EventBus 三大bug并统一 Event Schema** (commit: 1ef0d31)
   - 14 files changed, 2813 insertions(+), 83 deletions(-)

2. **完成 Milvus V2 集合模型与数据清洗准备** (commit: db896cb)
   - 5 files changed, 578 insertions(+)

3. **完成 Milvus V2 集合数据迁移（三字段Schema）** (commit: 4173d3f)
   - 5 files changed, 290 insertions(+), 40 deletions(-)

**总计**: 24个文件变更，约3700行代码

---

## 待完成工作（Day 2下午或Day 3）

### P0 多Agent协作编排攻坚
- [ ] 跑通至少2个不同agent_type的分发验证（如客服/投顾各一次）
- [ ] 填充真实Agent调用（当前返回mock响应）
- [ ] 对照ADR-6核对实现是否一致

### P1 Milvus检索逻辑更新
- [ ] 更新RAG检索服务，支持V2集合查询
- [ ] 从metadata JSON字段提取业务数据
- [ ] 阈值调整测试（准备30道标准测试问题）

### P1 补齐Day1数据层遗留
- [ ] 检查MySQL/Milvus/Neo4j是否有Day1未建完的表/集合/schema

---

## 成果亮点

1. **EventBus可靠性提升**
   - 解决消息丢失风险（PEL重放）
   - 避免毒消息阻塞（死信队列）
   - 防止重复处理（幂等检查）

2. **Milvus Schema标准化**
   - 三字段模式统一四个集合
   - 业务字段变更无需重建集合
   - 类型安全避免Day 1的类型错误

3. **文档完善**
   - 3个详细方案文档（总计3000+字）
   - 问题分析+解决方案+验证方法完整

---

## 技术债务记录

1. **混合检索暂未实现**
   - 原因：Milvus BM25 Function Output机制不成熟
   - 影响：当前仍使用纯稠密向量检索
   - 计划：Milvus 2.5+版本稳定后再升级

2. **V2集合检索逻辑未切换**
   - 原因：时间优先EventBus修复
   - 影响：应用层仍调用V1集合
   - 计划：Day 2下午或Day 3完成切换

---

## 协作通知

**已通知人员**:
- 聂柏：EventBus修复完成，可继续风控Agent开发
- 赵嘉/袁艺铭：Milvus V2集合已就绪，RAG检索逻辑待更新

**待同步**:
- 全员：Day 2晚会议纪要同步进度
