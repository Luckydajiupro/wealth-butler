# 智能财富管家系统 - API接口文档

## 1. 认证说明

### 1.1 认证方式
系统采用JWT（JSON Web Token）认证机制。

### 1.2 获取Token
**接口**：`POST /api/auth/login`

**请求体**：
```json
{
  "username": "wb_seed_c1_elderly",
  "password": "<从环境变量安全注入的演示密码>"
}
```

**响应示例**：
```json
{
  "status_code": 200,
  "msg": "登录成功",
  "data": {
    "id": 1,
    "username": "wb_seed_c1_elderly",
    "source_module": "fin",
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "<已脱敏>",
    "roles": [],
    "permissions": [],
    "is_admin": false
  }
}
```

### 1.3 使用Token
在请求头中添加：
```
Authorization: Bearer <access_token>
```

### 1.4 Token过期
- **Access Token有效期**：30分钟（可在.env中配置）
- **刷新Token**：使用 `POST /api/auth/refresh` 接口

---

## 2. 对话接口

### 2.1 统一对话入口
**接口**：`POST /api/chat`

**描述**：按agent_type分发到对应Agent

**权限**：需要JWT认证

**请求体**：
```json
{
  "agent_type": "customer",
  "message": "我想了解一下货币基金",
  "session_id": "session_123",
  "user_id": 1,
  "customer_id": null,
  "is_stream": true
}
```

**参数说明**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agent_type | string | 是 | Agent类型：customer/advisor/analyst/operator |
| message | string | 是 | 用户消息内容 |
| session_id | string | 否 | 会话ID，不传则自动创建 |
| user_id | int | 是 | 当前登录用户ID |
| customer_id | int | 否 | 客户ID（advisor/operator必填） |
| is_stream | boolean | 否 | 是否流式输出，默认true |

**Agent类型说明**：
- `customer` - 智能客服（RAG知识库检索）
- `advisor` - 投顾助手（产品推荐、适当性匹配）
- `analyst` - 数据分析（NL2SQL）
- `operator` - 业务操作（NL2API、二次确认）

**响应格式（SSE流式）**：
```
data: 根据
data: 您的
data: 风险等级
data: ...
```

---

### 2.2 智能客服直连
**接口**：`POST /api/chat/customer`

**描述**：RAG知识库检索 + 会话记忆

**权限**：客户本人或员工代客户

**请求体**：
```json
{
  "message": "理财产品的风险等级是如何划分的？",
  "session_id": "customer_session_001",
  "user_id": 1,
  "is_stream": true
}
```

**功能特性**：
- 基于RAG的知识库检索
- 多轮对话记忆
- 支持金融产品、政策法规、业务流程查询

---

### 2.3 投顾助手直连
**接口**：`POST /api/chat/advisor`

**描述**：客户画像分析 + 产品推荐 + 适当性匹配

**权限**：理财顾问（product:recommend权限）

**请求体**：
```json
{
  "message": "推荐适合这位客户的产品",
  "session_id": "advisor_session_001",
  "user_id": 2,
  "customer_id": 1,
  "is_stream": true
}
```

**参数说明**：
- `customer_id` - 必填，指定服务的客户ID

**功能特性**：
- 客户画像分析（风险等级、资产配置）
- 基于风险匹配的产品推荐
- GraphRAG增强（知识图谱）
- 适当性校验

---

### 2.4 数据分析直连
**接口**：`POST /api/chat/analyst`

**描述**：自然语言转SQL查询

**权限**：全体员工（data:nl2sql_query权限）

**请求体**：
```json
{
  "message": "查询最近一个月申购金额超过10万的客户",
  "session_id": "analyst_session_001",
  "user_id": 2,
  "is_stream": true
}
```

**功能特性**：
- NL2SQL自动生成
- SQL安全校验（防止DROP/DELETE等危险操作）
- 结果自动格式化
- 支持统计、排名、趋势分析

---

### 2.5 业务操作直连
**接口**：`POST /api/chat/operator`

**描述**：自然语言业务操作（NL2API + 二次确认）

