"""
数据层完整性检查脚本（简化版）

检查项：
1. Milvus V2集合数据量统计
2. 文件系统中的Model定义完整性
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.Base.Client.milvusClient import MilvusClientSingleton


def check_milvus_v2_collections():
    """检查Milvus V2集合及数据量"""
    print("[Milvus V2 Collections Check]")
    print("=" * 60)

    v2_collections = [
        'fin_faq_collection_v2',
        'fin_product_collection_v2',
        'fin_policy_collection_v2'
    ]

    try:
        milvus_client = MilvusClientSingleton()
        existing_collections = milvus_client.list_collections()

        total_records = 0
        all_exist = True

        for collection in v2_collections:
            if collection in existing_collections:
                # 查询数据量
                try:
                    stats = milvus_client.query(
                        collection_name=collection,
                        filter="",
                        output_fields=["count(*)"],
                        limit=1
                    )
                    count = stats[0].get('count(*)', 0) if stats else 0
                except:
                    # 使用备用方法：查询所有记录
                    records = milvus_client.query(
                        collection_name=collection,
                        filter="",
                        output_fields=["id"],
                        limit=1000
                    )
                    count = len(records) if records else 0

                total_records += count
                print(f"[OK] {collection}: {count} records")
            else:
                print(f"[MISSING] {collection}")
                all_exist = False

        print(f"\nTotal records across V2 collections: {total_records}")

        if all_exist and total_records > 0:
            print("\n[SUCCESS] All V2 collections exist with data")
            return True
        elif all_exist:
            print("\n[WARNING] All collections exist but no data")
            return False
        else:
            print("\n[WARNING] Some V2 collections missing")
            return False

    except Exception as e:
        print(f"[ERROR] Milvus check failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_model_files():
    """检查Model文件是否完整"""
    print("\n[Model Files Check]")
    print("=" * 60)

    # MySQL Models
    mysql_models = [
        'app/WealthButler/Models/baseUserExtModel.py',
        'app/WealthButler/Models/customerProfileModel.py',
        'app/WealthButler/Models/productModel.py',
        'app/WealthButler/Models/transactionModel.py',
        'app/WealthButler/Models/holdingsModel.py',
        'app/WealthButler/Models/riskAssessmentModel.py',
        'app/WealthButler/Models/riskAlertModel.py',
        'app/WealthButler/Models/workOrderModel.py',
        'app/WealthButler/Models/knowledgeMetaModel.py',
        'app/WealthButler/Models/conversationArchiveModel.py'
    ]

    print("\n[MySQL Models]")
    mysql_ok = 0
    for model_file in mysql_models:
        if os.path.exists(model_file):
            print(f"[OK] {os.path.basename(model_file)}")
            mysql_ok += 1
        else:
            print(f"[MISSING] {os.path.basename(model_file)}")

    # Milvus V2 Models
    milvus_models = [
        'app/WealthButler/Repository/faqCollectionModelV2.py',
        'app/WealthButler/Repository/productCollectionModelV2.py',
        'app/WealthButler/Repository/policyCollectionModelV2.py'
    ]

    print("\n[Milvus V2 Models]")
    milvus_ok = 0
    for model_file in milvus_models:
        if os.path.exists(model_file):
            print(f"[OK] {os.path.basename(model_file)}")
            milvus_ok += 1
        else:
            print(f"[MISSING] {os.path.basename(model_file)}")

    print(f"\nMySQL Models: {mysql_ok}/{len(mysql_models)}")
    print(f"Milvus V2 Models: {milvus_ok}/{len(milvus_models)}")

    all_ok = (mysql_ok == len(mysql_models)) and (milvus_ok == len(milvus_models))

    if all_ok:
        print("\n[SUCCESS] All model files exist")
        return True
    else:
        print("\n[WARNING] Some model files missing")
        return False


def check_service_files():
    """检查关键Service文件"""
    print("\n[Service Files Check]")
    print("=" * 60)

    service_files = [
        'app/WealthButler/Service/chatService.py',
        'app/WealthButler/Service/riskService.py',
        'app/WealthButler/Service/ragSearchService.py'
    ]

    ok_count = 0
    for service_file in service_files:
        if os.path.exists(service_file):
            print(f"[OK] {os.path.basename(service_file)}")
            ok_count += 1
        else:
            print(f"[MISSING] {os.path.basename(service_file)}")

    print(f"\nTotal: {ok_count}/{len(service_files)}")

    if ok_count == len(service_files):
        print("\n[SUCCESS] All service files exist")
        return True
    else:
        print("\n[WARNING] Some service files missing")
        return False


def main():
    """主函数"""
    print("Data Layer Completeness Check (Simplified)")
    print("=" * 60)

    results = {
        'milvus_v2': check_milvus_v2_collections(),
        'model_files': check_model_files(),
        'service_files': check_service_files()
    }

    print("\n" + "=" * 60)
    print("[Summary]")
    print("=" * 60)

    for component, status in results.items():
        status_str = "[OK]" if status else "[FAIL]"
        print(f"{status_str} {component}")

    all_passed = all(results.values())

    if all_passed:
        print("\n[SUCCESS] Data layer check passed")
        return 0
    else:
        print("\n[WARNING] Some checks failed, review above for details")
        return 1


if __name__ == "__main__":
    exit(main())
