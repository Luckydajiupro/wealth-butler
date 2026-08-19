import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.manage_historical_dlq import (
    classify,
    summarize,
    terminalize_invalid_pending,
    write_snapshot,
)


def _fields(payload):
    return {"event_type": "suspicious_intent", "payload": json.dumps(payload)}


def test_classify_separates_terminal_schema_errors_from_handler_failures():
    assert classify({"event_type": "suspicious_intent", "payload": "{"}) == "TERMINAL_INVALID_JSON"
    assert classify(_fields({"customer_id": 1})) == "TERMINAL_SCHEMA_INVALID"
    assert classify(_fields({
        "customer_id": 1,
        "session_id": "session-1",
        "intent_type": "fraud",
        "confidence": "0.9",
    })) == "RETAIN_HANDLER_FAILURE"


def test_summarize_counts_duplicate_originals_without_payload_output():
    records = [
        {"classification": "RETAIN_HANDLER_FAILURE", "original_stream": "stream:x",
         "original_msg_id": "1-0", "trace_id": "trace-1"},
        {"classification": "RETAIN_HANDLER_FAILURE", "original_stream": "stream:x",
         "original_msg_id": "1-0", "trace_id": "trace-1"},
    ]
    result = summarize(records)
    assert result["dlq_records"] == 2
    assert result["unique_originals"] == 1
    assert result["duplicate_records"] == 1


def test_snapshot_is_exclusive_and_contains_recovery_payload():
    records = [{"classification": "TERMINAL_SCHEMA_INVALID", "fields": {"payload": "secret"},
                "original_stream": "stream:x", "original_msg_id": "1-0", "trace_id": "trace"}]
    runtime_dir = Path("runtime_artifacts")
    runtime_dir.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=runtime_dir) as directory:
        path, digest = write_snapshot(records, Path(directory))
        assert path.exists()
        assert len(digest) == 64
        assert json.loads(path.read_text(encoding="utf-8"))["records"] == records


class _Redis:
    def __init__(self):
        self.acked = []

    def xpending_range(self, stream, group, min, max, count):
        return [{"message_id": min}]

    def xack(self, stream, group, message_id):
        self.acked.append((stream, group, message_id))
        return 1


def test_terminalize_only_acks_unique_schema_invalid_pending_messages():
    invalid = {"classification": "TERMINAL_SCHEMA_INVALID",
               "original_stream": "stream:suspicious_intent", "original_msg_id": "1-0"}
    retained = {"classification": "RETAIN_HANDLER_FAILURE",
                "original_stream": "stream:suspicious_intent", "original_msg_id": "2-0"}
    client = _Redis()
    assert terminalize_invalid_pending(client, [invalid, invalid, retained]) == 1
    assert client.acked == [("stream:suspicious_intent", "risk_monitor_group", "1-0")]
