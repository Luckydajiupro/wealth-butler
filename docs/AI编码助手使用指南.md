# AI编码助手使用指南

> 本文档适用于所有团队成员使用任何AI编码助手（Claude Code、Cursor、GitHub Copilot、通义灵码等）开发本项目时的通用规范。

---

## 0. 为什么需要这个文档

本项目设置了多个skill（位于`.claude/skills/`），但这些skill只有Claude Code能直接识别。如果你使用其他AI编码工具（Cursor、Copilot、通义灵码等），需要**手动将本文档内容提供给AI**，确保它遵守项目规范。

**使用方法：**
1. 打开你的AI编码助手对话界面
2. 在开始编码前，将本文档内容粘贴给AI，或者用"@文件"功能引用本文档
3. 明确告诉AI："在本项目中编码时，必须严格遵守以上规范"

---

## 1. 编码规范（对应 skill: coding-standards）

### 1.1 复用优先原则

**关键规则：能复用绝不重写**

- 新写代码前，先确认脚手架 `D:\lqh\reproject\ric-train\ric-train\Base` 里是否已有可抄的类似模式
- **禁止引入脚手架没有的新框架/新ORM/新第三方库**（除非架构设计文档明确要求）

**参考模板：**
- 新业务表Model → 参照 `Base/Models/userModel.py`
- 新Agent → 参照 `Base/Ai/agents/nl2cypherAgent.py`、`Base/Ai/base/baseAgent.py`
- 新向量集合Model → 参照 `Base/Repository/examples/exampleVDBModel.py`
- 新Service → 参照 `Base/Service/authService.py`

### 1.2 文件落点规则

**11层架构**对应的代码目录（详见 `app/WealthButler/README.md`）：

| 内容 | 落点 | 示例 |
|---|---|---|
| MySQL业务表Model | `WealthButler/Models/` | `advisorModel.py` |
| Milvus集合入库 | `WealthButler/Knowledge/` | `ragIngestion.py` |
| Neo4j图谱构建 | `WealthButler/Knowledge/` | `graphBuilder.py` |
| 业务逻辑Service | `WealthButler/Service/` | `advisorService.py` |
| 5个Agent子类 | `WealthButler/Agent/` | `customerServiceAgent.py` |
| 10个Tool工具 | `WealthButler/Tools/` | `knowledgeRetrievalTool.py` |
| System Prompt模板 | `WealthButler/Prompts/` | `customerServicePrompts.py` |
| Agent中间件 | `WealthButler/Middleware/` | `memoryRecallMiddleware.py` |
| 事件总线 | `WealthButler/EventBus/` | `eventBus.py` |
| 风控规则引擎 | `WealthButler/Rules/` | `ruleEngine.py` |
| 业务工具函数 | `WealthButler/Utils/` | `financeCalc.py` |
| API接口 | `WealthButler/Api/` | `advisorApi.py` |

### 1.3 命名约定

- **数据库表**：统一前缀 `wealth_`（如 `wealth_advisor`）
- **Model类**：驼峰命名 + `Model`后缀（如 `AdvisorModel`）
- **Service类**：驼峰命名 + `Service`后缀（如 `AdvisorService`）
- **Agent类**：驼峰命名 + `Agent`后缀（如 `CustomerServiceAgent`）
- **Tool类**：驼峰命名 + `Tool`后缀（如 `KnowledgeRetrievalTool`）

### 1.4 禁止事项

❌ **禁止做的事：**
- 引入新的Web框架（已有FastAPI）
- 引入新的ORM（已有SQLAlchemy）
- 引入新的向量库客户端（已有pymilvus）
- 引入新的Agent框架（已有BaseAgent）
- 修改`Base/`脚手架目录下的代码
- 硬编码敏感信息（数据库密码、API密钥等，必须放`.env`）

---

## 2. 注释规范（对应 skill: comment-standards）

### 2.1 何时写注释

✅ **需要注释的场景：**
- 复杂的业务逻辑（如四维度画像打分算法）
- 非显而易见的设计决策（如"为什么用Streams不用Pub/Sub"）
- 临时性的workaround（必须标注TODO和原因）
- 外部API的关键参数说明

❌ **不需要注释的场景：**
- 显而易见的代码（如`user_id = 123`）
- 函数名已经说明用途的代码
- 重复Python类型注解的内容

### 2.2 注释格式

