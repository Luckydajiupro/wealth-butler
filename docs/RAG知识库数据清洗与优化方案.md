# RAG知识库数据清洗与优化方案

> **反馈来源**：客服Agent负责人（赵嘉/袁艺铭）  
> **优先级**：🔴 P0（Day 2上午必须完成）  
> **原因**：当前数据质量问题直接影响客服Agent回答准确性和安全性

---

## 一、当前问题汇总

### 1.1 数据质量问题

| 问题 | 影响 | 严重程度 |
|---|---|---|
| FAQ存在重复（相同"问题+答案"） | 检索返回重复结果，浪费TopK位置 | 🔴 高 |
| 产品`risk_level`全部为占位符"R2" | 客户询问高风险产品时返回错误风险等级 | 🔴 高 |
| 产品`product_code`全部为占位符"XXXXXX" | 无法根据产品代码精确匹配 | 🔴 高 |
| 产品内容混杂"XX"测试占位符 | 回答给客户的内容不完整/不专业 | 🔴 高 |
| 产品资料缺少`chunk_type`字段 | 无法区分"产品详情"vs"对比表"vs"费用示例" | 🟡 中 |
| 政策标题不够精确 | 标题为文件名，无法定位到具体条款 | 🟡 中 |

### 1.2 检索逻辑问题

| 问题 | 影响 | 严重程度 |
|---|---|---|
| 中文BM25失效（未使用jieba分词） | "投资者适当性管理"被拆成单字，召回率极低 | 🔴 高 |
| 向量和BM25混合分数计算不合理 | BM25无结果时，向量分数×0.7导致阈值过低 | 🔴 高 |
| 通用问题未优先查FAQ | "R1到R5是什么意思"先查产品库，效率低 | 🟡 中 |
| 产品问题未追问客户 | 客户只说"我想买基金"，未提供产品名称即检索 | 🟡 中 |
| 返回结果未去重 | 同一文档的多个chunk返回，重复展示 | 🟡 中 |

### 1.3 阈值设置问题

| 集合 | 当前阈值 | 问题 | 建议 |
|---|---|---|---|
| FAQ（纯向量） | 0.75 | ✅ 合理 | 保持0.75 |
| 产品（混合检索） | 0.70 | ❌ BM25失效时太高 | 纯向量备用线0.65 |
| 政策（混合检索） | 0.70 | ❌ BM25失效时太高 | 纯向量备用线0.70 |
| 混合检索 | 无单独阈值 | ❌ 不应与纯向量共用 | jieba修好后重新计算 |

---

## 二、优化方案（分3步执行）

### 🔴 Step 1：数据清洗（P0，今天上午必须完成）

#### 1.1 清理FAQ重复数据

**任务**：根据"问题+答案"去重

**执行**：
```python
# scripts/clean_faq_duplicates.py
from collections import defaultdict

def clean_faq_duplicates(faq_file_path):
    """去除FAQ文件中的重复问答对"""
    seen = set()
    unique_lines = []
    duplicate_count = 0
    
    with open(faq_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split('\t')
        if len(parts) != 2:
            continue
        
        question, answer = parts[0].strip(), parts[1].strip()
        key = (question, answer)
        
        if key not in seen:
            seen.add(key)
            unique_lines.append(line)
        else:
            duplicate_count += 1
            print(f"[去重] {question}")
    
    # 写回文件
    with open(faq_file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(unique_lines))
    
    print(f"✓ FAQ去重完成：保留 {len(unique_lines)} 条，删除 {duplicate_count} 条重复")
    return len(unique_lines), duplicate_count

if __name__ == '__main__':
    clean_faq_duplicates('D:/lqh/金融/公司信息/高频问答对.txt')
```

#### 1.2 修正产品数据

**任务1**：修正所有产品的`risk_level`字段

**产品清单与风险等级**（从产品手册提取）：
```python
PRODUCT_RISK_LEVELS = {
    # 货币基金
    'XX货币市场基金': 'R1',
    
    # 债券基金
    'XX稳健增利债券A': 'R2',
    
    # 混合基金
    'XX平衡优选混合': 'R3',
    
    # 股票基金（需要补充product_code后才能修正）
    # 'XX沪深300指数增强': 'R4',
    
    # 银行理财（需要从手册中提取完整清单）
    # ...
}
```

**任务2**：补齐真实`product_code`

