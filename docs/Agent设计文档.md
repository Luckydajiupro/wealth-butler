# Agent设计文档

## 0. 文档说明

**定位**：本文档是《API接口设计文档.md》§3"内部Tool清单"和《架构设计文档.md》§8"五个Agent内部技术架构"的进一步落地展开，面向5个Agent负责人的**实现层**规范——System Prompt骨架、意图分类到处理函数的映射表、Tool详细入参出参Schema、二次确认状态机的完整流转细节、逐Agent验收标准自查对照表。

**不重复的内容**：架构设计文档§8已有的5张mermaid流程图、§5的6条ADR决策依据、需求文档§5的完整业务规则原文，本文档不重新画图/不重新抄条文，只引用章节号；本文档聚焦"负责人写代码时能直接对照填空"的细化颗粒度。

**分工边界**（与API接口设计文档§0同一原则）：本文档定义每个Agent的System Prompt骨架、意图→处理函数映射、Tool的输入输出Schema——这是"契约"层。Prompt具体措辞、处理函数内部实现、LLM调用细节留给对应Agent负责人自行完成。

**5个Agent负责人分工**（同架构设计文档§8/需求文档§2.2）：智能客服Agent、投顾助手Agent、风控监测Agent、数据分析Agent、业务操作Agent，各自1名负责人。

---

## 1. 通用规范（4个对话类Agent共享，风控监测Agent除外见§6）

### 1.1 继承与构造

```python
class XxxAgent(ReActAgent):
    def classify_intent(self, text: str) -> tuple[str, float]: ...   # 返回(意图标签, 置信度)
    def _get_handler(self, intent: str) -> Callable: ...              # 意图 → 处理函数
    def _intent_threshold(self) -> float: ...                          # 本Agent的置信度阈值
    def _scenario_name(self) -> str: ...                                # 场景标识，供§5.4.1综合重排的"场景权重"使用
```

中间件洋葱顺序（架构设计文档§2.3）：`Logging → Metrics → Safety → MemoryRecallMiddleware(新增) → Eval`，构造时统一传入`llm/tools/memory/middlewares`，不在子类里重新拼装链路。

### 1.2 System Prompt通用骨架（5段式模板）

| 段落 | 内容 | 说明 |
|---|---|---|
| ①角色定义 | "你是XX系统的XX Agent，服务对象是XX" | 明确单一服务对象（见§2.2职责矩阵），不要让Prompt里出现"你可以帮任何用户做任何事" |
| ②能力边界 | 能做什么 + **明确不能做什么**（越权场景直接拒绝话术） | 尤其RBAC相关：客服Agent不得执行任何写操作、投顾/业务操作Agent不得跳过适当性校验直接给结论 |
| ③工具使用说明 | 本Agent可调用的Tool清单 + 各Tool的调用时机 | 与§7 Tool Schema表一一对应，Prompt里只写"何时调用"，不重复Schema细节（Schema由Function Calling自动传给LLM） |
| ④输出格式约束 | 是否要求引用来源、是否要求结构化字段（如`confirm_required`）、SSE流式下的分段策略 | 对齐API接口设计文档§1.4 AgentResult结构 |
| ⑤合规红线重申 | 每个Agent各自的强制项 | 客服Agent："不得承诺收益/预测涨跌"；业务操作Agent："超阈值必须走二次确认，不得自行执行" |

### 1.3 AgentResult返回与metadata扩展

非流式响应体固定包装`{success, output, tool_calls, iterations, duration_ms, error_msg, token_usage, metadata}`（`Ai/base/baseAgent.py`）。`metadata`是各Agent自定义扩展字段的位置，本文档§2~§5逐Agent列出各自会用到的`metadata`键，需与API接口设计文档§2.1响应体描述保持一致（如`metadata.generated_sql`/`metadata.confirm_required`/`metadata.admission_tier`）。

---

## 2. 智能客服Agent（RAG + 短期记忆）

### 2.1 意图分类清单

