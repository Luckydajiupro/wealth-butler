# Conda 环境安装指南

## 环境创建与依赖安装（一次性执行）

```bash
# 1. 创建 Python 3.11 环境（wealth-butler 为环境名，可自定义）
conda create -n wealth-butler python=3.11 -y

# 2. 激活环境
conda activate wealth-butler

# 3. 安装依赖（在项目根目录执行）
cd D:\lqh\金融
pip install -r requirements.txt

# 4. 验证核心包
python -c "import pymilvus, redis, pymysql, neo4j, minio, fastapi; print('核心依赖已就绪')"
```

## 后续使用

每次新开终端需要激活环境：

```bash
conda activate wealth-butler
cd D:\lqh\金融\app
python main.py
```

## 代理问题修复（避免 Milvus/MinIO 连不上）

Windows 永久生效（执行后重启终端）：

```cmd
setx NO_PROXY "aetherheartpool.top,192.168.184.128,localhost,127.0.0.1"
```

临时生效（仅当前会话）：

```bash
# bash
export NO_PROXY="192.168.184.128,localhost,127.0.0.1"

# cmd
set NO_PROXY=192.168.184.128,localhost,127.0.0.1
```

## 已剔除的坑包说明

- `pathlib==1.0.1` — Python 3.x 内置 pathlib，装这个会冲突
- `fitz==0.0.1.dev2` — PyPI 空白包，真正的 fitz 模块由 PyMuPDF 提供（已在依赖中）

## 环境管理常用命令

```bash
# 列出所有环境
conda env list

# 删除环境（需要时）
conda env remove -n wealth-butler

# 导出环境（便于团队同步）
conda env export > environment.yml
```
