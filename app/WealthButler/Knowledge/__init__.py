"""知识库管理层

职责：
- 实现 RAG/GraphRAG 的知识切片、向量化、入库流程
- 管理 Milvus 三个集合（fin_product/fin_policy/fin_faq）的 CRUD 操作
- 管理 Neo4j 知识图谱的实体关系构建与查询
- 提供知识库更新、版本管理、质量评估接口

分层原则：
- 本层是知识工程层，负责"离线数据准备"，与"在线检索"（Tools 层）解耦
- 复用 Base.Client.milvusClient 和 Base.Client.neo4jClient
- 切片策略由 RAG切片入库策略.md 定义，本层实现具体逻辑
- 知识更新是后台任务，不阻塞 API 请求

核心概念：
- Collection: Milvus 向量集合（对应一类知识库）
- Chunk: 文档切片（一个原始文档切分为多个 Chunk）
- Embedding: 向量表示（通过嵌入模型将 Chunk 转为向量）
- Entity: Neo4j 实体节点（基金/公司/行业/产品）
- Relationship: Neo4j 关系边（基金-投资于-公司）

3 个 Milvus Collection（架构设计文档§8.1）：
1. fin_product_collection    理财产品知识库
   - 来源：公司业务/个人理财产品手册.md
   - Schema: {id, chunk_text, embedding[1024], product_id, product_name, metadata}
   - 切片策略：按产品维度切片（每个产品 1 个 Chunk），见 RAG切片入库策略.md

2. fin_policy_collection     金融政策知识库
   - 来源：金融政策/*.md（反洗钱/适当性管理/销售管理）
   - Schema: {id, chunk_text, embedding[1024], policy_name, effective_date, metadata}
   - 切片策略：按章节切片（每章节 300-500 字），Markdown 标题识别

3. fin_faq_collection        高频问答知识库
   - 来源：公司信息/高频问答对.txt
   - Schema: {id, question, answer, embedding[1024], category, metadata}
   - 切片策略：QA 对不切片（一问一答为一个 Chunk）

Neo4j 知识图谱（架构设计文档§8.2）：
- 实体类型：Fund(基金)、Company(公司)、Industry(行业)、Product(产品)
- 关系类型：INVESTS_IN(投资于)、BELONGS_TO(属于)、COMPETES_WITH(竞争)
- 来源：从产品手册、公开数据（如基金持仓）提取

典型模块：
- ragIngestion.py            RAG 向量入库管道
  - ingest_product_docs() → 产品手册切片入库
  - ingest_policy_docs()  → 政策文档切片入库
  - ingest_faq_docs()     → FAQ 问答对入库

- graphBuilder.py            知识图谱构建管道
  - build_fund_graph()    → 构建基金-公司-行业关系图谱
  - build_product_graph() → 构建产品关联图谱

- chunkStrategy.py           切片策略实现
  - chunk_by_product()    → 按产品维度切片
  - chunk_by_section()    → 按章节切片
  - chunk_by_qa_pair()    → QA 对不切片

- embeddingService.py        嵌入模型封装
  - embed_text(text) -> list[float]  # 调用本地 Ollama bge-m3
  - batch_embed(texts) -> list[list[float]]

- collectionManager.py       Milvus 集合管理
  - create_collection(name, schema)
  - insert_vectors(collection, data)
  - update_vectors(collection, ids, data)
  - delete_by_ids(collection, ids)

RAG 向量入库管道实现：
    from Base.Client.milvusClient import get_milvus_client
    from WealthButler.Knowledge.chunkStrategy import chunk_by_product
    from WealthButler.Knowledge.embeddingService import batch_embed
    import os
    import json

    class RAGIngestion:
        '''RAG 向量入库管道'''

        def __init__(self):
            self.milvus = get_milvus_client()
            self.collection_name = 'fin_product_collection'

        def ingest_product_docs(self, source_dir: str):
            '''产品手册切片入库

            Args:
                source_dir: 产品文档目录（如 公司业务/）

            流程：
                1. 读取 Markdown 文档
                2. 按产品维度切片（chunk_by_product）
                3. 批量向量化（batch_embed）
                4. 插入 Milvus
            '''
            # 1. 读取文档
            doc_path = os.path.join(source_dir, '个人理财产品手册.md')
            with open(doc_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 2. 切片（按产品维度）
            chunks = chunk_by_product(content)
            # chunks = [
            #     {
            #         'product_id': 'P001',
            #         'product_name': '稳健增值理财',
            #         'chunk_text': '产品描述...',
            #         'metadata': {'risk_level': '中低风险', 'term': '6个月'}
            #     },
            #     ...
            # ]

            # 3. 批量向量化（每批 32 条）
            batch_size = 32
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i+batch_size]
                texts = [c['chunk_text'] for c in batch]
                embeddings = batch_embed(texts)

                # 4. 构造 Milvus 插入数据
                data = []
                for chunk, embedding in zip(batch, embeddings):
                    data.append({
                        'chunk_text': chunk['chunk_text'],
                        'embedding': embedding,
                        'product_id': chunk['product_id'],
                        'product_name': chunk['product_name'],
                        'metadata': json.dumps(chunk['metadata'], ensure_ascii=False)
                    })

                # 5. 插入 Milvus
                self.milvus.insert(collection_name=self.collection_name, data=data)

            print(f"[RAGIngestion] Ingested {len(chunks)} product chunks")

        def ingest_policy_docs(self, source_dir: str):
            '''政策文档切片入库（按章节切片）'''
            # 类似实现，使用 chunk_by_section()
            pass

        def ingest_faq_docs(self, source_path: str):
            '''FAQ 问答对入库（不切片）'''
            # 类似实现，使用 chunk_by_qa_pair()
            pass

切片策略实现（chunkStrategy.py）：
    import re

    def chunk_by_product(markdown_content: str) -> list[dict]:
        '''按产品维度切片（RAG切片入库策略.md §2.1）

        策略：识别 Markdown 二级标题（##）作为产品边界
        '''
        chunks = []
        # 正则匹配 ## 产品名称
        pattern = r'^## (.+?)\\n(.*?)(?=\\n## |$)'
        matches = re.finditer(pattern, markdown_content, re.MULTILINE | re.DOTALL)

        for idx, match in enumerate(matches):
            product_name = match.group(1).strip()
            product_desc = match.group(2).strip()

            # 提取元数据（风险等级、期限等）
            metadata = extract_metadata(product_desc)

            chunks.append({
                'product_id': f'P{idx+1:03d}',  # 自动生成 ID
                'product_name': product_name,
                'chunk_text': product_desc,
                'metadata': metadata
            })

        return chunks

    def chunk_by_section(markdown_content: str, max_len: int = 500) -> list[dict]:
        '''按章节切片（RAG切片入库策略.md §2.2）

        策略：识别 Markdown 标题（### 或 ####），每章节 300-500 字
        '''
        # 实现省略（类似 chunk_by_product，但按字数截断）
        pass

    def chunk_by_qa_pair(qa_text: str) -> list[dict]:
        '''QA 对不切片（RAG切片入库策略.md §2.3）

        策略：每行一个 QA 对（格式：Q: 问题\\nA: 答案）
        '''
        chunks = []
        lines = qa_text.strip().split('\\n\\n')  # 双换行分隔 QA 对

        for line in lines:
            if line.startswith('Q:'):
                parts = line.split('\\nA:')
                if len(parts) == 2:
                    question = parts[0].replace('Q:', '').strip()
                    answer = parts[1].strip()
                    chunks.append({
                        'question': question,
                        'answer': answer,
                        'chunk_text': f"{question} {answer}"  # 拼接用于向量化
                    })

        return chunks

嵌入模型封装（embeddingService.py）：
    import requests

    class EmbeddingService:
        '''嵌入模型封装（本地 Ollama bge-m3）'''

        def __init__(self, api_url: str = 'http://localhost:11434/api/embeddings'):
            self.api_url = api_url
            self.model = 'bge-m3'

        def embed_text(self, text: str) -> list[float]:
            '''单文本向量化'''
            response = requests.post(self.api_url, json={
                'model': self.model,
                'prompt': text
            })
            return response.json()['embedding']

        def batch_embed(self, texts: list[str]) -> list[list[float]]:
            '''批量文本向量化'''
            return [self.embed_text(t) for t in texts]

    # 全局单例
    _embedding_service = EmbeddingService()

    def batch_embed(texts: list[str]) -> list[list[float]]:
        return _embedding_service.batch_embed(texts)

Neo4j 图谱构建（graphBuilder.py）：
    from Base.Client.neo4jClient import get_neo4j_client

    class GraphBuilder:
        '''知识图谱构建管道'''

        def __init__(self):
            self.neo4j = get_neo4j_client()

        def build_fund_graph(self, fund_data: list[dict]):
            '''构建基金-公司-行业关系图谱

            Args:
                fund_data: [
                    {
                        'fund_id': 'F001',
                        'fund_name': '华夏成长',
                        'holdings': [
                            {'company': '腾讯', 'industry': '互联网', 'weight': 0.05}
                        ]
                    }
                ]
            '''
            with self.neo4j.session() as session:
                for fund in fund_data:
                    # 创建基金节点
                    session.run(
                        "MERGE (f:Fund {id: $id, name: $name})",
                        id=fund['fund_id'], name=fund['fund_name']
                    )

                    # 创建持仓关系
                    for holding in fund['holdings']:
                        session.run('''
                            MERGE (c:Company {name: $company})
                            MERGE (i:Industry {name: $industry})
                            MERGE (c)-[:BELONGS_TO]->(i)
                            MERGE (f:Fund {id: $fund_id})
                            MERGE (f)-[:INVESTS_IN {weight: $weight}]->(c)
                        ''', fund_id=fund['fund_id'], company=holding['company'],
                            industry=holding['industry'], weight=holding['weight'])

            print(f"[GraphBuilder] Built fund graph with {len(fund_data)} funds")

启动入库任务（在 Base/main.py 或独立脚本）：
    from WealthButler.Knowledge.ragIngestion import RAGIngestion

    # 方式1：启动时一次性入库
    ingestion = RAGIngestion()
    ingestion.ingest_product_docs('D:\\\\lqh\\\\金融\\\\公司业务')
    ingestion.ingest_policy_docs('D:\\\\lqh\\\\金融\\\\金融政策')
    ingestion.ingest_faq_docs('D:\\\\lqh\\\\金融\\\\公司信息\\\\高频问答对.txt')

    # 方式2：定时更新（每天凌晨2点）
    from Base.Service.scheduler.schedulerService import SchedulerService
    SchedulerService.add_job(
        func=ingestion.ingest_product_docs,
        trigger='cron',
        hour=2,
        args=['D:\\\\lqh\\\\金融\\\\公司业务']
    )

与架构设计文档的对应关系：
- §8.1: 智能客服 Agent 的 RAG 检索（三个 Collection）
- §8.2: 投顾助手 Agent 的 GraphRAG 增强（Neo4j 图谱查询）
- RAG切片入库策略.md: 三种切片策略的详细说明

技术约束：
- Milvus Collection 需预先创建（Schema 固定：chunk_text + embedding[1024] + metadata）
- 向量维度 1024（Ollama bge-m3 模型输出维度）
- Neo4j 图谱更新是全量覆盖（先删除旧节点，再插入新节点）
- 入库任务耗时较长（产品手册约 5min），应后台异步执行

使用规范：
- 知识库更新需要版本号标记（metadata.version）
- 生产环境入库前需在测试环境验证切片质量
- 向量化失败的 Chunk 应记录日志，不中断整个流程
- Neo4j 图谱查询应加 LIMIT，避免全图遍历
"""

__all__ = []