| 意图标签 | 处理函数 | 说明 |
|---|---|---|
| `product_consult` | `_handle_product_consult` | 走`KnowledgeRetrieval`检索`fin_product_collection` |
| `policy_explain` | `_handle_policy_explain` | 走`KnowledgeRetrieval`检索`fin_policy_collection` |
| `faq` | `_handle_faq` | 走`KnowledgeRetrieval`检索`fin_faq_collection` |
| `chitchat` | `_handle_chitchat` | 不调用检索工具，直接LLM生成，不联网/不编造产品数据 |
| `transfer_to_human` | `_handle_transfer_to_human` | 调用`work_order_tool`写`biz_work_order`（`order_type="客户转介"`，见架构设计文档§2.4.1） |

**两个阈值不要混淆**：
- `_intent_threshold() = 0.6`（需求文档§2.3）：5类意图分类本身的置信度阈值，低于此值时退回`chitchat`兜底或直接触发`transfer_to_human`。
- **RAG检索Score阈值0.7~0.75**（架构设计文档§8.1）：`product_consult`/`policy_explain`/`faq`三个意图各自检索后，命中Score低于对应集合阈值（FAQ 0.75，产品/政策0.7）时，视为"检索不到可靠答案"，同样兜底触发`transfer_to_human`，不是意图分类本身判定为转人工。

### 2.2 使用的Tool

`KnowledgeRetrieval`（RAG检索，见§7.1）、`ProfileExtract`（对话中识别出客户属性/偏好时抽取写入`memory_units`，见§7.2）、`work_order_tool`（转介工单外壳，非§7列出的10个AI Tool之一，是`biz_work_order`表的通用CRUD封装）。

可疑意图识别（如客户话语透露洗钱线索）时调用`EventBus.publish("suspicious_intent", ...)`（架构设计文档§2.4），这是事件发布而非Function Calling工具调用，在`_handle_*`函数末尾直接调用即可。

### 2.3 metadata扩展字段

`metadata.source_refs`（RAG命中的来源列表，供前端"引用来源"展示）、`metadata.transfer_ticket_id`（触发转人工时新建的`biz_work_order.id`）。

### 2.4 验收标准自查（需求文档F1.3）

- [ ] 产品咨询准确率≥80%（5题以上测试用例）
- [ ] 政策解读2题以上测试用例通过
- [ ] 多轮对话3轮以上，上下文不丢失（短期记忆`session:{id}:messages`，TTL30min）
- [ ] Score<0.7（或0.75，按集合）触发兜底转人工后，能在理财顾问/客户经理工作台查到对应`biz_work_order`

---

## 3. 投顾助手Agent（GraphRAG + 中期记忆）

### 3.1 处理流程（非多意图分类，单一推荐管线）

投顾助手Agent不是"多意图并列选择"结构，而是一条固定管线（架构设计文档§8.2 mermaid图）：`中期记忆召回(fin_customer_profile) → SuitabilityCheck过滤 → GraphQuery图谱增强 → 融合排序 → 多因子排序 → LLM生成推荐理由`。`_get_handler()`可简化为单一`_handle_recommend`，`_intent_threshold() = 0.65`用于判断"是否需要澄清追问"（如客户意向产品类型模糊时先追问，而非直接输出）而非多意图路由。

若对话中出现追问场景（"为什么推荐这个"/"换一个风险更低的"），归为同一处理函数内部的子分支，不单独定义新意图标签。

**融合排序与多因子排序是Agent内部业务逻辑，不是独立Tool**：`融合Score = 向量Score×0.6 + 图谱Score×0.4`、`多因子Score = 收益0.3+风险匹配0.25+期限0.15+分散度0.15+图谱信号0.15`（架构设计文档§8.2）直接写在`_handle_recommend`函数体内，不通过`BaseTool`/Function Calling暴露——因为LLM不需要"决定要不要排序"，排序是确定性代码步骤，套Function Calling反而增加一次不必要的模型调用。

### 3.2 使用的Tool

`SuitabilityCheck`（适当性硬匹配过滤，见§7.3）、`GraphQuery`（Neo4j多跳查询行业分散度信号，见§7.4）。

### 3.3 与`POST /api/product/recommend`、`POST /api/profile/{customer_id}/assessment`的复用关系

