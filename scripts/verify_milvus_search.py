"""Milvus检索功能验证脚本

验证三个集合的search()方法是否正常工作：
- fin_faq_collection
- fin_product_collection_v2
- fin_policy_collection_v2

使用方式：
    python scripts/verify_milvus_search.py
"""

import sys
import os
import io
from typing import List, Dict, Any

# 设置标准输出为UTF-8编码（解决Windows控制台中文显示问题）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2


def print_section(title: str):
    """打印章节标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_collection_basic_info(model_class, collection_name: str) -> Dict[str, Any]:
    """测试集合基础信息"""
    result = {
        'collection': collection_name,
        'exists': False,
        'count': 0,
        'has_data': False
    }

    try:
        connection = model_class.get_connection()
        result['exists'] = connection.has_collection(collection_name)

        if result['exists']:
            result['count'] = model_class.count()
            result['has_data'] = result['count'] > 0

        return result
    except Exception as e:
        result['error'] = str(e)
        return result


def test_faq_search() -> Dict[str, Any]:
    """测试FAQ集合的检索功能"""
    print_section("1. 测试 FAQ 集合检索")

    result = {
        'collection': 'fin_faq_collection',
        'search_successful': False,
        'sample_results': 0,
        'issues': []
    }

    try:
        # 检查集合基础信息
        info = test_collection_basic_info(FaqCollectionModelV2, 'fin_faq_collection')
        print(f"\n集合名称: {info['collection']}")
        print(f"集合存在: {info['exists']}")
        print(f"数据量: {info['count']}")

        if not info['exists']:
            result['issues'].append("集合不存在")
            print("[X] 集合不存在")
            return result

        if not info['has_data']:
            result['issues'].append("集合无数据")
            print("[!] 集合存在但无数据")
            return result

        # 执行检索测试（使用零向量作为测试查询）
        print("\n执行检索测试...")
        test_vector = [0.0] * 1024  # bge-m3模型是1024维

        search_results = FaqCollectionModelV2.search(
            data=test_vector,
            limit=3,
            output_fields=["id", "text", "metadata"]
        )

        result['search_successful'] = True
        result['sample_results'] = len(search_results)

        print(f"[OK] 检索成功，返回 {len(search_results)} 条结果")

        # 打印前3条结果
        if search_results:
            print("\n样本结果（前3条）：")
            for i, hit in enumerate(search_results[:3], 1):
                print(f"\n  [{i}] ID: {hit.get('id', 'N/A')}")
                print(f"      Distance: {hit.get('distance', 'N/A'):.4f}")
                text = hit.get('text', '')[:100] if hit.get('text') else 'N/A'
                print(f"      Text: {text}...")

        return result

    except Exception as e:
        result['issues'].append(f"检索失败: {str(e)}")
        print(f"[X] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        return result


def test_product_search() -> Dict[str, Any]:
    """测试产品集合的检索功能"""
    print_section("2. 测试产品集合检索")

    result = {
        'collection': 'fin_product_collection',
        'search_successful': False,
        'sample_results': 0,
        'issues': []
    }

    try:
        # 检查集合基础信息
        info = test_collection_basic_info(ProductCollectionModelV2, 'fin_product_collection')
        print(f"\n集合名称: {info['collection']}")
        print(f"集合存在: {info['exists']}")
        print(f"数据量: {info['count']}")

        if not info['exists']:
            result['issues'].append("集合不存在")
            print("[X] 集合不存在")
            return result

        if not info['has_data']:
            result['issues'].append("集合无数据")
            print("[!] 集合存在但无数据")
            return result

        # 执行检索测试
        print("\n执行检索测试...")
        test_vector = [0.0] * 1024

        search_results = ProductCollectionModelV2.search(
            data=test_vector,
            limit=3,
            output_fields=["id", "text", "metadata"]
        )

        result['search_successful'] = True
        result['sample_results'] = len(search_results)

        print(f"[OK] 检索成功，返回 {len(search_results)} 条结果")

        # 打印前3条结果
        if search_results:
            print("\n样本结果（前3条）：")
            for i, hit in enumerate(search_results[:3], 1):
                print(f"\n  [{i}] ID: {hit.get('id', 'N/A')}")
                print(f"      Distance: {hit.get('distance', 'N/A'):.4f}")
                text = hit.get('text', '')[:100] if hit.get('text') else 'N/A'
                print(f"      Text: {text}...")

        return result

    except Exception as e:
        result['issues'].append(f"检索失败: {str(e)}")
        print(f"[X] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        return result


def test_policy_search() -> Dict[str, Any]:
    """测试政策集合的检索功能"""
    print_section("3. 测试政策法规集合检索")

    result = {
        'collection': 'fin_policy_collection',
        'search_successful': False,
        'sample_results': 0,
        'issues': []
    }

    try:
        # 检查集合基础信息
        info = test_collection_basic_info(PolicyCollectionModelV2, 'fin_policy_collection')
        print(f"\n集合名称: {info['collection']}")
        print(f"集合存在: {info['exists']}")
        print(f"数据量: {info['count']}")

        if not info['exists']:
            result['issues'].append("集合不存在")
            print("[X] 集合不存在")
            return result

        if not info['has_data']:
            result['issues'].append("集合无数据")
            print("[!] 集合存在但无数据")
            return result

        # 执行检索测试
        print("\n执行检索测试...")
        test_vector = [0.0] * 1024

        search_results = PolicyCollectionModelV2.search(
            data=test_vector,
            limit=3,
            output_fields=["id", "text", "metadata"]
        )

        result['search_successful'] = True
        result['sample_results'] = len(search_results)

        print(f"[OK] 检索成功，返回 {len(search_results)} 条结果")

        # 打印前3条结果
        if search_results:
            print("\n样本结果（前3条）：")
            for i, hit in enumerate(search_results[:3], 1):
                print(f"\n  [{i}] ID: {hit.get('id', 'N/A')}")
                print(f"      Distance: {hit.get('distance', 'N/A'):.4f}")
                text = hit.get('text', '')[:100] if hit.get('text') else 'N/A'
                print(f"      Text: {text}...")

        return result

    except Exception as e:
        result['issues'].append(f"检索失败: {str(e)}")
        print(f"[X] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        return result


def main():
    """主函数"""
    print("\n" + "╔" + "=" * 68 + "╗")
    print("║" + " " * 20 + "Milvus 检索功能验证" + " " * 20 + "║")
    print("╚" + "=" * 68 + "╝")

    # 运行所有测试
    results = []
    results.append(test_faq_search())
    results.append(test_product_search())
    results.append(test_policy_search())

    # 输出汇总报告
    print_section("验证汇总")

    all_passed = True
    for result in results:
        status = "[OK] 通过" if result['search_successful'] else "[X] 失败"
        print(f"\n{result['collection']}: {status}")

        if result['search_successful']:
            print(f"  - 返回结果数: {result['sample_results']}")
        else:
            all_passed = False
            for issue in result['issues']:
                print(f"  - 问题: {issue}")

    print("\n" + "=" * 70)
    if all_passed:
        print("[SUCCESS] 所有Milvus检索功能正常")
    else:
        print("[WARNING] 部分Milvus检索功能存在问题，请查看上述详情")
    print("=" * 70 + "\n")

    return results


if __name__ == '__main__':
    results = main()
