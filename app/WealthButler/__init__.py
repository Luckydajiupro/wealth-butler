"""智能财富管家系统 - 业务模块

本模块为「智能财富管家系统」的核心业务实现，基于 Base 脚手架构建。

架构原则：
- Base/ 提供通用基础能力（认证、数据库、LLM、中间件），不轻易改动
- WealthButler/ 实现财富管家业务逻辑，依赖 Base 的基础设施
- 保持业务代码与基础设施的清晰边界

模块组成：
- Api/      业务 API 接口层（投顾、理财产品、资产配置等 RESTful 接口）
- Service/  业务服务层（业务逻辑封装、数据处理、外部服务调用）
- Models/   业务模型层（ORM 模型定义、数据库表映射）
- Agent/    智能 Agent 层（5 大智能体：客服、投顾、风险、配置、挖掘）
- Utils/    业务工具层（金融计算、数据转换等业务专用工具函数）

开发规范：
1. 复用 Base 能力：from Base.Client.mysqlClient import get_mysql_client
2. 业务路由注册：在 Base/main.py 中 include_router
3. 配置管理：扩展 Base/Config/setting.py 或使用独立配置文件
4. 数据库迁移：在 Base/Models/migrations/ 添加表结构
"""

__all__ = []
