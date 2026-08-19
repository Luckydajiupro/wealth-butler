# Phase 5 数据重建交接说明

## 当前状态

- 项目入口：`app/WealthButler/main.py`
- 服务端口：`8010`
- 当前浏览器页面：`/chat/advisor`
- 代码已经完成客服回执、客户风险测评入口、投顾客户权限范围、投顾客户姓名展示等 Phase 5 功能修复。
- 数据库当前实际行数没有完成最终盘点。此前通过脚本直连 MySQL 时被本机网络策略阻断：`192.168.110.106:3306` 返回 `WinError 10013`。
- 因此，不要假设旧客户种子已经清理，也不要假设正式种子已经完整写入。

## 已修改的关键代码

- `app/WealthButler/Api/holdingsApi.py`
  - 客户收益、交易、持仓、通知接口。
  - 无有效风险测评时，产品接口返回 409，不再伪造 C1。
- `app/WealthButler/Api/advisorApi.py`
  - 普通理财顾问只看负责客户或自己领取的工单客户。
  - 超级管理员才可以看全部客户。
- `app/WealthButler/Agent/customerServiceAgent.py`
  - 增加风险测评意图和 `open_risk_assessment` 前端动作。
- `app/WealthButler/Frontend/pages/customer_dashboard.html`
  - 风险测评弹窗、未评估强制入口、客服回执轮询。
- `app/WealthButler/Frontend/pages/advisor_dashboard.html`
  - 显示客户业务范围；姓名缺失时不再显示内部客户 ID。
- `app/WealthButler/Api/riskApi.py`
  - 客户资料缺失时不再把客户 ID/用户名当姓名展示。
- `scripts/seed_wealthbutler_business_data.py`
  - 正式 MySQL 业务种子：180 客户、30 员工、55 产品及画像、风评、持仓、交易、预警、工单等。
  - 客户展示名是中文化名；账号如 `wb_seed_customer_001` 只用于内部自然键。
  - 使用 namespace `WB-SEED-20260817`，幂等插入，不覆盖非本 namespace 数据。
- `scripts/cleanup_legacy_customer_seed.py`
  - 只清理客户账号及客户关联业务记录。
  - 默认不连接数据库；`--connect-dry-run` 只预览；删除需要确认短语。
  - 不操作 `fin_product`、FAQ、产品问答、知识库表或 Milvus。

## 严禁使用的旧脚本

- `scripts/generate_supplement_data.py`
  - 旧逻辑会用 `random.randint(1, 150)` 猜客户 ID，可能生成孤儿工单和错误客户关联。
- `scripts/supplement_data_seed.sql`
  - 旧随机静态 SQL，不要再次导入。
- `scripts/init_wealth_butler_data.py`
  - 旧版 2 客户/少量产品演示种子，不要与正式种子混用。
- 任何 `clean_all_rag_data.py`、`clean_milvus.py`、`drop_v2_collections.py` 等脚本本次都不要执行。

## 建议的重建顺序

### 1. 先备份并盘点

至少记录以下表的总行数、客户关联行数和产品/知识表行数：

`base_user`、`base_user_role`、`fin_customer_profile`、`fin_risk_assessment`、`fin_holdings`、`fin_transaction`、`fin_risk_alert`、`biz_work_order`、`conversation_archive`、`base_llm_conversation`、`base_llm_session`、`fin_product`、`fin_knowledge_meta`。

同时记录 Milvus 集合名称和行数；不要删除已有集合或切片。

### 2. 只预览客户数据清理范围

```powershell
cd D:\lqh\金融
python scripts\cleanup_legacy_customer_seed.py --connect-dry-run
```

核对客户名单必须是旧演示客户或 `wb_seed_*` 客户，不能出现真实业务客户。

### 3. 只清理客户相关数据

```powershell
python scripts\cleanup_legacy_customer_seed.py --apply --confirm CLEANUP_LEGACY_CUSTOMER_DATA
```

该脚本不会删除产品、FAQ、知识库、问答或向量切片。无法确认归属的孤儿工单会保留并报告。

### 4. 写入正式 MySQL 业务种子

```powershell
python scripts\seed_wealthbutler_business_data.py --connect-dry-run
python scripts\seed_wealthbutler_business_data.py --apply --confirm APPLY_WB_SEED_20260817
python scripts\seed_wealthbutler_business_data.py --verify
```

正式种子会用真实化名填充 `base_user.extra_data.display_name`、客户画像和工单 `customer_name`。

### 5. Redis / MinIO 跨库场景

```powershell
python scripts\seed_cross_store_scenarios.py
python scripts\seed_cross_store_scenarios.py --apply
python scripts\seed_cross_store_scenarios.py --verify
```

该脚本只写入 `wb-seed:20260817` Redis 前缀、隔离 Stream、TTL 会话和 `wb-seed/20260817` MinIO 对象；不会 flush Redis，也不会删除业务键。

### 6. 向量库和图数据库

- 先检查集合状态：`python scripts/check_collections_status.py`。
- 不要运行清空/删除集合脚本。
- 如需补充知识，只使用 `seed_vector_graph_data.py` 或项目已有的增量 ingestion 流程，并确认脚本没有 `drop_collection`、`flushdb` 或全量 delete。
- 现有 FAQ、产品问答和准确切片必须保留；重建客户 MySQL 数据不应触碰 Milvus。

## 验收重点

1. 客户登录后无有效风评时先进入风险测评；完成后才能看产品和申购。
2. 风险等级显示为 C1-C5，收益率最多两位小数。
3. 总资产页面能看到该客户持仓配置结构、产品名称、金额和占比。
4. 投顾普通账号只看到自己负责/领取的客户，管理员看到全部客户。
5. 工单有 `customer_id`、`customer_name` 和业务摘要；孤儿工单不能自动猜客户。
6. 客服 Agent 能查询公司产品、风险等级和客户收益，不得把客户资料当成公司资料回复。
7. 产品表、FAQ、知识库元数据、Milvus 集合及切片的数量在重建前后保持不变或仅有明确的增量。

