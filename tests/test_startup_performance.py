import asyncio
import importlib
import sys
import threading
from types import SimpleNamespace


def test_lifespan_overlaps_scheduler_loading_with_route_registration(monkeypatch):
    main = importlib.import_module("app.WealthButler.main")
    scheduler_load_started = threading.Event()
    routes_may_finish = threading.Event()

    class FakeScheduler:
        def __init__(self):
            self.scheduler = SimpleNamespace(running=False)

        def start(self):
            self.scheduler.running = True

        def shutdown(self, wait=False):
            self.scheduler.running = False

    scheduler = FakeScheduler()

    def load_scheduler():
        scheduler_load_started.set()
        assert routes_may_finish.wait(timeout=1)
        return scheduler

    def register_routes(_app):
        assert scheduler_load_started.wait(timeout=1)
        routes_may_finish.set()

    monkeypatch.setattr(main, "_register_routes_once", register_routes)
    monkeypatch.setattr(main, "_get_scheduler_client", load_scheduler, raising=False)
    monkeypatch.setattr(main, "load_operator_runtime_config", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(main, "_register_scheduler_modules_once", lambda: ())
    monkeypatch.setattr(main, "_assert_unique_scheduler_jobs", lambda _client: None)
    monkeypatch.setitem(
        sys.modules,
        "app.WealthButler.Service.chatService",
        SimpleNamespace(ChatService=SimpleNamespace(configure_operator_runtime=lambda _runtime: None)),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.WealthButler.EventBus.consumer",
        SimpleNamespace(start_all_consumers=lambda: None, stop_all_consumers=lambda: None),
    )
    fake_app = SimpleNamespace(state=SimpleNamespace())

    async def exercise():
        async with main.lifespan(fake_app):
            assert scheduler.scheduler.running is True

    asyncio.run(exercise())

    assert scheduler.scheduler.running is False
