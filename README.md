# 智能财富管家系统（Intelligent Wealth Butler）

面向金融机构的智能财富管理多 Agent 系统。课程组队答辩项目，4 天 vibe coding 工期，复用既有 Python/FastAPI 脚手架，通过 AI 编码 agent（Codex 写代码、Claude Code 做 review）完成开发。

## 项目简介

系统以 5 个 Agent 为核心，通过 Redis Streams 事件总线协作，覆盖"咨询-推荐-交易-风控"完整业务链：

| Agent | 职责 |
|---|---|
| 智能客服 Agent | RAG 知识问答、5 类意图、低置信转人工工单 |
| 投顾助手 Agent | GraphRAG 图谱增强推荐、客户画像、适当性匹配 |
| 风控监测 Agent | 20 条规则引擎（8 条实时/准实时 + 12 条日批/周批）、三层记忆置信度体系 |
| 数据分析 Agent | NL2SQL 数据查询（含表名字段白名单安全校验） |
| 业务操作 Agent | NL2API 8 种业务操作 + 二次确认状态机（申购>1万 / 转账>5万） |

## 技术栈

FastAPI（后端）+ MySQL / Redis / Milvus / Neo4j / MinIO（Docker 容器）+ Qwen / DeepSeek LLM（外部 API）+ Streamlit（演示前端）。后端 5 个 Agent 运行在同一个 FastAPI 进程内，APScheduler 承载日批/周批任务。

## 文档导航（docs/）

| 文档 | 用途 |
|---|---|
| 《智能财富管家系统-项目需求文档.md》 | 功能需求、RBAC 矩阵、事件格式、验收标准（最高权威） |
| 《架构设计文档.md》 | 逻辑架构图、ADR 决策记录、部署视图、代码目录落点 |
| 《表设计文档.md》 | MySQL 10 张业务表结构 |
| 《API接口设计文档.md》 | REST 接口契约、权限 |
| 《Agent设计文档.md》 | 5 个 Agent 的 System Prompt、意图分类、工具 schema |
| 《业务流程说明.md》 | 端到端业务流程与事件时序 |
| 《开发计划.md》 | 4 天任务分工、Day1~4 清单（团队每天必读） |
| 《Vibe Coding协作规范.md》 | AI 编码流程、编码/测试/合并规范、git 协作（团队每天必读） |

完整清单见 `docs/` 目录，共 14 份文档，均维护版本号与变更记录。

## 仓库内容

- `docs/`：团队产出的 14 份设计文档
- `.claude/skills/`：10 个 AI 编码规范 skills（编码/注释/测试/合并/review/提示词/脚手架复用/文档一致性/版本管理）
- `公司业务/` `公司信息/` `金融政策/`：RAG 知识库业务素材
- `用户测试数据/`：客户 A（高净值）/ 客户 B（普通投资者）测试样本
- `用户研判规则/`：反洗钱、投资者风险画像研判规则（风控规则引擎依据）

## 快速开始（团队成员）

1. 克隆仓库（仓库地址见协作者通知）
2. 先读 `docs/开发计划.md` 和 `docs/Vibe Coding协作规范.md`
3. 环境准备：启动 Docker 容器（MySQL/Redis/Milvus/Neo4j/MinIO）+ 配置 LLM API Key，见《开发计划》Day1
4. 开发流程：Codex 写代码 → 各人合并到 main → Claude Code 统一 review

## 开发流程约定

- Codex 写代码、Claude Code 在代码合并后统一 review
- 单 `main` 分支，VS Code GUI 操作，push 前先 pull，冲突找总负责人处理
- 详细规范见《Vibe Coding协作规范.md》与 `.claude/skills/`

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|---|---|---|---|
| v1.0 | 2026-08-14 | 首版发布，作为远程仓库入口说明 | （待填） |
