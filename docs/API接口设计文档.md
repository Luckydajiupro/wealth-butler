# 智能财富管家系统 — API接口设计文档

## 0. 文档说明

- 本文档是《智能财富管家系统-项目需求文档.md》§7.1"REST API清单"的**字段级展开**——该清单目前只有方法+路径，没有请求/响应体、没有权限标注、没有归属人，写法上与《表设计文档》"对需求文档做字段级展开"是同一模式。
- **分工原则**：本文档只定"范式层"——统一响应信封、认证方式、每个接口的请求/响应JSON Schema、RBAC权限要求、归属Agent。各Agent内部实现（Prompt设计、Function Calling工具链怎么串、具体业务逻辑）由对应负责人完成；已经在《表设计文档》/《研判规则提取与落地方案.md》/《架构设计文档》里拍板的规则，实现时直接引用，本文档不重复展开。
- **复用声明**：认证方式、响应信封、SSE帧格式全部直接复用脚手架已有实现（`Base/RicUtils/httpUtils.py`的`HttpResponse`、`Base/Api/authApi.py`的Bearer鉴权模式、`Base/Api/ai/chatApi.py`的流式响应模式），不新造一套格式——这是"能复用绝不重写"原则（架构设计文档§1）在API层的落地，也让新写的接口和直接复用的`/api/auth/*`风格一致，不增加前端联调的心智负担。
- 若本文档字段与《表设计文档》/《研判规则提取与落地方案.md》/《架构设计文档》出现不一致，以那几份为准，视为本文档需要同步修正的信号。

---

## 1. 全局范式（统一约定，逐接口不再重复）

### 1.1 响应信封

成功响应直接复用脚手架`HttpResponse.ok(data, msg)`，FastAPI按对象`__dict__`序列化为：

```json
{"status_code": 200, "data": {...}, "msg": "success."}
```

失败响应复用FastAPI原生`HTTPException(status_code, detail)`，序列化为：

```json
{"detail": "错误原因"}
```

两种响应体结构不统一，是脚手架`authApi.py`的既有实现（全篇如此），本项目跟随而非新发明一套——减少新写接口和直接复用的`/api/auth/*`之间的风格割裂。

### 1.2 认证与RBAC

- 复用`Base/Api/authApi.py`的`POST /api/auth/login`，登录成功返回`access_token`；之后所有接口走`Authorization: Bearer {token}` + `HTTPBearer`依赖注入，复用`_get_current_user`/`_require_permission`模式，鉴权失败401，权限不足403。
- 客户与员工共用同一套JWT体系，区分靠`base_user.user_type`；员工进一步按`base_user_role`关联的权限字符串做细粒度校验（对齐需求文档§3.3的11个业务权限），本文档每个写操作接口都标注所需权限标识。
- **客户端只能访问** `/api/chat/customer`、`/api/chat/session/{id}/history`（仅本人）、`GET /api/profile/{customer_id}`（仅本人，且只返回客户可见字段子集，见§2.3说明）、`POST /api/profile/{customer_id}/assessment`（仅本人发起16题问卷）；其余接口全部要求员工身份+对应权限——这是需求文档§2.1"客户仅智能客服Agent一个入口"在API层的落地。画像本身**没有面向客户的PUT接口**：`fin_customer_profile`是评估流程/规则引擎的计算产物，不是客户可编辑的资料（客户联系方式属于`base_user`，走`PUT /api/operation/contact`，权限是`customer:info_update`即客户经理专属，不是客户本人）。
- 需求文档§3.3的11个业务权限未覆盖"知识库管理""图谱查看""管理员操作"这几类接口，本文档复用脚手架已有的通用权限`Permission.SYSTEM_CONFIG`（`authApi.py`菜单管理已在用）承载，不再新增权限字符串——理由与《研判规则提取与落地方案.md》"能不新建就不新建"一致，避免为低频管理类接口扩大权限矩阵。

