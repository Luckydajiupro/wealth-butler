from typing import Optional, List, ClassVar

from pydantic import Field

from Base.Ai.llms.qwenLlm import get_default_qwen_llm
from Base.Repository.base.baseVDB import BaseVDBModel
from pymilvus import Function, FunctionType


class VDBLLMKeyword(BaseVDBModel):
    """
    关键词向量数据库模型
    """
    collection_alias: ClassVar[str] = "keyword"
    description: ClassVar[str] = "关键词表"

    id: Optional[int] = Field(
        default=0,
        json_schema_extra={
            'is_primary': True,
            'auto_id': True
        }
    )

    db_id: Optional[str] = Field(
        default='',
        json_schema_extra={
            'max_length': 50
        }
    )

    keyword_name: Optional[str] = Field(
        default='',
        json_schema_extra={
            'enable_match': True,
            'enable_analyzer': True,
            'max_length': 100
        }
    )

    keyword_code: Optional[str] = Field(
        default='',
        json_schema_extra={
            'max_length': 50
        }
    )

    keyword_synonyms: Optional[str] = Field(
        default='',
        json_schema_extra={
            'max_length': 50
        }
    )

    keyword_desc: Optional[str] = Field(
        default='',
        json_schema_extra={
            'max_length': 65535
        }
    )

    semantic_desc: Optional[str] = Field(
        default='',
        json_schema_extra={
            'max_length': 65535
        }
    )

    embedding: Optional[List[float]] = Field(
        default_factory=list,
        json_schema_extra={
            'dim': 1024
        }
    )

    # 稀疏向量字段（基于 BM25 文本字段生成）
    content_sparse: Optional[List[float]] = Field(
        default_factory=list,
        json_schema_extra={
            'is_sparse_vector': True,
            'bm25_source_field': 'keyword_name'
        }
    )



    @staticmethod
    def get_similarity_keywords(question: str, limit: int = 10):
        llm = get_default_qwen_llm()
        embedding = llm.embedding(question, dimensions=1024)
        ranker = Function(
            name="rrf",
            input_field_names=[],  # Must be an empty list
            function_type=FunctionType.RERANK,
            params={
                "reranker": "rrf",
                "k": 100  # Optional
            }
        )
        res = VDBLLMKeyword.hybrid_search(
            queries=[
                {
                    'data': embedding,  # 密集向量搜索
                    'field': 'embedding',
                    'type': 'dense',
                    'params': {
                        'metric_type': 'COSINE',
                        'params': {'nprobe': 10}
                    }
                },
                {
                    'data': [question],
                    'field': 'content_sparse',
                    'type': 'sparse',
                    'params': {
                        'metric_type': 'BM25',
                        'params': {}
                    }
                }
            ],
            limit=limit,
            # filter_expr=filter_expr,  # 添加过滤条件
            weights=[0.3, 0.7],
            output_fields=['db_id', 'keyword_name', 'keyword_code', 'keyword_desc', 'keyword_synonyms', 'semantic_desc'],
            ranker=ranker
            # 返回需要的字段
        )
        return res

    @staticmethod
    def get_similarity_keywords_by_bm25(question: str, limit: int = 10):
        res = VDBLLMKeyword.get_connection().client.search(
            data=[question],  # 直接传入文本
            collection_name=VDBLLMKeyword.collection_alias,
            anns_field='content_sparse',  # 稀疏向量字段
            search_params={
                'metric_type': 'BM25',
                'params': {}
            },
            limit=limit,
            output_fields=['db_id', 'keyword_name', 'keyword_code', 'keyword_desc', 'keyword_synonyms', 'semantic_desc']
        )
        return res[0]


if __name__ == '__main__':
    test_res = VDBLLMKeyword.get_similarity_keywords("狗头,打,鳄鱼,几几开")
    for i in test_res:
        print(i)