**权限**：理财顾问/客户经理

**请求体**：
```json
{
  "message": "帮客户申购XX货币基金5万元",
  "session_id": "operator_session_001",
  "user_id": 2,
  "customer_id": 1,
  "is_stream": true
}
```

**参数说明**：
- `customer_id` - 必填，仅员工代客户操作

**支持的业务操作**：
- 产品申购/赎回
- 转账操作
- 客户信息更新
- 风险评估重做
- 工单创建

**二次确认机制**：
- 申购金额 > 1万元
- 转账金额 > 5万元

**响应示例（需确认）**：
```json
{
  "type": "confirm_required",
  "content": "即将为客户张三申购XX货币基金50000元，请确认",
  "metadata": {
    "confirm_token": "token_abc123",
    "operation": "purchase",
    "amount": 50000
  }
}
```

---

### 2.6 业务操作二次确认
**接口**：`POST /api/chat/operator/confirm`

**描述**：确认或取消业务操作

**权限**：需要JWT认证

**请求体**：
```json
{
  "confirm_token": "token_abc123",
  "action": "confirm"
}
```

**参数说明**：
| 参数 | 类型 | 说明 |
|------|------|------|
| confirm_token | string | 待确认操作的token |
| action | string | confirm（确认）/ cancel（取消） |

**响应示例**：
```json
{
  "code": 0,
  "msg": "操作已确认并执行",
  "data": {
    "status": "success",
    "operation": "purchase",
    "result": "申购成功，交易ID：12345"
  }
}
```

---

### 2.7 会话历史查询
**接口**：`GET /api/chat/session/{session_id}/history`

**描述**：获取会话历史消息

**权限**：需要JWT认证

**请求参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话ID（路径参数） |
| limit | int | 返回最近N条记录，默认50 |

**响应示例**：
```json
{
  "code": 0,
  "msg": "查询成功",
  "data": [
    {
      "role": "user",
      "content": "我想了解货币基金",
      "timestamp": "2026-08-16 10:00:00"
    },
    {
      "role": "assistant",
      "content": "货币基金是风险等级最低的...",
      "timestamp": "2026-08-16 10:00:05"
    }
  ]
}
```

---

## 3. 风险预警接口

### 3.1 查询风险预警列表
**接口**：`GET /api/wealth/risk/alerts`

**描述**：查询风险预警列表，支持筛选

**权限**：
- 风控专员：查看所有预警
- 业务管理员：仅查看需要裁决的高风险预警

**请求参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| status | string | 状态筛选：待处理/处理中/已确认/误报 |
| alert_level | string | 风险级别：低/中/高/严重 |
| need_override | boolean | 是否需要管理员裁决 |
| limit | int | 每页数量，默认20，最大100 |
| offset | int | 偏移量，默认0 |

**响应示例**：
```json
{
  "code": 0,
  "msg": "查询成功",
  "data": {
    "alerts": [
      {
        "id": 1,
        "alert_type": "RULE_AML_01",
        "alert_name": "短期大额现金交易",
        "alert_level": "高",
        "customer_id": 5,
        "customer_name": "customer0005",
        "transaction_amount": 150000.00,
        "trigger_reason": "单笔现金交易超15万",
        "triggered_at": "2026-08-16 09:30:00",
        "status": "待处理",
        "confidence": 0.92,
        "need_override": true,
        "handler_id": null,
        "handled_at": null
      }
    ],
    "total": 10
  }
}
```

---

### 3.2 查询单个预警详情
**接口**：`GET /api/wealth/risk/alert/{alert_id}`

**描述**：查询风险预警详细信息

**权限**：风控专员或业务管理员