API接口设计文档§2.4的`POST /api/product/recommend`（结构化推荐，供前端"一键推荐"按钮）内部直接复用本节`_handle_recommend`同一套融合排序+多因子排序逻辑，只是不经过`ReActAgent`对话循环、不生成LLM自然语言推荐理由——实现时应把排序逻辑拆成独立的纯函数（如`rank_products(customer_id) -> list[ProductScore]`），被对话入口（`/api/chat/advisor`）和结构化入口（`/api/product/recommend`）两处共同调用，不要在Agent类内部重复实现一遍。

`POST /api/profile/{customer_id}/assessment`（风评问卷提交与四维度重算）归属本Agent负责人（画像计算引擎所在处，见API接口设计文档§2.3），但触发入口有两条：客户/理财顾问直接调用该REST端点提交问卷；或理财顾问通过业务操作Agent发起"风评重做"对话意图（见§5.2）。两条入口最终都应调用同一个画像重算函数（如`recalculate_profile(customer_id, answers)`），业务操作Agent的`_handle_reassess`函数内部直接调用这个共享函数，不要在业务操作Agent里重新实现一遍四维度加权公式（需求文档§5.3第十条）。

### 3.4 metadata扩展字段

`metadata.graph_signals`（图谱增强命中的行业分散度等信号，供前端展示"为什么推荐"）、`metadata.admission_tier`（`可执行|仅预约`，两层准入结构判断结果，需求文档§5.1）。

### 3.5 验收标准自查（需求文档F3.2/F3.3）

- [ ] GraphRAG效果优于纯RAG（对比测试，至少1组）
- [ ] 推荐符合风险等级（C1客户不推R4+产品）
- [ ] Neo4j节点数>100、关系数>200（F3.1，图谱数据导入，非本Agent代码工作量但影响本Agent效果）
- [ ] 私募/资管类产品被正确判定为"仅预约"而非直接可执行

---

## 4. 数据分析Agent（NL2SQL）

### 4.1 处理流程（单一路径，非意图分类）

`_get_handler()`固定返回`_handle_nl2sql`，不做多意图分类；`_intent_threshold() = 0.5`（矩阵最低值）在本Agent的语境下含义是"生成SQL后LLM自评置信度低于此值时，附加提示'结果可能不准确，建议人工复核'，但仍执行查询"，而非阻止执行——因为内部只读查询出错不造成业务后果（需求文档§2.3），比其余3个Agent"低置信度即拒绝/转人工"的处理方式更宽松。

流程：Redis缓存命中检查(`nl2sql:cache:{query_hash}`，TTL10min) → 未命中则动态Schema筛选+few-shot → LLM生成SQL → `NL2SQL`安全校验层 → 执行(限100行) → LLM自然语言解读结果 → 写回缓存。

### 4.2 使用的Tool

`NL2SQL`（见§7.5），是本Agent的核心新写工作量，不复用脚手架`SQLBuilder`（其不做表名/字段白名单，见需求文档§2.7代码核实依据）。

### 4.3 metadata扩展字段

`metadata.generated_sql`（携带生成的SQL供审计，需求文档§8.2 NL2SQL安全要求）、`metadata.row_count`、`metadata.cache_hit`(bool)。

### 4.4 验收标准自查（需求文档F2.3）

- [ ] 准确率≥80%（5题以上测试用例）
- [ ] 安全校验正确拒绝DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE等危险语句
- [ ] 结果行数超100行时被正确截断
- [ ] 白名单外的表/字段被正确拒绝

---

## 5. 业务操作Agent（NL2API）

### 5.1 意图分类清单

