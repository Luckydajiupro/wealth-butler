# Phase 5 固定题集准确率评测报告

## 0. 修复后最终复测

使用同一固定题集和项目 `.env` 中的 `deepseek-v4-flash` 重新执行，未修改题目或
标准答案。修复内容仅包括 NL2API Prompt 的规范字段契约和评测器对外部模型无效 JSON
的失败计分/单次重试。

| 指标 | 修复前 | 修复后 | 需求门槛 | 最终结论 |
|---|---:|---:|---:|---|
| 客服意图分类 | 100.00% | 100.00% | >=80% | 通过 |
| 客服真实RAG证据命中 | 88.89% | 88.89% | >=80% | 通过 |
| NL2SQL语义与安全校验 | 100.00% | 80.00% | >=80% | 通过（边界值） |
| Operator意图识别 | 100.00% | 100.00% | >80% | 通过 |
| Operator参数抽取 | 26.09% | 100.00% | >90% | 通过 |

最终总门禁为 **PASS**。NL2SQL 本轮有2题因模型未生成可解析 SQL 而失败，准确率恰好
达到门槛，仍属于交付风险，不能据此宣称稳定高于80%。修复后机器结果：
`runtime_artifacts/evaluation/accuracy-live-after-fix.json`。

## 1. 初次评测结论（保留作修复前基线）

评测日期：2026-08-17。正式模型为项目 `.env` 已配置的 `deepseek-v4-flash`。
评测只生成分类、SQL 和业务参数候选；NL2SQL 不连接执行器，Operator 不调用
APIExecutor，因此不会执行查询或产生申购、赎回、转账、工单等业务写入。

| 指标 | 固定题数/字段数 | 结果 | 需求门槛 | 结论 |
|---|---:|---:|---:|---|
| 客服意图分类 | 18题 | 100.00% | 辅助指标 | 通过 |
| 客服真实RAG证据命中 | 9题 | 88.89% | >=80% | 通过 |
| NL2SQL语义与安全校验 | 10题 | 100.00% | >=80% | 通过 |
| Operator意图识别 | 16题 | 100.00% | >80% | 通过 |
| Operator参数抽取 | 23个字段 | 26.09% | >90% | **未通过** |

因此本轮固定题集总门禁为 **FAIL**。客服咨询的 88.89% 是“召回证据包含
标准答案关键词”的可重复指标，不等价于对最终自然语言回答逐字打分；最终回答
质量仍应在答辩人工演练中抽查。

## 2. 题集与计分

- 客服：覆盖产品、政策、FAQ、持仓、寒暄、转人工六类意图；真实RAG题覆盖
  FAQ、产品、政策三个 Milvus 集合。每题要求 Top5 有结果、Top1 达到生产阈值，
  且召回正文包含全部标准答案关键词。
- NL2SQL：覆盖客户画像、产品、交易、持仓、风评、预警、工单和用户表。SQL
  必须包含预期表/语义字段，并通过生产 `Nl2sqlGuard`；脚本不执行 SQL。
- Operator：覆盖8类业务意图。意图按整题计分，参数按标准答案声明的每个字段
  单独计分；生产 `NL2APITool` 归一化或白名单拒绝后的结果才作为最终参数结果。
- 指标不使用“注入标准答案后再计算准确率”的做法。`contract` 模式仅作为确定性
  回归代理，其结果明确标记为 `deterministic_regression_proxy`，不能替代模型验收。

机器可读明细：

- `runtime_artifacts/evaluation/accuracy-live.json`
- `runtime_artifacts/evaluation/accuracy-contract-storage.json`

## 3. 失败分析

Operator 的16题意图全部正确，但23个标准参数仅6个通过生产归一化。主要原因是
`LLMIntentParser` 提示词只规定 `extracted_params` 是对象，没有列出8类意图各自的
合法字段名。模型因此输出 `product_code`、`product`、`account`、`payee`、
`payee_name` 等自然别名；`OperationInputPolicy` 按安全要求拒绝非白名单字段，整组
参数被 fail-closed 清空。这一安全行为正确，问题位于结构化抽取契约不足。

建议后续修复：在解析 Prompt 中直接注入 `INTENT_ALLOWED_PARAMS` 和各意图必填字段，
为金额、产品ID、对手方、工单、可疑上报分别提供一个 JSON few-shot；模型输出后仍
保留现有白名单归一化，不放宽安全策略。修复后必须用同一题集重新运行，不能修改
标准答案迎合模型输出。

另外，客服确定性降级规则仅为14/18（77.78%），容易把现金报告阈值、风评有效期、
申购确认和“持有哪些产品”误路由。在线模型当前为18/18，但模型不可用时降级体验
仍未达到80%，建议补充关键词或采用轻量确定性规则表后回归。

## 4. 复现命令

```powershell
python scripts/evaluation_accuracy.py --mode contract --with-storage `
  --output runtime_artifacts/evaluation/accuracy-contract-storage.json

python scripts/evaluation_accuracy.py --mode live --with-storage `
  --output runtime_artifacts/evaluation/accuracy-live.json

python -m pytest -q -p no:cacheprovider `
  tests/test_evaluation_accuracy.py tests/test_evaluation_graphrag.py
```

模型输出存在随机性。报告记录的是上述最终一次完整运行结果，机器明细保留每题
实际输出；后续正式验收建议至少重复3轮并报告均值与最差轮。
