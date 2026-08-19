"""长期记忆检索在旧 VARCHAR 与 v2 INT64 schema 间的兼容测试。"""

from app.WealthButler.Service.memoryService import MilvusLongTermStore


class _Model:
    @staticmethod
    def get_collection_name():
        return "memory-test"


class _Connection:
    def __init__(self, customer_type):
        self.customer_type = customer_type
        self.search_kwargs = None

    def describe_collection(self, _collection_name):
        return {"fields": [{"name": "customer_id", "type": self.customer_type}]}

    def search(self, **kwargs):
        self.search_kwargs = kwargs
        return [[]]


def _search(customer_type):
    connection = _Connection(customer_type)
    store = MilvusLongTermStore(
        embedding_fn=lambda _query: [0.0] * 1024,
        model_provider=lambda: _Model,
        connection_getter=lambda: connection,
    )
    assert store.search(42, "test", 5, 0.6) == []
    return connection.search_kwargs


def test_legacy_varchar_customer_filter_is_quoted_and_uses_current_client_parameter():
    kwargs = _search(21)
    assert kwargs["filter"] == 'customer_id == "42"'
    assert "filter_expr" not in kwargs


def test_v2_int_customer_filter_is_unquoted():
    kwargs = _search(5)
    assert kwargs["filter"] == "customer_id == 42"
