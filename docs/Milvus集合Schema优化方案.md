# Milvus集合Schema优化方案

## 问题分析

### 当前设计的严重问题

#### 1. 数据类型不匹配（导致入库失败）

**Schema定义**（`faqCollectionModel.py`）：
```python
id: Optional[int] = Field(
    default=0,
    json_schema_extra={
        'is_primary': True,
        'auto_id': True  # 期望Milvus自动生成整型ID
    }
)

updated_at: Optional[int] = Field(default=0)  # 定义为int
```

**入库脚本实际写入**（`rag_ingestion.py` Line 294-299）：
```python
data_list.append({
    'id': f"faq_{i}_{hash(text) % 1000000}",  # ❌ 字符串ID！
    'updated_at': datetime.now().strftime('%Y-%m-%d'),  # ❌ 字符串日期！
    ...
})
```

**后果**：
- Milvus期望`id`是整型，实际传入字符串 → **类型错误或被忽略**
- `updated_at`定义为int但传入字符串 → **类型错误或默认值0**
- 结果：字段值缺失或入库失败

#### 2. 字段冗余且不符合向量库最佳实践

当前Schema将所有业务字段平铺：
```python
class FaqCollectionModel:
    id: int
    question: str
    answer: str
    source: str
    category: str
    updated_at: int
    embedding: List[float]
```

**问题**：
- 标量字段分散，不易维护
- 新增字段需要修改Schema并重建集合
- 缺少原始切片文本，无法追溯完整内容

---

## 优化方案：标准三字段模式

### 新Schema设计

```python
class FaqCollectionModel(BaseVDBModel):
    """FAQ问答集合（标准向量库模式）"""
    
    # 主键（Milvus自动生成）
    id: Optional[int] = Field(
        default=0,
        json_schema_extra={
            'is_primary': True,
            'auto_id': True
        }
    )
    
    # 切片原文（完整保留，便于调试和展示）
    text: Optional[str] = Field(
        default="",
        json_schema_extra={
            'max_length': 65535
        }
    )
    
    # 元数据JSON（集中管理所有业务字段）
    metadata: Optional[dict] = Field(
        default={},
        json_schema_extra={
            'max_length': 65535  # JSON字段
        }
    )
    
    # 稠密向量
    embedding: Optional[List[float]] = Field(
        default=[],
        json_schema_extra={
            'dim': 1024
        }
    )
```

### 入库数据格式

```python
# FAQ示例
{
    'id': 1,  # 由Milvus自动生成，入库时不传或传0
    'text': 'Q: 如何开通网银？\nA: 请携带身份证和银行卡前往任意网点办理...',
    'metadata': {
        'question': '如何开通网银？',
        'answer': '请携带身份证和银行卡前往任意网点办理...',
        'source': 'D:/lqh/金融/公司信息/高频问答对.txt',
        'category': '公司信息',
        'knowledge_type': 'FAQ',
        'chunk_index': 1,
        'updated_at': '2026-08-15'
    },
    'embedding': [0.123, 0.456, ...]  # 1024维
}
```

---

## 优势对比

| 维度 | 当前设计 | 优化方案 |
|---|---|---|
| **主键类型** | ❌ 字符串哈希（与Schema不符） | ✅ 自增整型（Milvus自动生成） |
| **原文保留** | ❌ 需拼接question+answer | ✅ text字段完整保留 |
| **字段扩展** | ❌ 需修改Schema重建集合 | ✅ metadata内部扩展，无需重建 |
| **类型安全** | ❌ updated_at类型不匹配 | ✅ metadata统一为JSON |
| **查询返回** | ❌ 只能返回分离的question/answer | ✅ text直接可用于展示 |
| **调试追溯** | ❌ 无法知道原始切片内容 | ✅ text字段一目了然 |
| **最佳实践** | ❌ 不符合Milvus官方推荐 | ✅ 标准三字段模式 |

---

## 实施步骤

### Step 1：重构集合模型（4个集合统一）

**文件**：
- `app/WealthButler/Repository/faqCollectionModel.py`
- `app/WealthButler/Repository/productCollectionModel.py`
- `app/WealthButler/Repository/policyCollectionModel.py`
- `app/WealthButler/Repository/customerMemoryCollectionModel.py`

**统一改为**：
```python
from typing import Optional, ClassVar, List
from pydantic import Field
from app.Base.Repository.base.baseVDB import BaseVDBModel


class FaqCollectionModel(BaseVDBModel):
    """FAQ问答集合（标准三字段模式）"""
    
    # 1. 自增主键
    id: Optional[int] = Field(
        default=0,
        json_schema_extra={'is_primary': True, 'auto_id': True}
    )
    
    # 2. 切片原文
    text: Optional[str] = Field(
        default="",
        json_schema_extra={'max_length': 65535}
    )
    
    # 3. 元数据JSON
    metadata: Optional[dict] = Field(
        default={},
        json_schema_extra={'max_length': 65535}
    )
    
    # 4. 稠密向量
    embedding: Optional[List[float]] = Field(
        default=[],
        json_schema_extra={'dim': 1024}
    )
    
    # 集合配置
    collection_alias: ClassVar[str] = "fin_faq_collection"
    description: ClassVar[str] = "FAQ问答集合"
    auto_create_collection: ClassVar[bool] = True
    
    # 向量索引
    _vector_fields_config: ClassVar[dict] = {
        'index_type': 'HNSW',
        'metric_type': 'COSINE',
        'params': {"M": 16, "efConstruction": 200}
    }
```