### 1.3 分页

统一`limit`（默认20）/`offset`（默认0）查询参数，响应体固定包裹`{items: [...], total, limit, offset}`（复用`authApi.py list_users`已有写法）。

### 1.4 对话类接口统一结构

请求体（`/api/chat`统一入口 + 4个直连入口共用）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 用户输入 |
| `customer_id` | int | 视场景 | 员工代客户操作时必填（投顾/业务操作/客服转介场景），客户本人对话时可从Token解出不必传 |
| `session_id` | string | 否 | 不传则新开会话，对应Redis `session:{id}:messages` |
| `agent_type` | enum | 仅`/api/chat`必填 | `customer\|advisor\|analyst\|operator`，编排层按此分发（ADR-6，不含风控——风控不走对话范式） |
| `is_stream` | bool | 否，默认`true` | 是否SSE流式输出 |

非流式响应体是`BaseAgent.run()`返回的`AgentResult`（`Base/Ai/base/baseAgent.py`已定义）包一层`HttpResponse.ok`：

```json
{
  "status_code": 200,
  "data": {
    "success": true,
    "output": "回答正文",
    "tool_calls": [{"name": "KnowledgeRetrieval", "args": {...}, "result": "..."}],
    "iterations": 2,
    "duration_ms": 1200,
    "token_usage": {"prompt_tokens": 500, "completion_tokens": 120},
    "metadata": {}
  },
  "msg": "success."
}
```

流式（`is_stream=true`）：`StreamingResponse(media_type="text/event-stream")`，帧格式复用`chatApi.py`已有约定`data: {chunk}\n\n`，`chunk`为JSON字符串：

```json
{"type": "content|reasoning|tool_call|done", "content": "..."}
```

`type=tool_call`是本项目新增的帧类型（脚手架原版只有`content`/`reasoning`两种），因为客服/投顾/业务操作Agent都有Function Calling中间态，前端需要展示"正在检索政策库…"这类过程提示；`type=done`帧收尾，携带本轮`tool_calls`/`duration_ms`。

### 1.5 时间/金额/枚举序列化约定

- `DECIMAL`字段（金额/份额/评分）序列化为**字符串**，不用JS float精度不可靠的number，如`"risk_score": "78.50"`。
- `DATETIME`字段序列化为ISO 8601字符串，如`"2026-08-13T10:30:00"`。
- `ENUM`字段原样透传《表设计文档》定义的中文值，如`"risk_level": "C3"`、`"alert_level": "黄"`，不转数字code，减少前端一层映射表维护成本。

### 1.6 错误约定

| HTTP状态码 | 场景 |
|---|---|
| 400 | 请求参数校验失败、业务规则拒绝（如C1客户申购R4产品被适当性红线拒绝，需求文档§8.2） |
| 401 | 未登录/Token失效 |
| 403 | 已登录但无权限（RBAC角色不匹配） |
| 404 | 资源不存在 |
| 422 | FastAPI/Pydantic自动参数校验失败（框架自动产生，无需手写） |
| 500 | 未预期异常 |

---

## 2. 分接口契约

对齐需求文档§7.1清单逐条展开；每条给出方法+路径、所需权限、请求体、响应体、归属Agent/负责人。

### 2.1 对话类