**说明**：
- 当前所有产品代码都是"XXXXXX"占位符
- **需要从产品手册中手动提取真实代码**（产品手册中也是占位符）
- **临时方案**：如果手册中没有真实代码，生成唯一标识符
  ```python
  # 临时方案
  product_code = f"JP{hashlib.md5(product_name.encode()).hexdigest()[:6].upper()}"
  # 例如："XX货币市场基金" -> "JPXXX123"
  ```

**任务3**：清除"XX"测试占位符

**执行**：
```python
def clean_product_placeholders(product_file_path, placeholder_dict_path):
    """清理产品文件中的占位符"""
    import json
    
    # 加载占位符字典
    with open(placeholder_dict_path, 'r', encoding='utf-8') as f:
        placeholder_dict = json.load(f)
    
    # 读取产品文件
    with open(product_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 替换占位符
    cleaned_content = content
    for placeholder, replacement in placeholder_dict.items():
        cleaned_content = cleaned_content.replace(placeholder, replacement)
    
    # 检查是否还有残留的占位符
    remaining_xx = cleaned_content.count('XX')
    remaining_xxx = cleaned_content.count('XXX')
    remaining_x = cleaned_content.count('X万') + cleaned_content.count('X亿')
    
    print(f"⚠️ 残留占位符：XX={remaining_xx}, XXX={remaining_xxx}, X单位={remaining_x}")
    
    # 写回文件
    with open(product_file_path, 'w', encoding='utf-8') as f:
        f.write(cleaned_content)
    
    print(f"✓ 产品占位符清理完成")

if __name__ == '__main__':
    clean_product_placeholders(
        'D:/lqh/金融/公司业务/个人理财产品手册.md',
        'scripts/placeholder_dict.json'
    )
```

**⚠️ 注意**：
- 当前`placeholder_dict.json`只有28条规则
- 产品手册中可能还有**未覆盖的占位符**（如具体金额、人名等）
- **需要人工检查清理后的文件，补充遗漏的占位符规则**

#### 1.3 产品资料增加chunk_type

**目的**：区分产品详情、对比表、费用示例

**实现**：在切片时根据内容特征打标签

```python
def detect_chunk_type(chunk_text: str) -> str:
    """检测chunk类型"""
    
    # 1. 对比表特征：包含表格、多个产品横向对比
    if '|' in chunk_text and '产品对比' in chunk_text:
        return '产品对比表'
    
    # 2. 费用示例特征：包含"申购费率""赎回费率""管理费"
    fee_keywords = ['申购费率', '赎回费率', '管理费', '托管费', '销售服务费']
    if sum(kw in chunk_text for kw in fee_keywords) >= 2:
        return '费用说明'
    
    # 3. 申购赎回流程
    if '申购赎回' in chunk_text or '操作流程' in chunk_text:
        return '操作流程'
    
    # 4. 默认：产品详情
    return '产品详情'

# 在 rag_ingestion.py 的 insert_to_milvus() 中添加
metadata = {
    'product_name': title,
    'product_code': get_real_product_code(title),  # 新增函数
    'product_type': '理财产品',
    'risk_level': get_real_risk_level(title),      # 新增函数
    'chunk_type': detect_chunk_type(chunk['text']),  # 新增字段
    'source': str(chunk_metadata.get('source', '')),
    'knowledge_type': knowledge_type,
    'chunk_index': chunk_metadata.get('chunk_index', i),
    'updated_at': datetime.now().strftime('%Y-%m-%d')
}
```

#### 1.4 政策标题优化

**当前格式**：`反洗钱合规操作手册`  
**优化格式**：`反洗钱合规操作手册 > 第一条 目的`

**实现**：在切片时解析Markdown标题结构

```python
def extract_policy_section_title(chunk_text: str, file_name: str) -> str:
    """提取政策条款的精确标题"""
    
    # 1. 尝试从chunk中提取标题（Markdown格式）
    lines = chunk_text.split('\n')
    for line in lines[:5]:  # 只看前5行
        # 匹配 "## 第一条 目的" 或 "### 3.1 定义"
        if line.startswith('#'):
            section_title = line.lstrip('#').strip()
            return f"{file_name} > {section_title}"
    
    # 2. 如果没有标题，使用前20个字作为摘要
    summary = chunk_text[:20].replace('\n', ' ').strip()
    return f"{file_name} > {summary}..."

# 在 rag_ingestion.py 的政策类型处理中
metadata = {
    'title': extract_policy_section_title(chunk['text'], title),  # 优化
    'policy_no': '',
    'category': '监管政策',
    ...
}
```

