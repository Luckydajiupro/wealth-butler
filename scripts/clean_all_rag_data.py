# -*- coding: utf-8 -*-
"""清理所有RAG数据（MySQL + Milvus）"""
import sys
sys.path.insert(0, 'D:/lqh/金融')

import pymysql
from app.Base.Config.setting import settings
from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2

print("=" * 60)
print("清理所有RAG数据（MySQL + Milvus）")
print("=" * 60)

# 1. 清理MySQL中的fin_knowledge_meta表
print("\n[1] 清理MySQL fin_knowledge_meta表...")
try:
    conn = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=settings.mysql.name,
        charset='utf8mb4'
    )
    cursor = conn.cursor()

    # 查询当前记录数
    cursor.execute("SELECT COUNT(*) FROM fin_knowledge_meta")
    count_before = cursor.fetchone()[0]
    print(f"    清理前记录数: {count_before}")

    # 删除所有记录
    cursor.execute("DELETE FROM fin_knowledge_meta")
    conn.commit()

    # 查询清理后记录数
    cursor.execute("SELECT COUNT(*) FROM fin_knowledge_meta")
    count_after = cursor.fetchone()[0]
    print(f"    清理后记录数: {count_after}")
    print(f"    [OK] 已删除 {count_before - count_after} 条记录")

    cursor.close()
    conn.close()
except Exception as e:
    print(f"    [ERROR] MySQL清理失败: {e}")

# 2. 清理并重建Milvus集合
print("\n[2] 清理Milvus集合...")
collections = [
    ('FAQ集合', FaqCollectionModelV2),
    ('产品集合', ProductCollectionModelV2),
    ('政策集合', PolicyCollectionModelV2)
]

for name, model in collections:
    try:
        collection_name = model.get_collection_name()
        connection = model.get_connection()

        # 删除集合
        if connection.has_collection(collection_name):
            connection.client.drop_collection(collection_name)
            print(f"    [OK] 已删除 {name}: {collection_name}")
        else:
            print(f"    [SKIP] {name}不存在: {collection_name}")

        # 重建集合
        model._check_and_create_collection()
        print(f"    [OK] 已重建 {name}: {collection_name}")

    except Exception as e:
        print(f"    [ERROR] {name}处理失败: {e}")

print("\n" + "=" * 60)
print("清理完成，可以重新运行 rag_ingestion_full.py 入库")
print("=" * 60)
