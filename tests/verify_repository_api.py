"""
验证 Repository 和 API 层
测试3个Repository和风控API是否正确创建
"""
import sys
sys.path.insert(0, 'D:/lqh/金融')

print("=" * 60)
print("开始验证 Repository 层...")
print("=" * 60)

try:
    from app.WealthButler.Repository.customerProfileRepository import CustomerProfileRepository
    print("[OK] CustomerProfileRepository 导入成功")
except Exception as e:
    print(f"[FAIL] CustomerProfileRepository 导入失败: {e}")

try:
    from app.WealthButler.Repository.transactionRepository import TransactionRepository
    print("[OK] TransactionRepository 导入成功")
except Exception as e:
    print(f"[FAIL] TransactionRepository 导入失败: {e}")

try:
    from app.WealthButler.Repository.riskAlertRepository import RiskAlertRepository
    print("[OK] RiskAlertRepository 导入成功")
except Exception as e:
    print(f"[FAIL] RiskAlertRepository 导入失败: {e}")

print("\n" + "=" * 60)
print("开始验证 Service 层...")
print("=" * 60)

try:
    from app.WealthButler.Service.riskService import RiskService
    print("[OK] RiskService 导入成功")
except Exception as e:
    print(f"[FAIL] RiskService 导入失败: {e}")

print("\n" + "=" * 60)
print("开始验证 API 层...")
print("=" * 60)

try:
    from app.WealthButler.Api.riskApi import register_risk_api, router
    print("[OK] riskApi 导入成功")

    from fastapi import FastAPI
    from fastapi.openapi.utils import get_openapi

    app = FastAPI()
    register_risk_api(app)

    # 通过 OpenAPI schema 检查路由
    openapi_schema = get_openapi(
        title='Test',
        version='1.0',
        routes=app.routes,
    )

    risk_paths = {path: methods for path, methods in openapi_schema.get('paths', {}).items() if '/api/risk' in path}

    if risk_paths:
        print(f"[OK] 风控API路由注册成功，共 {len(risk_paths)} 个路由:")
        for path, methods in risk_paths.items():
            method_list = ', '.join(methods.keys())
            print(f"  - {method_list:10} {path}")
    else:
        print("[FAIL] 未找到风控API路由")

except Exception as e:
    print(f"[FAIL] riskApi 验证失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("验证完成")
print("=" * 60)