**响应示例**：
```json
{
  "code": 0,
  "msg": "查询成功",
  "data": {
    "id": 1,
    "alert_type": "RULE_AML_01",
    "alert_name": "短期大额现金交易",
    "alert_level": "高",
    "customer_id": 5,
    "customer_name": "customer0005",
    "trigger_reason": "单笔现金交易超15万",
    "trigger_details": {
      "reason": "单笔现金交易超15万",
      "threshold": 150000,
      "actual_amount": 200000
    },
    "triggered_at": "2026-08-16 09:30:00",
    "status": "待处理",
    "confidence": 0.92,
    "need_override": true,
    "handler_id": null,
    "handler_name": null,
    "handled_at": null,
    "handle_result": null,
    "related_transaction": {
      "id": 1234,
      "transaction_type": "现金存入",
      "amount": 200000.00,
      "transaction_time": "2026-08-16 09:00:00",
      "counterparty_account": null,
      "counterparty_name": null,
      "status": "成交"
    }
  }
}
```

---

### 3.3 处理风险预警
**接口**：`PUT /api/wealth/risk/alert/{alert_id}/handle`

**描述**：处理风险预警（状态流转）

**权限**：
- 风控专员：process/confirm/mark_false
- 业务管理员：override_approve/override_reject

**请求体**：
```json
{
  "action": "process",
  "remark": "已核实客户身份，正在调查资金来源"
}
```

**action说明**：
| 操作 | 权限 | 状态流转 | 说明 |
|------|------|----------|------|
| process | 风控专员 | 待处理→处理中 | 开始处理预警 |
| confirm | 风控专员 | 处理中→已确认 | 确认风险存在 |
| mark_false | 风控专员 | 处理中→误报 | 标记为误报 |
| override_approve | 管理员 | →误报 | 管理员批准放行 |
| override_reject | 管理员 | →已确认 | 管理员确认拦截 |

**响应示例**：
```json
{
  "code": 0,
  "msg": "预警已标记为处理中"
}
```

---

### 3.4 风险统计数据
**接口**：`GET /api/wealth/risk/stats`

**描述**：获取风险预警统计数据

**权限**：风控专员或业务管理员

**响应示例**：
```json
{
  "code": 0,
  "msg": "查询成功",
  "data": {
    "today_total": 12,
    "pending_count": 5,
    "false_positive_rate": 15.5,
    "reported_count": 3
  }
}
```

**字段说明**：
- `today_total` - 今日预警总数
- `pending_count` - 待处理数量
- `false_positive_rate` - 误报率（近30天）
- `reported_count` - 已上报数量（已确认状态）

---

## 4. 持仓管理接口

### 4.1 查询客户持仓
**接口**：`GET /api/wealth/holdings`

**描述**：查询当前登录客户的持仓列表

**权限**：客户本人（从JWT解析customer_id）

**响应示例**：
```json
{
  "code": 0,
  "msg": "查询成功",
  "data": {
    "holdings": [
      {
        "id": 1,
        "product_id": 1,
        "product_name": "XX货币市场基金",
        "product_code": "HB001",
        "shares": 10000.0,
        "cost_amount": 10000.00,
        "current_value": 10500.00,
        "profit_loss": 500.00,
        "profit_ratio": 0.05
      }
    ],
    "total_value": 10500.00,
    "total_profit": 500.00
  }
}
```

**字段说明**：
- `shares` - 持有份额
- `cost_amount` - 成本金额
- `current_value` - 当前市值
- `profit_loss` - 浮动盈亏
- `profit_ratio` - 收益率（小数形式，0.05表示5%）

---

## 5. 工单管理接口

### 5.1 查询工单列表
**接口**：`GET /api/wealth/workorder/list`

**描述**：查询工单列表，根据角色自动筛选

**权限**：
- 理财顾问：筛选包含"申购/赎回/产品推荐"的客户转介工单
- 客户经理：筛选包含"转账/信息更新/工单"的客户转介工单
- 风控专员：筛选风险预警类工单
- 管理员：查看所有工单

**请求参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| order_type | string | 工单类型：客户转介/风险预警/信息变更/转账审核/其他 |
| status | string | 状态：待处理/处理中/已完成/已驳回 |
| keyword | string | 关键词搜索（在intent_summary中搜索） |
| limit | int | 每页数量，默认20 |
| offset | int | 偏移量，默认0 |