| 意图标签 | 处理函数 | 所需权限 | 说明 |
|---|---|---|---|
| `purchase` | `_handle_purchase` | `operation:purchase`（理财顾问） | 走两层准入结构（§5.1）+ 二次确认（>1万，见§5.4） |
| `redeem` | `_handle_redeem` | `operation:redeem` | 同上准入结构判断，无二次确认阈值（原文未对赎回设二次确认线，需求文档§8.2仅列申购/转账） |
| `transfer` | `_handle_transfer` | `operation:transfer`（客户经理） | 二次确认（>5万，见§5.4） |
| `reassess` | `_handle_reassess` | `risk:reassess`（理财顾问代客户） | 内部调用§3.3所述共享画像重算函数，不重复实现 |
| `update_info` | `_handle_update_info` | `customer:info_update`（客户经理） | 对应`PUT /api/operation/contact`，仅联系方式类非敏感字段 |
| `product_query` | `_handle_product_query` | `product:query` | 只读，对应`GET /api/product/list|{id}` |
| `suspicious_report` | `_handle_suspicious_report` | `risk:suspicious_report`（理财顾问/客户经理/风控专员均持有，需求文档§3.3） | 员工主动上报可疑交易，写入`fin_risk_alert`（人工触发，与风控Agent自动触发并列，`alert_type`可标注"人工上报"）；理财顾问/客户经理代客户操作时人工发现可疑交易可直接上报，不必须经风控专员中转 |
| `workorder_create` | `_handle_workorder_create` | `workorder:create`（客户经理） | 员工主动手工创建工单，与"客户转介"工单（系统自动创建，见架构设计文档§2.4.1）是同一张表不同`order_type`，本意图不占用/不依赖`workorder:create`以外的权限判断逻辑 |

`_intent_threshold() = 0.75`（矩阵最高值，涉及资金写操作，出错代价最大，需求文档§2.3）。入口不做统一前置RBAC拦截，而是"按识别出的具体意图动态校验"对应权限（API接口设计文档§2.1）——即先分类意图，再按该意图对应权限校验，未通过则直接拒绝并给出缺失权限提示，不进入参数提取环节。

### 5.2 使用的Tool

`NL2API`（Function Calling参数提取，见§7.6）、`SuitabilityCheck`（`purchase`意图内复用，与投顾Agent共享同一实现，不重写）、`work_order_tool`（`workorder_create`意图）。

### 5.3 两层准入结构判断（需求文档§5.1）

`purchase`/`redeem`处理函数内，参数提取完成后先判断`fin_product.product_type`：公募基金/标准化产品 → 走§5.4二次确认阈值判断后直接执行；私募/资管计划类 → 无论金额大小，一律只能提交"预约+资格初核"，不进入实际执行分支，响应体`metadata.admission_tier="仅预约"`。

### 5.4 二次确认状态机完整设计（ADR-4展开）

**触发条件**：`purchase`意图且`amount > COMPLIANCE_THRESHOLDS.operation_confirm_purchase(1万)`，或`transfer`意图且`amount > COMPLIANCE_THRESHOLDS.operation_confirm_transfer(5万)`（需求文档§8.2统一合规阈值配置表，避免硬编码）。

**存储**：Redis Key `confirm_token:{token}`（`token`为UUID4），Value为JSON：
```json
{
  "customer_id": 123,
  "action_type": "purchase",
  "params": {"product_id": 45, "amount": 15000},
  "status": "待确认",
  "requested_by": 8,
  "created_at": "2026-08-13T10:00:00"
}
```
TTL 10分钟（超时未确认自动失效，避免长期挂起占用Redis）。

**状态流转**：

```
待确认 --(POST /api/chat/operator/confirm, action=confirm)--> 已确认 --(立即执行原操作)--> 执行
待确认 --(POST /api/chat/operator/confirm, action=cancel)--> 已取消
```

> 三态命名统一采用需求文档§2.6/架构设计文档ADR-4已定的"待确认→已确认→执行"字面值（`status`枚举的第三态是`执行`不是`已执行`），避免同一个Redis JSON字段在不同文档里出现两种字符串字面值。

1. **生成待确认**：`_handle_purchase`/`_handle_transfer`判断命中阈值后，不执行实际写操作，生成`confirm_token`写入Redis（`status=待确认`），响应体返回`metadata.confirm_required=true`、`metadata.confirm_token`、`metadata.pending_action`（待确认方案摘要，如"申购XX基金1.5万元"，供前端展示给用户确认）。
2. **确认执行**：`POST /api/chat/operator/confirm`收到`{confirm_token, action="confirm"}`后：校验token存在且`status=待确认`（不存在或已过期 → 提示"确认已失效，请重新发起操作"；`status`不是"待确认"→说明重复提交，幂等返回上次执行结果而非重复执行）→ 校验通过后`status`置为`已确认`→立即执行`params`里记录的原操作（写`fin_transaction`/`fin_holdings`）→执行成功后`status`置为`执行`（或直接删除该Redis key，保留至TTL自然过期即可满足审计需要，不强制立即删除）。
3. **取消**：收到`{confirm_token, action="cancel"}`→`status`置为`已取消`，不执行任何写操作，直接返回确认取消结果。