| 接口 | 权限 | 请求体 | 响应体 | 归属 |
|---|---|---|---|---|
| `POST /api/chat` | 登录用户（`agent_type`对应权限在分发后由具体Agent二次校验） | §1.4通用结构，`agent_type`必填 | §1.4通用结构 | 编排层（ADR-6，轻量分发，不做多跳） |
| `POST /api/chat/customer` | 客户本人 或 员工代客户 | §1.4通用结构（不需要`agent_type`） | §1.4通用结构 | 智能客服Agent负责人 |
| `POST /api/chat/advisor` | `product:recommend`（理财顾问） | 同上，`customer_id`必填 | 同上 | 投顾助手Agent负责人 |
| `POST /api/chat/analyst` | `data:nl2sql_query`（全体员工） | 同上，无需`customer_id` | 同上，`metadata.generated_sql`携带生成的SQL供审计（需求文档§8.2 NL2SQL安全要求） | 数据分析Agent负责人 |
| `POST /api/chat/operator` | 按识别出的具体意图动态校验（`operation:purchase`等，入口不做统一前置拦截） | 同上，`customer_id`必填 | 同上；若命中二次确认（ADR-4），额外返回`metadata.confirm_required=true`、`metadata.confirm_token`、`metadata.pending_action`（待确认方案摘要） | 业务操作Agent负责人 |
| `POST /api/chat/operator/confirm`（**补充接口**，见§4） | 与原操作相同权限 | `{"confirm_token": "string", "action": "confirm\|cancel"}` | `action=confirm`时执行并返回`fin_transaction`记录；`action=cancel`时状态机回退，返回确认取消 | 业务操作Agent负责人 |
| `GET /api/chat/session/{session_id}/history` | 本人 或 对应员工 | query: `limit/offset` | `conversation_archive`条目列表（`role/content/tool_calls/created_at`） | 通用（走`conversation_archive`表，不归属单一Agent） |

> `GET /api/chat/stream`（需求文档§7.1原列出的独立SSE端点）**建议不单独实现**，理由见§4"删除项"。

### 2.2 知识库

| 接口 | 权限 | 请求体/参数 | 响应体 | 归属 |
|---|---|---|---|---|
| `POST /api/knowledge/upload` | `SYSTEM_CONFIG`（业务管理员，见§1.2） | multipart文件 + `{knowledge_type: FAQ\|产品说明\|政策法规, title, source_file}` | 新建`fin_knowledge_meta`记录（`status=待入库`），异步触发《RAG切片入库策略.md》流水线，响应`{id, status}` | 知识库入库流水线负责人 |
| `POST /api/knowledge/search` | `SYSTEM_CONFIG`（管理端手动检索验证用，非对话检索——对话检索走各Agent内部`KnowledgeRetrieval`工具，不经此REST） | `{query, knowledge_type, top_k}` | Milvus检索命中列表（`content/score/source_file`） | 同上 |
| `GET /api/knowledge/list` | `SYSTEM_CONFIG` | query: `knowledge_type/status` + 分页 | `fin_knowledge_meta`列表 | 同上 |
| `DELETE /api/knowledge/{id}` | `SYSTEM_CONFIG` | — | 软下线：`fin_knowledge_meta.status=已下线`（《RAG切片入库策略.md》§5下线流程，不物理删除Milvus向量） | 同上 |

### 2.3 画像

| 接口 | 权限 | 请求体 | 响应体 | 归属 |
|---|---|---|---|---|
| `GET /api/profile/{customer_id}` | 本人 或 `product:query`（理财顾问/客户经理/风控专员） | — | **按调用方身份返回不同字段子集**（见下方说明），只读，无对应PUT接口 | 投顾助手Agent负责人（画像计算引擎归属处） |
| `GET /api/profile/assessment/questions`（**补充接口**，见§4） | 登录用户皆可 | — | 16题题库（题号/题干/选项/分值），供前端渲染问卷表单；数据来源见下方说明 | 同上 |
| `POST /api/profile/{customer_id}/assessment` | 客户本人 或 `risk:reassess`（理财顾问代客户） | `{"answers": [{"question_no": 1, "option": "A", "score": 5}, ...]}`（16题，需求文档§5.1） | 新建`fin_risk_assessment`记录 + 联动重算`fin_customer_profile`四维度分与`risk_level` | 同上 |