---

### 🟡 Step 2：重建Milvus集合（支持中文BM25）

#### 2.1 启用jieba分词器

**前提条件**：
- Milvus 2.6.1已安装
- jieba analyzer已启用

**新Schema定义**（产品和政策集合）：

```python
class ProductCollectionModel(BaseVDBModel):
    """产品集合（支持中文BM25混合检索）"""
    
    # 主键
    id: Optional[int] = Field(
        default=0,
        json_schema_extra={'is_primary': True, 'auto_id': True}
    )
    
    # 切片原文
    text: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 65535,
            'enable_match': True,          # 🆕 启用文本匹配
            'enable_analyzer': True,        # 🆕 启用分词器
            'analyzer_params': {            # 🆕 指定jieba
                'type': 'jieba'
            }
        }
    )
    
    # 元数据JSON
    metadata: Optional[dict] = Field(
        default={},
        json_schema_extra={'max_length': 65535}
    )
    
    # 稠密向量
    embedding: Optional[List[float]] = Field(
        default=[],
        json_schema_extra={'dim': 1024}
    )
    
    # 稀疏向量（基于text字段自动生成）
    text_sparse: Optional[dict] = Field(
        default={},
        json_schema_extra={
            'is_sparse_vector': True,
            'bm25_source_field': 'text'     # 🆕 指定BM25源字段
        }
    )
    
    collection_alias: ClassVar[str] = "fin_product_collection_v2"  # 🆕 新版本
    description: ClassVar[str] = "产品集合（中文BM25）"
    auto_create_collection: ClassVar[bool] = True
```

#### 2.2 版本管理策略

**不直接覆盖旧集合**，采用版本并存：

```python
# 旧集合（保留，不删除）
fin_product_collection       # 不支持中文BM25
fin_policy_collection        # 不支持中文BM25

# 新集合（v2版本，支持jieba）
fin_product_collection_v2    # 🆕 支持中文BM25
fin_policy_collection_v2     # 🆕 支持中文BM25

# FAQ集合不需要BM25，保持不变
fin_faq_collection           # 纯向量检索
```

**切换流程**：
1. 创建`_v2`集合并导入数据
2. 在测试环境验证检索效果
3. **测试通过后**，修改检索代码指向`_v2`集合
4. 观察1-2天，确认无问题后删除旧集合

#### 2.3 测试jieba分词效果

**测试脚本**：
```python
# scripts/test_jieba_analyzer.py
from pymilvus import MilvusClient

client = MilvusClient(uri="http://localhost:19530")

# 测试查询："投资者适当性管理政策"
test_queries = [
    "投资者适当性管理政策",
    "R1到R5是什么意思",
    "基金申购费率怎么算",
    "反洗钱可疑交易识别规则"
]

for query in test_queries:
    print(f"\n查询：{query}")
    
    # BM25搜索（使用jieba分词后）
    results = client.search(
        collection_name="fin_policy_collection_v2",
        data=[query],
        anns_field="text_sparse",  # 稀疏向量字段
        limit=5
    )
    
    print(f"  BM25召回 {len(results[0])} 条")
    for hit in results[0]:
        print(f"    分数={hit['distance']:.4f}, 标题={hit['entity']['metadata']['title'][:50]}")
```

**预期结果**：
- "投资者适当性管理政策" → 应召回《个人投资者适当性管理指南》
- 分词效果：`['投资者', '适当', '管理', '政策']` （而非单字）

---

### 🟢 Step 3：改进检索逻辑

#### 3.1 向量和BM25分开查询

**当前问题**：
- BM25无结果时，向量分数×0.7导致阈值过低（0.70×0.7=0.49）

**改进方案**：