```python
# 单行注释：用中文，简洁描述为什么这样做

def calculate_risk_score(profile: dict) -> float:
    """计算客户风险评分（四维度加权）
    
    Args:
        profile: 客户画像数据，包含四个维度的分项得分
        
    Returns:
        综合得分（0-100分）→ C1-C5等级
        
    算法依据：
        需求文档§5.3 + 用户研判规则/投资者风险画像研判规则.md
        维度一25% + 维度二25% + 维度三30% + 维度四20%
    """
    # TODO(李清华): FM-01~05熔断规则待补充，当前仅计算加权分
    score = (
        profile['dimension1_score'] * 0.25 +
        profile['dimension2_score'] * 0.25 +
        profile['dimension3_score'] * 0.30 +
        profile['dimension4_score'] * 0.20
    )
    return score
```

---

## 3. 测试规范（对应 skill: testing-standards）

### 3.1 必须写测试的场景

✅ **必须写单元测试：**
- 风控规则引擎（20条规则的评估逻辑）
- 客户画像打分算法（四维度加权）
- NL2SQL安全校验层
- EventBus发布/消费逻辑

### 3.2 测试用例生成方式

使用 `test-case-generation` skill：
```python
# 测试文件命名：test_{模块名}.py
# 位置：与被测试文件同目录或统一tests/目录

import pytest
from WealthButler.Rules.ruleEngine import RuleEngine
from WealthButler.Rules.ruleDefinitions import RW_001

def test_rw001_large_cash_withdrawal():
    """测试RW-001：短期内大额现金存取"""
    context = {
        'cash_withdraw_7d': 150000,
        'cash_deposit_7d': 120000,
        'tx_time_night_ratio': 0.4
    }
    result = RuleEngine.evaluate_rule(RW_001, context)
    
    assert result['triggered'] == True
    assert result['confidence'] > 0.6
    assert 'cash_withdraw_7d' in [c['field'] for c in result['violated_conditions']]
```

### 3.3 运行测试

```bash
# 运行所有测试
pytest

# 运行特定模块测试
pytest tests/test_ruleEngine.py

# 查看覆盖率
pytest --cov=WealthButler --cov-report=html
```

---

## 4. 代码审查规范（对应 skill: code-review）

### 4.1 自检清单（提交前必查）

在提交代码前，AI助手应帮你检查：

- [ ] 是否复用了脚手架已有模式？
- [ ] 文件放置的目录层级是否正确？
- [ ] 是否引入了新的第三方库？（如是，是否在架构文档中有说明）
- [ ] 是否硬编码了敏感信息？
- [ ] 是否为关键逻辑编写了单元测试？
- [ ] 注释是否清晰解释了"为什么"而非"是什么"？
- [ ] API接口是否注册到`Base/main.py`？

### 4.2 常见问题

**❌ 错误示例：**
```python
# 错误1：引入新框架
from flask import Flask  # ❌ 项目用FastAPI，不能引入Flask

# 错误2：硬编码敏感信息
MYSQL_PASSWORD = "123456"  # ❌ 必须用.env

# 错误3：自创新ORM写法
class MyCustomORM:  # ❌ 必须继承BaseDBModel
    pass
```

**✅ 正确示例：**
```python
# 正确1：复用脚手架BaseDBModel
from Base.Repository.base.baseDBModel import BaseDBModel

class AdvisorModel(BaseDBModel):
    __tablename__ = 'wealth_advisor'
    
# 正确2：使用.env配置
from Base.Config.setting import get_setting
MYSQL_PASSWORD = get_setting().mysql_password

# 正确3：复用BaseAgent
from Base.Ai.base.baseAgent import BaseAgent

class CustomerServiceAgent(BaseAgent):
    pass
```

---

## 5. 脚手架复用指南（对应 skill: scaffold-reuse）

### 5.1 脚手架提供的能力

**Base层（`D:\lqh\reproject\ric-train\ric-train\Base`）已提供：**

- **数据库连接**：`Client/mysqlClient.py`、`Client/redisClient.py`、`Client/milvusClient.py`、`Client/neo4jClient.py`
- **LLM封装**：`Ai/llms/qwenLlm.py`、`Ai/llms/deepseekLlm.py`
- **Agent基座**：`Ai/base/baseAgent.py`、`Ai/base/baseTool.py`
- **认证授权**：`Service/authService.py`（JWT + RBAC）
- **中间件**：`Middleware/corsMiddleware.py`、`Middleware/loggingMiddleware.py`
- **工具函数**：`RicUtils/httpUtils.py`、`RicUtils/dateUtils.py`