**归属**：本状态机在`SafetyMiddleware`基础上新增（脚手架原`safety/base.py`的`GuardResult`只有"通过/阻断"二态，无确认态字段，需求文档§2.7代码核实依据），由业务操作Agent负责人实现，供`purchase`/`transfer`两个处理函数共用同一套状态机代码，不要各自实现一份。

### 5.5 metadata扩展字段

`metadata.confirm_required`/`metadata.confirm_token`/`metadata.pending_action`（见§5.4）、`metadata.admission_tier`（见§5.3）。

### 5.6 验收标准自查（需求文档F3.4）

- [ ] 意图识别准确率>80%（10用例以上）
- [ ] 参数提取准确率>90%
- [ ] 无权限操作被正确拒绝（覆盖8个意图各自的权限校验）
- [ ] 私募类申购请求被正确拦截为"预约"而非直接执行
- [ ] 申购>1万、转账>5万正确触发二次确认，`confirm`/`cancel`两条分支均可正确闭环
- [ ] 二次确认token过期后重新确认被正确拒绝并给出提示

---

## 6. 风控监测Agent（规则引擎 + 置信度，不走对话范式）

本Agent**不实例化为`ReActAgent`对话骨架**，不存在System Prompt、意图分类、Function Calling这几个概念（架构设计文档§8.3、《待确认疑点补充设计建议.md》疑点3）；`rule.evaluate()`是确定性代码判断，本节改用"规则引擎结构"替代"System Prompt骨架"。

### 6.1 触发入口函数命名

| 触发路径 | 入口函数 | 说明 |
|---|---|---|
| 实时/准实时轨（RW-001/003/008/011/014/015/016/017，共8条） | `on_large_transaction_event(payload)` / `on_suspicious_intent_event(payload)` | `EventBus.consume()`后台监听协程的handler，事件仅作触发信号，函数内部直接回查`fin_transaction`/`base_user`按规则时间窗口判定（RW-011用`counterparty_region`、RW-014用`payer_account_name`、RW-015用`base_user.updated_at`，均为既有字段，无需扩展事件payload） |
| 日批/周批轨（其余12条：RW-002/004/005/006/007/009/010/012/013/018/019/020） | `scan_daily_rules()` / `scan_weekly_rules()` | `Service/scheduler/`的`@scheduled`装饰器注册，按cron周期批量扫描 |

两个入口最终都调用同一个核心函数`RiskRuleMatch.match(customer_id, rule_scope)`（见§7.7），区别只是`rule_scope`传入的规则子集不同（事件触发传对应的1条实时规则，批量扫描传全部12条日批/周批规则），不要为两条轨道各写一套判定逻辑。

### 6.2 使用的Tool

`RiskRuleMatch`（见§7.7），内部直接引用需求文档§5.2的`RULE_WEIGHT`字典与`calc_risk_confidence()`公式（§5.4.2），不通过独立的"置信度计算"Tool（风控置信度公式是`RiskRuleMatch`判定流程的最后一步，与§7.2的`BaseConfidenceCalc`记忆置信度公式是两套不同公式，互不复用，见需求文档§5.3开头的"重要架构说明"）。

### 6.3 三级分级与写库

命中规则后：`alert_level`按需求文档§5.2第三条（1条规则→蓝、2-3条或重复触发→黄、>3条→红）；`confidence`按§5.4.2公式计算；写入`fin_risk_alert`（`alert_type`=规则编号，同批多条规则各自写一行，`rule_weight_tier`/`is_repeat`/`repeat_trigger_count`取值逻辑见《研判规则提取与落地方案.md》§2.2）+ `biz_work_order`（`order_type="风控处置"`）双表，随后`EventBus.publish("risk_alert", ...)`。