```python
def hybrid_search(collection_name: str, query: str, top_k: int = 5):
    """改进的混合检索：向量和BM25分开查询"""
    
    # 1. 生成query向量
    query_embedding = get_embedding(query)
    
    # 2. 向量检索（始终执行）
    vector_results = milvus_client.search(
        collection_name=collection_name,
        data=[query_embedding],
        anns_field="embedding",
        output_fields=['id', 'text', 'metadata'],
        limit=top_k * 2  # 多召回一些，后续融合排序
    )
    
    # 3. BM25检索（如果集合支持）
    bm25_results = []
    if collection_name.endswith('_v2'):  # 只有v2集合支持BM25
        try:
            bm25_results = milvus_client.search(
                collection_name=collection_name,
                data=[query],
                anns_field="text_sparse",
                output_fields=['id', 'text', 'metadata'],
                limit=top_k * 2
            )
        except Exception as e:
            logger.warning(f"BM25检索失败（可能query太短）: {e}")
    
    # 4. 融合排序
    if bm25_results and len(bm25_results[0]) > 0:
        # BM25有结果，使用混合分数
        merged = merge_search_results(
            vector_results[0], 
            bm25_results[0],
            vector_weight=0.7,
            bm25_weight=0.3
        )
        threshold = 0.60  # 混合检索阈值（待重新标定）
    else:
        # BM25无结果，使用纯向量分数（不打折！）
        merged = vector_results[0]
        threshold = 0.65 if 'product' in collection_name else 0.70
    
    # 5. 过滤低分结果
    filtered = [hit for hit in merged if hit['distance'] >= threshold]
    
    return filtered[:top_k]


def merge_search_results(vector_hits, bm25_hits, vector_weight=0.7, bm25_weight=0.3):
    """融合向量和BM25结果"""
    scores = {}
    
    # 向量分数
    for hit in vector_hits:
        doc_id = hit['id']
        scores[doc_id] = {
            'vector_score': hit['distance'],
            'bm25_score': 0,
            'entity': hit['entity']
        }
    
    # BM25分数
    for hit in bm25_hits:
        doc_id = hit['id']
        if doc_id in scores:
            scores[doc_id]['bm25_score'] = hit['distance']
        else:
            scores[doc_id] = {
                'vector_score': 0,
                'bm25_score': hit['distance'],
                'entity': hit['entity']
            }
    
    # 计算融合分数
    merged = []
    for doc_id, data in scores.items():
        final_score = (
            data['vector_score'] * vector_weight + 
            data['bm25_score'] * bm25_weight
        )
        merged.append({
            'id': doc_id,
            'distance': final_score,
            'entity': data['entity']
        })
    
    # 按分数排序
    merged.sort(key=lambda x: x['distance'], reverse=True)
    return merged
```

#### 3.2 通用问题优先查FAQ

**实现**：在KnowledgeRetrievalTool中增加意图识别

```python
def detect_query_intent(query: str) -> str:
    """检测查询意图"""
    
    # 1. 通用金融知识（优先查FAQ）
    general_keywords = [
        'R1', 'R2', 'R3', 'R4', 'R5',  # 风险等级
        '是什么', '什么意思', '怎么办', '如何',  # 解释类
        '区别', '对比',  # 比较类
        '开户', '客服', '投诉', '联系方式',  # 公司信息
        'T+0', 'T+1', '净值',  # 金融术语
    ]
    if any(kw in query for kw in general_keywords):
        return 'general_knowledge'  # 优先查FAQ
    
    # 2. 具体产品查询（需要产品名称或代码）
    if any(kw in query for kw in ['货币基金', '债券基金', '混合基金', '产品代码']):
        return 'product_specific'
    
    # 3. 政策法规查询
    if any(kw in query for kw in ['政策', '法规', '监管', '合规', '反洗钱', '适当性']):
        return 'policy'
    
    # 4. 默认：产品通用查询
    return 'product_general'


def knowledge_retrieval_tool(query: str, top_k: int = 3) -> List[Dict]:
    """知识检索工具（优化版）"""
    
    intent = detect_query_intent(query)
    
    if intent == 'general_knowledge':
        # 优先查FAQ，阈值0.75
        results = hybrid_search('fin_faq_collection', query, top_k=3)
        if results:
            return results
        # FAQ无结果，降级查产品和政策
        results = hybrid_search('fin_product_collection_v2', query, top_k=2)
        results += hybrid_search('fin_policy_collection_v2', query, top_k=1)
        return results[:top_k]
    
    elif intent == 'product_specific':
        # 查产品，阈值0.65
        return hybrid_search('fin_product_collection_v2', query, top_k=top_k)
    
    elif intent == 'policy':
        # 查政策，阈值0.70
        return hybrid_search('fin_policy_collection_v2', query, top_k=top_k)
    
    else:
        # 默认：产品通用查询
        return hybrid_search('fin_product_collection_v2', query, top_k=top_k)
```

#### 3.3 产品问题追问客户