### 5.2 如何复用

**步骤：**
1. 查看脚手架对应模块的示例代码
2. 复制代码结构到`WealthButler/`对应层级
3. 修改业务逻辑，保持框架调用方式不变

**示例：新建一个Service**
```python
# 参照：Base/Service/authService.py
from Base.Client.mysqlClient import get_mysql_client
from WealthButler.Models.advisorModel import AdvisorModel

class AdvisorService:
    @staticmethod
    def list_advisors(page: int = 1, page_size: int = 10):
        """查询投顾列表（复用Base的分页模式）"""
        db = get_mysql_client()
        # 这里的查询方式完全复制authService里的模式
        query = db.query(AdvisorModel).offset((page-1)*page_size).limit(page_size)
        return query.all()
```

---

## 6. 文档一致性（对应 skill: doc-consistency）

### 6.1 关键原则

**一个事实，一个来源**：
- 表结构 → 以`docs/表设计文档.md`为准
- API接口 → 以`docs/API接口设计文档.md`为准
- 架构设计 → 以`docs/架构设计文档.md`为准
- 风控规则 → 以`用户研判规则/`目录为准

### 6.2 冲突处理

如果代码与文档不一致：
1. **先问团队负责人**（李清华）
2. 以需求文档为最高权威
3. 修改后同步更新代码和文档

---

## 7. Git提交规范（对应 skill: merge-standards）

### 7.1 提交信息格式

```
<类型>: <简短描述>

<详细说明>（可选）

- 具体修改点1
- 具体修改点2
```

**类型：**
- `feat`: 新功能
- `fix`: 修复bug
- `refactor`: 重构
- `docs`: 文档修改
- `test`: 测试相关
- `chore`: 构建/工具配置

**示例：**
```
feat: 实现客户画像四维度打分算法

- 新增 Service/profileService.py
- 实现四维度加权计算（基础属性25% + 投资经验25% + 风险偏好30% + 行为异常20%）
- 新增 FM-01~05 熔断规则校验
- 单元测试覆盖率 85%
```

### 7.2 提交前检查

```bash
# 1. 查看修改内容
git status
git diff

# 2. 只提交相关文件（不要 git add .）
git add WealthButler/Service/profileService.py
git add tests/test_profileService.py

# 3. 提交
git commit -m "feat: 实现客户画像四维度打分算法"

# 4. 推送
git push origin main
```

---

## 8. 使用示例

### 8.1 使用Cursor开发时

```
你（对Cursor AI说）：
我要在本项目中开发客户画像打分Service，请先阅读以下规范：
@AI编码助手使用指南.md

然后帮我：
1. 检查脚手架Base/Service/里是否有可参考的Service模式
2. 在WealthButler/Service/目录下新建profileService.py
3. 实现四维度加权打分算法（需求文档§5.3）
4. 编写单元测试
5. 确保没有引入新的第三方库
```

### 8.2 使用通义灵码/GitHub Copilot时

```
你（对AI说）：
请遵守以下编码规范：
[粘贴本文档第1-7章全部内容]

现在帮我实现风控规则引擎，要求：
1. 参考Base/层的代码模式
2. 放在WealthButler/Rules/ruleEngine.py
3. 实现20条RW规则的评估逻辑
4. 不使用eval()，用安全的操作符映射
```

---

## 9. 常见问题 FAQ

### Q1: 我用的AI工具不支持@文件引用怎么办？
**A**: 手动复制本文档内容粘贴到对话框，或者在每次会话开始时说"请遵守《AI编码助手使用指南.md》中的规范"。

### Q2: AI生成的代码与规范不符怎么办？
**A**: 立即指出违反了哪条规范，要求AI重新生成。例如："你引入了pandas，但规范要求不能引入脚手架没有的库，请用现有库实现"。

### Q3: 规范太长，AI记不住怎么办？
**A**: 分步骤提问，每次只关注一条规范。例如先问"文件应该放在哪个目录"，再问"如何复用Base层的代码"。

### Q4: 发现本文档与其他文档冲突怎么办？
**A**: 以需求文档为准，联系李清华更新本文档。

---

## 10. 更新记录

| 日期 | 更新内容 | 更新人 |
|---|---|---|
| 2026-08-14 | 首版发布，整合12个skill内容为通用AI助手规范 | 李清华 |