> **`GET /api/profile/{customer_id}`的字段可见性分层**（本文档写作时发现的设计问题，见§4）：`fin_customer_profile`把"客户该知道的画像结果"和"风控内部计算过程/推断记录"存在同一行里，不能不加区分地整行返回。
> - **客户本人可见**：`risk_level`、`valid_until`（引用自`fin_risk_assessment`）、`asset_allocation`、`product_preference`。
> - **仅员工（`product:query`）可见，客户不可见**：`fm_flags`（FM-01~05熔断标记——一旦客户看到自己被标记为身份异常/异常交易熔断，等同变相告知其正被重点监控，与反洗钱"不得打草惊蛇"的合规精神冲突）、`dimension1~4_score`/`risk_score`/`confidence_score`（打分方法论细节暴露给客户会让后续风评问卷失去甄别效力）、`memory_units`（AI对客户的行为/偏好推断记录，内容主观、供内部个性化推荐使用，不适合作为"结论"直接展示给被评估对象）、`updated_reason`（内部审计字段）。
> - 实现方式：Service层查出整行后按调用方角色做字段级过滤，不新建两张视图表。

> **题库存放位置**：16题原文+选项+分值来自《个人投资者适当性管理指南.md》第三章（第八条/第九条），是静态参考数据（不因客户而变、无复杂计算逻辑），不新建MySQL表——与《研判规则提取与落地方案.md》§1"规则定义不落库"是同一决策框架。整理成`risk_assessment_questions.json`配置文件，由`GET /api/profile/assessment/questions`读取返回；`fin_risk_assessment.answers`只存**客户作答结果**，不存题库本身，两者不重复。

### 2.4 产品

| 接口 | 权限 | 请求体/参数 | 响应体 | 归属 |
|---|---|---|---|---|
| `GET /api/product/list` | `product:query`（员工） | query: `product_type/risk_level/status/keyword` + 分页 | `fin_product`列表 | 通用（直查MySQL，不归属单一Agent） |
| `GET /api/product/{id}` | `product:query` | — | 单条`fin_product`详情 | 同上 |
| `POST /api/product/recommend` | `product:recommend`（理财顾问） | `{"customer_id": int}` | 结构化推荐列表（非自然语言，供前端"一键推荐"按钮），每项含`product_id/score/reason`，内部复用投顾助手Agent的融合排序+多因子排序工具链（架构设计文档§8.2），但不经过`ReActAgent`对话范式 | 投顾助手Agent负责人 |

### 2.5 业务操作

| 接口 | 权限 | 请求体 | 响应体 | 归属 |
|---|---|---|---|---|
| `POST /api/operation/purchase` | `operation:purchase`（理财顾问） | `{"customer_id", "product_id", "amount"}` | 未触发二次确认：直接返回`fin_transaction`记录；触发（>1万，需求文档§8.2）：返回`confirm_token`（走§2.1的`/confirm`接口闭环） | 业务操作Agent负责人 |
| `POST /api/operation/redeem` | `operation:redeem` | `{"customer_id", "product_id", "shares"}` | 同上 | 同上 |
| `POST /api/operation/transfer` | `operation:transfer`（客户经理） | `{"customer_id", "amount", "counterparty_account", "counterparty_name"}` | 未触发二次确认：直接返回`fin_transaction`；触发（>5万，需求文档§8.2）：返回`confirm_token` | 同上 |
| `PUT /api/operation/contact` | `customer:info_update` | `{"customer_id", "phone"?, "email"?}` | 更新后的`base_user`联系方式字段 | 同上 |

> 两层准入结构（公募/标准化可一键执行 vs 私募/资管仅预约+资格初核，需求文档§5.1）由业务操作Agent内部在生成方案阶段判断，体现在响应体的`metadata.admission_tier`字段（`可执行\|仅预约`），不是独立接口。

### 2.6 风控