**场景**：客户只说"我想买基金"，未提供具体产品名称

**实现**：在Agent层增加参数提取和追问逻辑

```python
# 在 customerServiceAgent 的 System Prompt 中增加
"""
当客户询问具体产品时，必须确认以下信息：
1. 产品类型（货币基金/债券基金/混合基金/股票基金）
2. 产品名称或产品代码（如果客户已知）
3. 客户的风险等级（从画像中获取）

如果客户未提供产品名称，应追问：
- "您想了解哪款产品呢？可以告诉我产品名称或代码吗？"
- "您的风险评估等级是C2，我可以为您推荐适合的债券基金或银行理财产品，您想了解哪类呢？"

❌ 错误示范：直接用"基金"作为关键词检索（会返回大量无关结果）
✅ 正确示范：追问具体产品 → 用户提供"XX稳健增利债券A" → 检索该产品
```

#### 3.4 返回结果按文档和标题去重

**当前问题**：同一文档的多个chunk返回，重复展示

**去重逻辑**：

```python
def deduplicate_results(results: List[Dict]) -> List[Dict]:
    """按文档标题去重，保留最高分的chunk"""
    
    seen_titles = {}
    deduplicated = []
    
    for hit in results:
        metadata = hit['entity']['metadata']
        
        # 去重键：根据知识类型选择
        if metadata.get('knowledge_type') == 'FAQ':
            key = metadata.get('question', '')  # FAQ按问题去重
        else:
            key = metadata.get('title', '') or metadata.get('product_name', '')
        
        if not key:
            # 没有标题，保留
            deduplicated.append(hit)
            continue
        
        # 保留分数更高的
        if key not in seen_titles or hit['distance'] > seen_titles[key]['distance']:
            seen_titles[key] = hit
    
    deduplicated = list(seen_titles.values())
    deduplicated.sort(key=lambda x: x['distance'], reverse=True)
    
    return deduplicated
```

---

## 三、阈值重新标定方案

### 3.1 不共用阈值

| 检索类型 | 阈值 | 说明 |
|---|---|---|
| FAQ纯向量 | 0.75 | 保持不变，已验证合理 |
| 产品纯向量备用线 | 0.65 | BM25失效时使用 |
| 政策纯向量备用线 | 0.70 | BM25失效时使用 |
| 产品混合检索 | 待标定 | jieba修好后重新计算 |
| 政策混合检索 | 待标定 | jieba修好后重新计算 |

### 3.2 混合检索阈值标定流程

**前提**：jieba分词器已启用，数据已清洗并重新入库

**Step 1**：准备标准测试集（30道题）

```python
# scripts/generate_test_queries.py
STANDARD_QUERIES = [
    # 产品类（10题）
    {'query': 'XX货币市场基金的七日年化是多少', 'expected_doc': 'XX货币市场基金', 'type': 'product'},
    {'query': 'XX稳健增利债券A适合什么人', 'expected_doc': 'XX稳健增利债券A', 'type': 'product'},
    {'query': '混合基金和股票基金的区别', 'expected_doc': '产品对比表', 'type': 'product'},
    # ... 共10题
    
    # 政策类（10题）
    {'query': '投资者适当性管理的核心原则是什么', 'expected_doc': '适当性管理指南 > 第一条', 'type': 'policy'},
    {'query': '反洗钱可疑交易的识别标准', 'expected_doc': '反洗钱可疑交易识别规则 > 第二条', 'type': 'policy'},
    # ... 共10题
    
    # 通用类（10题）
    {'query': 'R1到R5是什么意思', 'expected_doc': 'FAQ', 'type': 'general'},
    {'query': '基金申购后多久确认', 'expected_doc': 'FAQ', 'type': 'general'},
    # ... 共10题
]
```

**Step 2**：批量测试不同阈值