**响应示例**：
```json
{
  "code": 0,
  "msg": "查询成功",
  "data": {
    "workorders": [
      {
        "id": 1,
        "order_type": "客户转介",
        "customer_id": 5,
        "customer_name": "customer0005",
        "intent_summary": "申购XX产品，意向金额约10万",
        "status": "待处理",
        "priority": "普通",
        "handled_by": null,
        "handler_name": null,
        "handled_at": null,
        "completed_at": null,
        "remark": null,
        "created_at": "2026-08-16 10:00:00",
        "updated_at": "2026-08-16 10:00:00"
      }
    ],
    "total": 10
  }
}
```

---

### 5.2 创建工单
**接口**：`POST /api/wealth/workorder`

**描述**：创建新工单

**权限**：需要JWT认证

**请求体**：
```json
{
  "order_type": "客户转介",
  "customer_id": 5,
  "intent_summary": "申购XX产品，意向金额约10万",
  "priority": "普通"
}
```

**参数说明**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| order_type | string | 是 | 客户转介/风险预警/信息变更/转账审核/其他 |
| customer_id | int | 是 | 客户ID |
| intent_summary | string | 是 | 意向摘要/业务描述 |
| priority | string | 否 | 普通/紧急，默认普通 |

**响应示例**：
```json
{
  "code": 0,
  "msg": "工单创建成功",
  "data": {
    "id": 123
  }
}
```

---

### 5.3 更新工单状态
**接口**：`PUT /api/wealth/workorder/{workorder_id}`

**描述**：领取、完成或驳回工单

**权限**：需要JWT认证

**请求体**：
```json
{
  "action": "claim",
  "remark": "开始处理此工单"
}
```

**action说明**：
| 操作 | 状态流转 | 说明 |
|------|----------|------|
| claim | 待处理→处理中 | 领取工单 |
| complete | 处理中→已完成 | 完成工单 |
| reject | 处理中→已驳回 | 驳回工单 |

**响应示例**：
```json
{
  "code": 0,
  "msg": "工单领取成功"
}
```

---

### 5.4 查询工单详情
**接口**：`GET /api/wealth/workorder/{workorder_id}`

**描述**：查询单个工单详细信息

**权限**：需要JWT认证

**响应示例**：
```json
{
  "code": 0,
  "msg": "查询成功",
  "data": {
    "id": 1,
    "order_type": "客户转介",
    "customer_id": 5,
    "customer_name": "customer0005",
    "intent_summary": "申购XX产品，意向金额约10万",
    "status": "处理中",
    "priority": "普通",
    "handled_by": 2,
    "handler_name": "advisor001",
    "handled_at": "2026-08-16 10:30:00",
    "completed_at": null,
    "remark": "已联系客户，正在准备产品推荐方案",
    "created_at": "2026-08-16 10:00:00",
    "updated_at": "2026-08-16 10:30:00"
  }
}
```

---

## 6. 前端页面接口

### 6.1 登录页
**接口**：`GET /login`（`GET /` 同样返回登录页）

**描述**：财富管家系统登录页面

### 6.2 角色工作台
**实际固定路径**：
- `GET /chat/customer` - 客户工作台
- `GET /chat/advisor` - 理财顾问工作台
- `GET /chat/analyst` - 数据分析工作台
- `GET /chat/operator` - 客户经理工作台
- `GET /chat/risk` 或 `GET /risk_dashboard` - 风控工作台
- `GET /admin_dashboard` - 管理员工作台

---

## 7. 统一响应格式

### 7.1 成功响应
```json
{
  "status_code": 200,
  "msg": "操作成功",
  "data": { }
}
```

### 7.2 错误响应
```json
认证、参数校验等 FastAPI 异常按 HTTP 状态返回，响应通常包含 `detail`；业务层使用 `HttpResponse.error` 时返回 `status_code`、`msg`、`data`。
```

### 7.3 常见错误码
| HTTP状态 | 说明 |
|------|------|
| 200 | 成功 |
| 400 | 请求参数或业务前置条件不满足 |
| 401 | 未授权（Token无效或过期） |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 8. 接口限流

系统集成SlowAPI限流中间件：
- **默认限制**：100次/分钟
- **超限响应**：HTTP 429 Too Many Requests