### Step 2：修改入库脚本

**文件**：`scripts/rag_ingestion.py`

**修改 Line 260-350 的 insert_to_milvus() 函数**：

```python
def insert_to_milvus(collection_name: str, chunks: List[Dict], knowledge_type: str, title: str = '') -> List[int]:
    """批量插入 Milvus（标准三字段模式）"""
    
    if not chunks:
        return []
    
    try:
        data_list = []
        
        for i, chunk in enumerate(chunks, 1):
            # 统一格式：id + text + metadata + embedding
            chunk_metadata = chunk.get('metadata', {})
            
            # 根据知识类型定制metadata内容
            if knowledge_type == 'FAQ':
                # 从text中提取question和answer
                text = chunk['text']
                if '\nA:' in text:
                    question = text.split('\nA:')[0].replace('Q: ', '').strip()
                    answer = text.split('\nA:')[1].strip()
                else:
                    question = chunk.get('question', text[:200])
                    answer = chunk.get('answer', '')
                
                metadata = {
                    'question': question,
                    'answer': answer,
                    'source': str(chunk_metadata.get('source', '')),
                    'category': '公司信息',
                    'knowledge_type': knowledge_type,
                    'chunk_index': chunk_metadata.get('chunk_index', i),
                    'updated_at': datetime.now().strftime('%Y-%m-%d')
                }
            
            elif knowledge_type == '产品说明书':
                metadata = {
                    'product_name': title,
                    'product_code': '',
                    'product_type': '理财产品',
                    'risk_level': 'R2',
                    'source': str(chunk_metadata.get('source', '')),
                    'knowledge_type': knowledge_type,
                    'chunk_index': chunk_metadata.get('chunk_index', i),
                    'updated_at': datetime.now().strftime('%Y-%m-%d')
                }
            
            elif knowledge_type == '政策法规':
                metadata = {
                    'title': title,
                    'policy_no': '',
                    'category': '监管政策',
                    'issuer': '银保监会',
                    'effective_date': '2024-01-01',
                    'source': str(chunk_metadata.get('source', '')),
                    'knowledge_type': knowledge_type,
                    'chunk_index': chunk_metadata.get('chunk_index', i),
                    'updated_at': datetime.now().strftime('%Y-%m-%d')
                }
            
            # 构造标准三字段数据
            data_list.append({
                # id字段不传，让Milvus auto_id自动生成
                'text': chunk['text'],
                'metadata': metadata,
                'embedding': chunk['embedding']
            })
        
        # 插入数据
        result = milvus_client.insert(
            collection_name=collection_name,
            data=data_list
        )
        
        pk_list = result.get('ids', []) if isinstance(result, dict) else []
        logger.info(f"Milvus 插入成功：{collection_name}，{len(pk_list)} 条")
        return pk_list
    
    except Exception as e:
        logger.error(f"Milvus 插入失败: {e}")
        raise
```

### Step 3：修改检索逻辑

**所有调用Milvus检索的地方**（如`KnowledgeRetrievalTool`）：

```python
# 检索时指定返回字段
results = milvus_client.search(
    collection_name='fin_faq_collection',
    data=[query_embedding],
    output_fields=['id', 'text', 'metadata'],  # 新增text和metadata
    limit=3
)

# 解析结果
for hit in results[0]:
    chunk_text = hit['entity']['text']  # 完整切片文本
    metadata = hit['entity']['metadata']  # JSON元数据
    
    # 从metadata提取业务字段
    question = metadata.get('question', '')
    answer = metadata.get('answer', '')
    source = metadata.get('source', '')
```

---

## 迁移方案

### 方案A：删除重建（推荐，数据量小）

```python
# 1. 删除旧集合
milvus_client.drop_collection('fin_faq_collection')
milvus_client.drop_collection('fin_product_collection')
milvus_client.drop_collection('fin_policy_collection')

# 2. 运行新Schema初始化
python scripts/init_data_layer.py

# 3. 重新入库
python scripts/rag_ingestion.py
```

### 方案B：别名切换（生产环境）

```python
# 1. 创建新集合 fin_faq_collection_v2
# 2. 数据迁移到新集合
# 3. 切换别名 fin_faq_collection -> fin_faq_collection_v2
# 4. 删除旧集合
```

---

## 验收标准

- [x] 4个集合Schema统一为标准三字段（id/text/metadata/embedding）
- [x] 入库脚本ID字段不传值（由Milvus auto_id生成）
- [x] metadata字段包含所有业务信息（JSON格式）
- [x] 检索返回text字段可直接展示
- [x] 类型匹配正确（无类型转换错误）
- [x] 新增字段只需修改metadata构造逻辑，无需重建集合

---

## 后续优化（可选）

1. **BM25混合检索**：产品和政策集合可增加`text_sparse`稀疏向量字段
2. **分区管理**：按`knowledge_type`创建分区，加速检索
3. **动态字段**：Milvus 2.4+支持动态字段，metadata可自动扩展

---

**优先级**：🔴 P0（Day 2上午必须修复）

**原因**：
1. 当前入库脚本存在类型错误，可能导致数据缺失
2. 影响所有依赖RAG检索的Agent（客服/投顾）
3. 修复后需重新入库，越早处理越好