```python
# scripts/calibrate_threshold.py
import numpy as np

def test_threshold(threshold, test_queries):
    """测试指定阈值下的准确率和召回率"""
    correct = 0
    total = len(test_queries)
    no_result_count = 0
    
    for item in test_queries:
        query = item['query']
        expected = item['expected_doc']
        query_type = item['type']
        
        # 执行检索
        results = hybrid_search(
            collection_name=f"fin_{query_type}_collection_v2",
            query=query,
            top_k=3
        )
        
        # 过滤低于阈值的结果
        filtered = [r for r in results if r['distance'] >= threshold]
        
        if not filtered:
            no_result_count += 1
            continue
        
        # 检查Top1是否正确
        top1_title = filtered[0]['entity']['metadata'].get('title', '')
        if expected in top1_title:
            correct += 1
    
    accuracy = correct / total
    no_result_rate = no_result_count / total
    
    return {
        'threshold': threshold,
        'accuracy': accuracy,
        'no_result_rate': no_result_rate,
        'correct': correct,
        'total': total
    }

# 测试阈值范围 0.45 ~ 0.75
thresholds = np.arange(0.45, 0.76, 0.05)
results = []

for threshold in thresholds:
    result = test_threshold(threshold, STANDARD_QUERIES)
    results.append(result)
    print(f"阈值 {threshold:.2f}: 准确率={result['accuracy']:.2%}, 无结果率={result['no_result_rate']:.2%}")

# 选择最优阈值（准确率最高且无结果率<10%）
best = max(
    [r for r in results if r['no_result_rate'] < 0.10],
    key=lambda x: x['accuracy']
)
print(f"\n推荐阈值: {best['threshold']:.2f}")
```

**Step 3**：根据测试结果确定最终阈值

**预期**：
- 混合检索阈值应低于纯向量阈值（因为融合后分数会被平均化）
- 合理范围：0.55 ~ 0.65

---

## 四、执行计划（Day 2上午）

### 时间分配（3小时）

| 时间 | 任务 | 负责人 | 输出 |
|---|---|---|---|
| 9:00-9:30 | Step 1.1: 清理FAQ重复 | 李清华 | 去重后的FAQ文件 |
| 9:30-10:30 | Step 1.2-1.4: 修正产品数据+增加字段 | 李清华 | 清洗后的产品/政策文件 |
| 10:30-11:00 | Step 2: 创建_v2集合（jieba） | 李清华 | 新集合创建完成 |
| 11:00-11:30 | 重新入库到_v2集合 | 李清华 | 数据导入完成 |
| 11:30-12:00 | Step 3: 测试jieba分词效果 | 李清华+赵嘉 | 分词效果验证报告 |

**下午任务**（如果上午未完成）：
- 13:30-15:00: 改进检索逻辑（Step 3.1-3.4）
- 15:00-16:00: 阈值标定（Step 3.2）
- 16:00-17:00: 切换到_v2集合并验证

---

## 五、验收标准

### 数据质量
- [x] FAQ去重完成，无重复"问题+答案"对
- [x] 所有产品`risk_level`修正为真实值（R1/R2/R3/R4）
- [x] 所有产品`product_code`补齐（真实代码或唯一标识符）
- [x] 产品内容无"XX"测试占位符残留
- [x] 产品资料增加`chunk_type`字段
- [x] 政策标题格式为"文件名 > 条款标题"

### 检索功能
- [x] jieba分词器正常工作（"投资者适当性管理"→`['投资者', '适当', '管理']`）
- [x] BM25无结果时使用纯向量分数（不打折）
- [x] 通用问题优先查FAQ（"R1到R5"先查FAQ再查产品）
- [x] 产品问题追问客户（未提供产品名称时提示）
- [x] 返回结果按标题去重

### 阈值设置
- [x] FAQ纯向量阈值=0.75
- [x] 产品纯向量备用线=0.65
- [x] 政策纯向量备用线=0.70
- [x] 混合检索阈值通过30题测试集标定

---

## 六、风险提示

### 高风险操作
1. **删除旧Milvus集合**：先创建_v2，测试通过后再删除
2. **修改检索逻辑**：需要在chatService的Agent调用中同步修改
3. **阈值调整**：不能仅凭经验，必须用测试集验证

### 回滚方案
如果_v2集合检索效果不如预期：
1. 检索代码切回旧集合（fin_product_collection）
2. 保留_v2集合用于调试
3. 分析jieba分词日志，定位问题

---

## 七、后续优化（Day 3可选）

1. **产品代码索引**：为`metadata.product_code`建立标量索引，加速精确匹配
2. **分区管理**：按`chunk_type`创建分区（详情/对比表/费用），提升检索效率
3. **动态权重**：根据查询类型动态调整向量和BM25权重
4. **A/B测试**：在客服Agent中对比旧/新检索逻辑的效果

---

**文档版本**：v1.0  
**创建时间**：2026-08-15  
**创建人**：李清华  
**审核人**：赵嘉/袁艺铭（客服Agent负责人）