| 接口 | 权限 | 请求体/参数 | 响应体 | 归属 |
|---|---|---|---|---|
| `POST /api/risk/monitor` | `SYSTEM_CONFIG`（供演示手动触发一次规则扫描；正常生产路径是事件驱动/定时任务自动触发，不经此REST，见ADR-3） | `{"customer_id"?, "rule_codes"?}`（均可选，不传则全量扫描） | 本次触发新增的`fin_risk_alert`列表 | 风控监测Agent负责人 |
| `GET /api/risk/alerts` | `risk:override`（风控专员） | query: `alert_level/status/customer_id` + 分页 | `fin_risk_alert`列表 | 同上 |
| `PUT /api/risk/alert/{id}/handle` | `risk:override` | `{"status", "is_false_positive"?, "handle_note"?}` | 更新后的`fin_risk_alert`（`handled_by`取当前登录员工ID，`handled_at`取当前时间） | 同上 |

### 2.7 工单

| 接口 | 权限 | 请求体/参数 | 响应体 | 归属 |
|---|---|---|---|---|
| `POST /api/workorder` | `workorder:create`（客户经理，手动创建场景；客服Agent识别转人工意图/风控Agent命中规则时是内部直接写库，不经此REST，见ADR-5） | 对齐`biz_work_order`字段：`{"order_type", "customer_id", "intent_summary"?, "priority"?}` | 新建`biz_work_order`记录 | 通用（复用`work_order_tool`工具外壳） |
| `GET /api/workorder/list` | 按`order_type`区分可见范围：`客户转介`→客户经理，`风控处置`→风控专员，`其他`→业务管理员 | query: `order_type/status/customer_id` + 分页 | `biz_work_order`列表 | 同上 |
| `PUT /api/workorder/{id}` | 同上（按`order_type`对应角色） | `{"status", "handled_by"?}` | 更新后的`biz_work_order` | 同上 |

### 2.8 图谱

| 接口 | 权限 | 请求体/参数 | 响应体 | 归属 |
|---|---|---|---|---|
| `GET /api/graph/stats` | `SYSTEM_CONFIG` | — | 节点/关系计数统计（按标签/类型分组，供答辩展示图谱规模） | 投顾助手Agent负责人（GraphQuery工具归属处） |
| `GET /api/graph/visualization/{customer_id}` | `product:query`（理财顾问） | query: `depth`（默认2跳） | 以该客户为中心的子图`{nodes: [...], edges: [...]}`，供前端力导向图渲染 | 同上 |

### 2.9 管理

| 接口 | 权限 | 请求体 | 响应体 | 归属 |
|---|---|---|---|---|
| `POST /api/admin/recalculate-confidence` | `SYSTEM_CONFIG`（业务管理员） | `{"customer_id"?}`（不传则全量批量重算） | `{"affected_count": int}`，按§5.4.1公式重算`fin_customer_profile.confidence_score` | 投顾助手Agent负责人（画像置信度计算归属处） |

### 2.10 认证

`POST /api/auth/login`、`POST /api/auth/register`等**直接复用**脚手架`Base/Api/authApi.py`既有实现，不新写。唯一需要补充的业务含义：`login`响应体里的`roles`字段决定前端登录后跳转到哪个工作台（客户→客服对话页；员工按`employee_role`跳对应Agent工作台，见《表设计文档》§1.1）。

---

## 3. 内部Tool清单

需求文档§7.2已列出10个内部Tool（`MemoryValidator`/`BaseConfidenceCalc`/`FinalConfidenceRank`/`KnowledgeRetrieval`/`GraphQuery`/`NL2SQL`/`NL2API`/`RiskRuleMatch`/`ProfileExtract`/`SuitabilityCheck`），均继承脚手架`BaseTool`，`to_openai_schema()`自动生成Function Calling schema——这些是Agent**内部**调用的工具，不对外暴露REST，不在本文档展开契约，由对应Agent负责人在实现时定义每个工具的入参/出参（工具级别的接口设计留给负责人，是本文档"范式vs实现"分工的具体体现，见§0）。

---

## 4. 与需求文档§7.1的差异说明（本文档写作时发现的开放项）