---

## 9. 在线API文档

启动服务后访问：
- **Swagger UI**：http://localhost:8010/docs
- **ReDoc**：http://localhost:8010/redoc

支持在线调试和参数说明查看。

---

## 10. 运行时 OpenAPI 路由基线

以下清单由 `app/WealthButler/main.py` 注册后的 OpenAPI schema 核对，当前共 64 个路径、69 个 HTTP 操作。请求模型、响应模型和授权细节以运行时 `/docs` 为准。

### 10.1 认证与权限（23 个操作）

- `POST /api/auth/login`、`POST /api/auth/refresh`、`POST /api/auth/register`
- `GET /api/auth/me`、`PUT /api/auth/me`、`POST /api/auth/change-password`
- `GET /api/auth/users`、`PUT /api/auth/users/status`、`POST /api/auth/users/reset-password`
- `GET /api/auth/users/{user_id}/roles`
- `GET /api/auth/roles`、`POST /api/auth/roles`、`PUT /api/auth/roles/permissions`
- `POST /api/auth/roles/grant`、`POST /api/auth/roles/revoke`、`POST /api/auth/roles/set`
- `GET /api/auth/permissions`
- `GET /api/auth/menus`、`POST /api/auth/menus`、`PUT /api/auth/menus/sort`
- `PUT /api/auth/menus/{menu_id}`、`DELETE /api/auth/menus/{menu_id}`
- `GET /api/auth/me/menus`

### 10.2 Agent 对话与会话（8 个操作）

- `POST /api/chat`
- `POST /api/chat/customer`
- `POST /api/chat/advisor`
- `POST /api/chat/analyst`
- `POST /api/chat/operator`
- `POST /api/chat/operator/confirm`
- `GET /api/chat/session/{session_id}/history`
- `POST /api/wealth/chat`

### 10.3 Operator 与合规写接口（8 个操作）

- `POST /api/operation/purchase`
- `POST /api/operation/redeem`
- `POST /api/operation/transfer`
- `PUT /api/operation/contact`
- `POST /api/compliance/evidence`
- `POST /api/compliance/evidence/{evidence_id}/revoke`
- `POST /api/compliance/payees/verify`
- `POST /api/compliance/payees/{payee_id}/revoke`

所有资金类操作必须通过员工认证、RBAC、适当性与二次确认；私募产品只能预约，不得一键成交。

### 10.4 财富业务只读与受控写接口（19 个操作）

- 风控：`GET /api/wealth/risk/alerts`、`GET /api/wealth/risk/alert/{alert_id}`、`PUT /api/wealth/risk/alert/{alert_id}/handle`、`GET /api/wealth/risk/stats`、`GET /api/wealth/risk/trend`
- 持仓：`GET /api/wealth/holdings`、`GET /api/wealth/holdings/profit-today`
- 工单：`GET /api/wealth/workorder/list`、`POST /api/wealth/workorder`、`GET /api/wealth/workorder/{workorder_id}`、`PUT /api/wealth/workorder/{workorder_id}`
- 投顾：`GET /api/wealth/advisor/clients`、`GET /api/wealth/advisor/stats`
- 分析：`GET /api/wealth/analyst/history`、`GET /api/wealth/analyst/query-history`、`GET /api/wealth/analyst/statistics`、`GET /api/wealth/analyst/profile/{customer_id}`、`GET /api/wealth/analyst/risk-assessment/questionnaire`、`POST /api/wealth/analyst/risk-assessment/submit`

### 10.5 页面与诊断（11 个操作）

- `GET /`、`GET /login`
- `GET /chat/customer`、`GET /chat/advisor`、`GET /chat/analyst`、`GET /chat/operator`、`GET /chat/risk`
- `GET /risk_dashboard`、`GET /admin_dashboard`
- `GET /auth-test`、`GET /superpowers`

以上五组共 69 个 HTTP 操作；由于同一路径可同时注册 GET/POST 或 PUT/DELETE，因此对应 64 个唯一 OpenAPI 路径。
