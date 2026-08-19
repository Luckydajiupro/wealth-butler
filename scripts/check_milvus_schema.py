"""只读输出三个业务知识集合的 Milvus Schema。"""

from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2


def main() -> None:
    """使用项目统一连接逐个读取集合定义。"""
    connection = FaqCollectionModelV2.get_connection()
    collections = (
        ("FAQ", FaqCollectionModelV2),
        ("Product", ProductCollectionModelV2),
        ("Policy", PolicyCollectionModelV2),
    )
    for label, model in collections:
        print(f"=== {label} Collection Schema ===")
        print(connection.describe_collection(model.get_collection_name()))


if __name__ == "__main__":
    main()
