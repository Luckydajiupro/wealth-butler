"""快速测试 RAG 入库脚本的关键组件

测试项：
1. Ollama 连接和向量生成
2. MinIO 文件上传
3. MySQL 知识元数据写入
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.Base.Client.ollamaClient import ollama_client
from app.Base.Client.minioClient import default_minio_client as minio_client
from app.Base.Client.mysqlClient import get_db
from app.WealthButler.Models.knowledgeMetaModel import FinKnowledgeMeta
import io

print("=" * 60)
print("测试 1: Ollama bge-m3 向量生成")
print("=" * 60)

try:
    test_text = "这是一个测试文本，用于验证向量生成功能"
    embedding = ollama_client.get_embedding(test_text, model='bge-m3')
    print(f"✓ 向量生成成功: 维度={len(embedding)}")
    print(f"  前5维: {embedding[:5]}")
except Exception as e:
    print(f"✗ 向量生成失败: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("测试 2: MinIO 文件上传")
print("=" * 60)

try:
    bucket_name = 'fin-knowledge-raw'
    if not minio_client.bucket_exists(bucket_name):
        minio_client.make_bucket(bucket_name)
        print(f"✓ 创建 bucket: {bucket_name}")

    test_content = "测试内容：知识库原文归档测试"
    object_key = "test/test_file.txt"
    data = test_content.encode('utf-8')

    minio_client.client.put_object(
        bucket_name=bucket_name,
        object_name=object_key,
        data=io.BytesIO(data),
        length=len(data),
        content_type='text/plain; charset=utf-8'
    )
    print(f"✓ 文件上传成功: {bucket_name}/{object_key}")
except Exception as e:
    print(f"✗ 文件上传失败: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("测试 3: MySQL 知识元数据写入")
print("=" * 60)

try:
    db = next(get_db())

    # 创建测试记录
    meta = FinKnowledgeMeta(
        knowledge_type='FAQ',
        title='测试FAQ',
        source_file='test.txt',
        source_url=object_key,
        status='待入库',
        uploaded_by=1
    )
    db.add(meta)
    db.commit()

    print(f"✓ 知识元数据写入成功: knowledge_id={meta.knowledge_id}")

    # 清理测试数据
    db.delete(meta)
    db.commit()
    print(f"✓ 测试数据已清理")

except Exception as e:
    print(f"✗ 知识元数据写入失败: {e}")
    db.rollback()
    sys.exit(1)
finally:
    db.close()

print("\n" + "=" * 60)
print("✓ 所有组件测试通过，可以开始切片入库")
print("=" * 60)
