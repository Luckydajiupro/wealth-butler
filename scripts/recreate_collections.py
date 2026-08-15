#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重建Milvus collections以修复id字段类型问题"""

import sys
sys.path.append('D:/lqh/金融')

from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2

def recreate_collection(model_class, collection_name):
    """删除并重建collection"""
    conn = model_class.get_connection()

    # 检查collection是否存在
    if conn.has_collection(collection_name):
        print(f"删除旧collection: {collection_name}")
        # 使用底层client的drop_collection方法
        conn.client.drop_collection(collection_name)
        print(f"  [OK] 已删除")

    # 重新创建collection（会触发auto_create_collection逻辑）
    print(f"重建collection: {collection_name}")
    model_class._check_and_create_collection()

    # 验证新schema
    schema = conn.describe_collection(collection_name)
    id_field = next((f for f in schema['fields'] if f['name'] == 'id'), None)
    if id_field:
        print(f"  新id字段类型: {id_field['type']}")
        print(f"  auto_id: {id_field.get('auto_id', False)}")
        print(f"  is_primary: {id_field.get('is_primary', False)}")
    print()

if __name__ == '__main__':
    print("=== 重建Milvus Collections ===\n")

    recreate_collection(FaqCollectionModelV2, 'fin_faq_collection')
    recreate_collection(ProductCollectionModelV2, 'fin_product_collection')
    recreate_collection(PolicyCollectionModelV2, 'fin_policy_collection')

    print("=== 完成 ===")
