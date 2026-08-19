"""
Embedding功能恢复验证脚本

验证项：
1. Ollama服务连接
2. ollama_embedding函数
3. OllamaClient客户端
4. 向量维度正确性

运行方式：
    cd D:/lqh/金融
    python scripts/test_embedding_recovery.py
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_ollama_connection():
    """测试1: Ollama服务连接"""
    print("=" * 60)
    print("测试1: Ollama服务连接")
    print("=" * 60)

    try:
        from app.Base.Client.ollamaClient import ollama_client
        vec = ollama_client.get_embedding('测试文本')

        print(f"[PASS] Ollama服务连接成功")
        print(f"  - 向量维度: {len(vec)}")
        print(f"  - 前3个值: {vec[:3]}")
        return True
    except Exception as e:
        print(f"[FAIL] Ollama服务连接失败: {e}")
        return False


def test_ollama_embedding_function():
    """测试2: ollama_embedding函数"""
    print("\n" + "=" * 60)
    print("测试2: ollama_embedding封装函数")
    print("=" * 60)

    try:
        from app.Base.Ai.llms.ollamaEmbedding import ollama_embedding
        vec = ollama_embedding('客户持仓查询')

        print(f"[PASS] ollama_embedding函数正常")
        print(f"  - 向量维度: {len(vec)}")
        print(f"  - 样本值: [{vec[0]:.4f}, {vec[1]:.4f}, {vec[2]:.4f}]")

        # 验证维度
        if len(vec) == 1024:
            print(f"[PASS] 向量维度正确 (1024维)")
            return True
        else:
            print(f"[FAIL] 向量维度错误: 期望1024, 实际{len(vec)}")
            return False
    except Exception as e:
        print(f"[FAIL] ollama_embedding函数失败: {e}")
        return False


def test_config_loading():
    """测试3: 配置加载"""
    print("\n" + "=" * 60)
    print("测试3: Ollama配置加载")
    print("=" * 60)

    try:
        from app.Base.Config.setting import settings

        print(f"[PASS] 配置加载成功")
        print(f"  - OLLAMA_BASE_URL: {settings.ollama.base_url}")
        print(f"  - OLLAMA_EMBEDDING_MODEL: {settings.ollama.embedding_model}")

        # 验证配置
        if settings.ollama.base_url and settings.ollama.embedding_model:
            return True
        else:
            print(f"[FAIL] 配置不完整")
            return False
    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        return False


def test_vector_consistency():
    """测试4: 向量一致性（相同文本应产生相同向量）"""
    print("\n" + "=" * 60)
    print("测试4: 向量一致性验证")
    print("=" * 60)

    try:
        from app.Base.Ai.llms.ollamaEmbedding import ollama_embedding

        text = "测试向量一致性"
        vec1 = ollama_embedding(text)
        vec2 = ollama_embedding(text)

        # 计算差异
        diff = sum(abs(a - b) for a, b in zip(vec1, vec2))

        if diff < 0.0001:  # 允许极小的浮点误差
            print(f"[PASS] 向量一致性验证通过")
            print(f"  - 两次生成向量差异: {diff:.8f}")
            return True
        else:
            print(f"[FAIL] 向量不一致: 差异={diff}")
            return False
    except Exception as e:
        print(f"[FAIL] 向量一致性测试失败: {e}")
        return False


def main():
    """主测试流程"""
    print("\n" + "=" * 60)
    print("Embedding功能恢复验证")
    print("=" * 60)
    print()

    results = []

    # 执行所有测试
    results.append(("Ollama服务连接", test_ollama_connection()))
    results.append(("ollama_embedding函数", test_ollama_embedding_function()))
    results.append(("配置加载", test_config_loading()))
    results.append(("向量一致性", test_vector_consistency()))

    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} {test_name}")

    print()
    print(f"通过: {passed}/{total}")

    if passed == total:
        print("\n✓ 所有测试通过！Embedding功能已完全恢复。")
        return 0
    else:
        print("\n✗ 部分测试失败，请检查Ollama服务状态。")
        return 1


if __name__ == '__main__':
    exit(main())