### 6.4 验收标准自查（需求文档F4.1）

- [ ] 20条规则全部实现且正确匹配（10测试交易以上，覆盖实时与批量两类）
- [ ] 三级分级正确
- [ ] Streams生产/消费/ACK正常，模拟消费者重启后未ACK消息可续处理（PEL重放）
- [ ] 定时批量任务按cron周期正确触发
- [ ] 同批多规则命中时`alert_level`按"就高原则"合并、各触发规则独立列明不遗漏（需求文档§5.2第四~五条）

---

## 7. 内部Tool详细Schema（10个Tool，均继承`BaseTool`，`to_openai_schema()`自动生成Function Calling schema）

### 7.1 KnowledgeRetrieval（RAG检索）

| | |
|---|---|
| 所属Agent | 智能客服Agent |
| 入参 | `query: str`（检索文本）、`collection: enum[faq\|product\|policy]`、`top_k: int?`（默认按集合：FAQ 3/产品5/政策5）、`score_threshold: float?`（默认：FAQ 0.75/产品0.7/政策0.7） |
| 出参 | `{hits: [{content: str, score: float, source_id: str, source_type: str}], hit_count: int}` |
| 实现要点 | 产品/政策集合走混合检索（稠密+BM25），FAQ走纯稠密检索（表设计文档§4） |

### 7.2 BaseConfidenceCalc（记忆置信度计算，F4.3）

| | |
|---|---|
| 所属Agent | 记忆体系通用（各Agent的`MemoryRecallMiddleware`调用，不归属单一对话Agent，风控置信度不复用本工具，见§6.2） |
| 入参 | `base: float`（来源初始权重，需求文档§5.4.1表）、`evidence_count: int`、`conflict_count: int`、`age_days: int` |
| 出参 | `{confidence: float}`，公式：`clamp((base + min(evidence_count×0.05, 0.3) - conflict_count×0.1) × max(0, 1-age_days/365×0.2), 0, 1)` |

### 7.3 FinalConfidenceRank（记忆综合重排，F4.3）

| | |
|---|---|
| 所属Agent | 记忆体系通用 |
| 入参 | `candidates: [{content: str, semantic_score: float, confidence: float, age_days: int, scenario_weight: float}]` |
| 出参 | `{ranked: [{content: str, final_score: float}]}`，公式：`0.4×语义相关性 + 0.3×置信度 + 0.15×timeliness(exp(-age_days/180)) + 0.15×场景权重`（需求文档§5.4.1，权重为团队拟定示例值） |

### 7.4 GraphQuery（GraphRAG查询）

| | |
|---|---|
| 所属Agent | 投顾助手Agent |
| 入参 | `customer_id: int`、`depth: int?`（默认2跳）、`query_intent: str?`（自然语言，如"行业分散度"，用于生成Cypher的意图提示） |
| 出参 | `{nodes: [...], edges: [...], diversity_score: float}` |
| 实现要点 | 参照`nl2cypherAgent.py`的ReAct双工具模式重写为查询方向（该文件原实现是知识抽取写入，方向相反，需求文档§2.7已核实） |

### 7.5 NL2SQL

| | |
|---|---|
| 所属Agent | 数据分析Agent |
| 入参 | `natural_language_query: str` |
| 出参 | `{sql: str, columns: [str], rows: [[...]], interpretation: str, rejected: bool, reject_reason: str?}` |
| 实现要点 | 仅允许SELECT，正则+表/字段白名单拒绝DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE，结果限100行（需求文档§8.2） |

### 7.6 NL2API（Function Calling参数提取）

| | |
|---|---|
| 所属Agent | 业务操作Agent |
| 入参 | `natural_language_instruction: str` |
| 出参 | `{intent: str, extracted_params: dict, missing_params: [str]?}`（`missing_params`非空时需向用户追问，不进入执行分支） |

### 7.7 RiskRuleMatch

