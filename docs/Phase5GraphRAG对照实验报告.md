# Phase 5 GraphRAG 对照实验报告

## 0. 修复后最终复测

已修复产品向量结果的 `metadata.product_code` 映射，并由图查询输出产品级分散度分数；
候选产品不再共享同一个图谱常数分。使用原查询和真实 MySQL、Milvus、Neo4j 只读复测：

| 数据集 | 纯RAG | GraphRAG | 变化 |
|---|---:|---:|---:|
| 受控业务事实 NDCG@3 | 0.9197 | 1.0000 | +0.0803 |
| 陈秀兰真实种子 NDCG@5 | 0.8700 | 1.0000 | +0.1300 |
| 王建国真实种子 NDCG@5 | 0.4900 | 1.0000 | +0.5100 |

真实题的相关性口径固定为：候选产品行业不在客户当前持仓行业中记2分、缺少行业记1分、
已有行业记0分。该结论只证明“行业分散”查询的增益，不外推到所有推荐意图。两位客户
均返回2行、2个行业的图谱证据，Top5 排名均发生变化，最终门禁为 **PASS**。

修复后机器结果：`runtime_artifacts/evaluation/graphrag-after-fix.json`。

## 1. 初次实验结论（保留作修复前基线）

本实验用同一查询比较纯RAG和GraphRAG，分为受控生产排序实验与真实存储观察。

| 实验 | 纯RAG | GraphRAG | 结论 |
|---|---:|---:|---|
| 固定业务事实 NDCG@3 | 0.9197 | 1.0000 | 提升0.0803 |
| 固定业务事实 MRR | 1.0000 | 1.0000 | 持平 |
| 真实陈秀兰种子排名 | Top5固定 | Top5相同 | 无排名变化 |
| 真实王建国种子排名 | Top5固定 | Top5相同 | 无排名变化 |
| 真实图谱解释证据 | 无 | 两位客户均返回2行、2个行业 | 解释性增强 |

当前可以证明：生产融合排序在收到产品级图信号时能够提高固定题集的相关性，真实
Neo4j 查询也能增加持仓行业解释证据。但尚不能声称“真实生产 GraphRAG 的推荐相关性
优于纯RAG”，严格验收项仍为 **未闭环**。

机器可读结果：`runtime_artifacts/evaluation/graphrag-latest.json`。

## 2. 实验设计

固定查询为“客户科技行业持仓集中，请推荐有助于分散风险的产品”。受控实验使用
生产 `AdvisorService.rank_products()`，纯RAG与GraphRAG共享相同客户风评、候选产品、
向量分和TopK，只改变图谱产品分。人工相关性标签只奖励非科技行业且适当性通过的
产品，使用 NDCG@3、MRR 和排名差异计分。

真实存储实验对陈秀兰（C1）和王建国（C4）使用同一查询、同一候选和同一生产排序，
只读 MySQL、Milvus、Neo4j，不更新任何业务数据。真实题集当前没有人工产品级相关性
标注，因此只记录图谱查询成功、证据数量和排序差异，不虚构NDCG。

## 3. 生产差距

1. `AdvisorService.retrieve_vector_scores()` 请求 Milvus 返回 `product_code`，但当前
   `fin_product_collection` schema 没有这个顶层字段，真实运行报
   `field product_code not exist`，服务随后降级为空分数。产品编码实际位于集合的
   metadata/正文时，需要按现有 schema 取回并解析，或通过受控迁移增加字段；不能
   直接假设字段存在。
2. `GraphQueryTool._normalize_rows()` 只返回整体 `graph_score/diversity_score`，没有
   生成 `product_scores`。`AdvisorService.rank_products()` 在缺少产品级图分时，把同一个
   整体图分应用给全部候选，加入常数不会改变候选相对顺序。因此真实A/B虽然增加了
   解释证据，排名必然相同或主要由非图谱因子决定。

闭环建议：先修复产品向量结果与 Milvus schema 的映射，再让 GraphQuery 返回可追溯的
产品级分散度/行业关联分 `product_scores`；为陈秀兰、王建国各建立至少5个候选产品的
人工相关性标注，重新计算 NDCG@3。只有真实数据 NDCG 严格提升，才能把需求文档中的
“GraphRAG优于纯RAG”标记为通过。

## 4. 复现命令

```powershell
python scripts/evaluation_graphrag.py --with-storage `
  --output runtime_artifacts/evaluation/graphrag-latest.json

python -m pytest -q -p no:cacheprovider tests/test_evaluation_graphrag.py
```

脚本中的真实路径只执行 `SELECT`、Milvus检索和只读Cypher，不执行图谱或业务数据写入。
