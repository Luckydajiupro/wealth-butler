#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查Milvus collection的schema配置"""

import sys
sys.path.append('D:/lqh/金融')

from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2

# 获取collection信息
print("=== FAQ Collection Schema ===")
conn = FaqCollectionModelV2.get_connection()
faq_collection = conn.describe_collection(FaqCollectionModelV2.get_collection_name())
print(faq_collection)

print("\n=== Product Collection Schema ===")
product_collection = conn.describe_collection(ProductCollectionModelV2.get_collection_name())
print(product_collection)

print("\n=== Policy Collection Schema ===")
policy_collection = conn.describe_collection(PolicyCollectionModelV2.get_collection_name())
print(policy_collection)