| | |
|---|---|
| 所属Agent | 风控监测Agent |
| 入参 | `customer_id: int`、`rule_scope: [str]`（规则编号列表，如`["RW-001"]`或12条日批/周批全集）、`trigger_source: enum[event\|scheduler]` |
| 出参 | `{triggered_rules: [{rule_id: str, weight_tier: float, priority: int}], alert_level: enum[蓝\|黄\|红], confidence: float, is_repeat: bool}` |
| 实现要点 | 逐规则回查`fin_transaction`等源表按§5.2触发条件判定，`confidence`公式见需求文档§5.4.2；不维护派生Redis计数器状态，天然幂等（架构设计文档ADR-3） |

### 7.8 ProfileExtract

| | |
|---|---|
| 所属Agent | 智能客服Agent（对话中抽取）、投顾/业务操作Agent（画像重算时可复用同一抽取逻辑） |
| 入参 | `conversation_text: str`、`customer_id: int` |
| 出参 | `{extracted_units: [{tag: str, content: str, info_type: enum[fact\|opinion], source: "AI从对话中提取", confidence: 0.60}]}`（初始置信度固定0.60，见需求文档§5.4.1来源权重表） |

### 7.9 SuitabilityCheck

| | |
|---|---|
| 所属Agent | 投顾助手Agent、业务操作Agent（共享同一实现） |
| 入参 | `customer_id: int`、`product_id: int` |
| 出参 | `{passed: bool, reason: str, requires_disclosure: bool, position_limit_pct: float?, admission_tier: enum[可执行\|仅预约]}` |
| 实现要点 | 硬匹配矩阵+`fm_flags`熔断标记联合校验，读取`fin_customer_profile.fm_flags`做强制拦截（需求文档§5.3第九条"不可人工绕过"，风控Agent写入/业务操作Agent读取的协作点，见《研判规则提取与落地方案.md》§3.3） |

### 7.10 MemoryValidator（记忆单元六维校验，F4.2）

| | |
|---|---|
| 所属Agent | 记忆体系通用，`ProfileExtract`输出写入`memory_units`前调用 |
| 入参 | `memory_unit: {tag, content, info_type, confidence, source, create_time, update_time, valid_until?}` |
| 出参 | `{valid: bool, violations: [str]}` |
| 校验维度 | 枚举值/数值范围/时间逻辑/来源合法性/标签唯一性/内容格式，六维规则见需求文档§5.4.3 |

---

## 8. 验收标准总对照表

| Agent | 需求文档功能编号 | 本文档章节 |
|---|---|---|
| 智能客服Agent | F1.3 | §2.4 |
| 投顾助手Agent | F3.2/F3.3 | §3.5 |
| 数据分析Agent | F2.3 | §4.4 |
| 业务操作Agent | F3.4 | §5.6 |
| 风控监测Agent | F4.1 | §6.4 |

Phase权重与加减分项见需求文档§9.2，不在本文档重复。

---

## 9. 变更记录

| 日期 | 变更内容 | 责任人 |
|---|---|---|
| 2026-08-13 | 首版：通用规范（System Prompt骨架、AgentResult约定）+ 5个Agent逐一的意图分类/处理函数映射表/二次确认状态机完整设计 + 10个内部Tool入参出参Schema + 验收标准自查对照表 | （待填） |
| 2026-08-13 | 跨文档一致性修正：§5.4二次确认状态机终态命名统一为需求文档§2.6/架构设计文档ADR-4已定的"执行"（此前误写成"已执行"，两份文档三处已用"执行"，本文档单独改了字面值，会导致Redis `status`枚举值实现时对不上） | （待填） |
| 2026-08-13 | 跨文档口径审计后两处修正：①§6.1触发入口表沿用了需求文档等既有文档"5条实时/准实时+15条日批/周批"的旧划分，与需求文档§5.2规则表本身对RW-011/014/015的标注（实时/实时/准实时）矛盾，核实所需字段均已存在于`fin_transaction`/`base_user`后改为"8条实时/准实时+12条日批/周批"，§7.7`RiskRuleMatch`入参说明同步；②§5.1`suspicious_report`行补充说明该权限已扩展授予理财顾问/客户经理（与需求文档§3.3同步，此前仅风控专员持有该权限与本节"该意图服务对象为理财顾问/客户经理"矛盾） | （待填） |
