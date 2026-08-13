---
name: merge-standards
description: 智能财富管家系统的代码合并规范。涉及 git 提交、push、合并、冲突处理、.gitignore 配置时使用。团队多数不熟悉 git，采用最低操作门槛的单 main 分支方案。
---

# 代码合并规范

本规范是《Vibe Coding协作规范.md》§5 的落地。团队多数人不熟悉 git，因此采用最低操作门槛的方案，不引入 feature 分支。

## 1. 仓库与分支

- GitHub 私有仓库，李清华创建并将其余 5 人加为协作者（Settings → Collaborators）。
- 单一 `main` 分支，不开 feature 分支。配合《开发计划.md》§1 已按文件/模块分工到人，天然冲突面很小。

## 2. 工具与认证

- 用 VS Code 自带的 Git 面板（图形化 pull/commit/push），不用命令行。
- 认证用 HTTPS + GitHub 个人访问令牌（Personal Access Token），不用 SSH key。首次克隆输一次账号+粘贴 token，GUI 工具会记住凭证。

## 3. 铁律（务必遵守）

- 改动前先 pull 一次，push 前再 pull 一次。
- 只改自己负责的文件（对照《开发计划.md》§1 分工表），不要顺手改别人的文件。

## 4. 冲突应急预案

- 一旦 push 被拒绝、提示冲突，不要自己瞎点"合并"，截图现象直接找李清华处理。新手用错误方式解决冲突容易导致代码丢失。

## 5. 备份

- 李清华每天收工后在 GitHub 上打一个 tag（如 `day1-checkpoint`），作为当天回滚点，其他人不需要操作。

## 6. .gitignore

仓库根目录配 `.gitignore`，排除：

- `__pycache__/`
- 虚拟环境目录
- `.env`（API Key 等密钥文件改用 `.env.example` 模板提交，真实 `.env` 不入库）

## 7. 提交信息

- commit message 简洁说明"为什么改 + 改了哪块"，避免 `update`、`fix` 这类无信息量的提交信息。
- 一次提交只做一件事（对应 coding-standards 的"任务粒度要小"原则）。

## 8. 交付前自检

push 前确认：已 pull 最新代码、只改了自己的文件、`.gitignore` 已生效（没有把 `__pycache__`/`.env` 提交进去）、commit message 有意义。