- **补充接口**：`POST /api/chat/operator/confirm`。ADR-4定义了"待确认→已确认→执行"状态机，但需求文档§7.1原清单没有列出让用户"确认"的接口——没有这个接口，状态机无法闭环（生成方案后永远停在"待确认"）。本文档在§2.1补齐，需要在需求文档§7.1同步这一条（未直接改需求文档正文，先记录在此，避免本文档单方面偏离需求文档口径）。
- **设计修正**：`GET /api/profile/{customer_id}`原方案是客户本人可整行读取、员工可整行读写，重新审视后发现`fin_customer_profile`混装了"客户该知道的结果"（`risk_level`等）和"风控内部计算过程"（`fm_flags`/各维度分/`memory_units`等），客户不应看到后者；同时PUT接口本身没有存在必要（画像是计算产物，不是用户可编辑资料）。已改为只读接口+按角色返回字段子集，去掉PUT，详见§2.3表格上方说明。
- **补充接口**：`GET /api/profile/assessment/questions`。需求文档§7.1只列了提交问卷的`POST .../assessment`，没有"前端怎么拿到16题题目"这一环——16题原文/选项/分值已在《个人投资者适当性管理指南.md》第三章中现成给出，整理成`risk_assessment_questions.json`配置文件（不建表，理由同《研判规则提取与落地方案.md》§1），本文档在§2.3补齐读取接口。
- **建议删除**：`GET /api/chat/stream`。脚手架`chatApi.py`的既有模式是流式与非流式共用同一个POST端点，靠请求体`is_stream`字段区分（§1.4），没有独立GET端点。若单独实现一个GET SSE端点，浏览器原生`EventSource`只能发GET不能带`Authorization`请求头，还需要额外做Token-in-URL的鉴权变通，为4天工期增加不必要的复杂度；前端用`fetch()`读取流式响应体即可满足演示需求，不依赖原生`EventSource`。建议这条从需求文档§7.1清单移除，或明确保留但降级为"暂不实现"。
- **权限矩阵未覆盖项**：知识库管理、图谱查看、管理员重算这几类接口，需求文档§3.3的11个业务权限没有对应项，本文档复用脚手架已有的`SYSTEM_CONFIG`通用权限承载（§1.2），未新增权限字符串。

---

## 5. 变更记录

| 日期 | 变更内容 | 责任人 |
|---|---|---|
| 2026-08-13 | 首版：对需求文档§7.1 REST API清单做字段级展开，定义统一响应信封/分页/对话类结构/SSE帧格式/序列化约定（§1），逐接口给出权限、请求体、响应体、归属Agent（§2），标注内部Tool清单分工边界（§3），发现并记录3处与需求文档的差异（§4：补充`/api/chat/operator/confirm`、建议删除独立SSE端点、知识库类权限复用SYSTEM_CONFIG） | （待填） |
| 2026-08-13 | 修正`GET/PUT /api/profile/{customer_id}`：取消客户PUT权限（画像是计算产物非用户可编辑资料），GET改为按调用方角色返回字段子集，客户不再能看到`fm_flags`/各维度分/`confidence_score`/`memory_units`等风控内部字段 | （待填） |
| 2026-08-13 | 补充`GET /api/profile/assessment/questions`：16题风评问卷题库（题干/选项/分值，来源《个人投资者适当性管理指南.md》第三章）需要单独的读取接口供前端渲染表单，不建MySQL表，走`risk_assessment_questions.json`配置文件，与提交结果的`fin_risk_assessment.answers`分工不重复 | （待填） |
| 2026-08-13 | 跨文档一致性修正：消歧§2.1/§2.4/§2.5中4处指代不清的"§8.2"引用（NL2SQL安全要求、二次确认阈值3处→改为"需求文档§8.2"；投顾助手融合排序工具链1处→改为"架构设计文档§8.2"，两份文档都有§8.2但内容不同） | （待填） |
