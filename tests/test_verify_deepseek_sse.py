from scripts.verify_deepseek_sse import _measure_request, percentile, summarize_samples


def test_percentile_uses_linear_interpolation():
    values = [100.0, 200.0, 300.0, 400.0, 500.0]

    assert percentile(values, 50) == 300.0
    assert percentile(values, 95) == 480.0


def test_summary_reports_success_rate_and_excludes_failed_latency():
    samples = [
        {
            "kind": "cold",
            "success": True,
            "first_frame_ms": 100.0,
            "completion_ms": 200.0,
        },
        {
            "kind": "cold",
            "success": False,
            "first_frame_ms": None,
            "completion_ms": 900.0,
        },
        {
            "kind": "hot",
            "success": True,
            "first_frame_ms": 50.0,
            "completion_ms": 80.0,
        },
    ]

    summary = summarize_samples(samples)

    assert summary["cold"] == {
        "sample_count": 2,
        "success_count": 1,
        "success_rate_percent": 50.0,
        "first_frame_ms": {"p50": 100.0, "p95": 100.0},
        "completion_ms": {"p50": 200.0, "p95": 200.0},
    }
    assert summary["hot"]["success_rate_percent"] == 100.0


def test_request_measurement_never_stores_sse_body():
    class Response:
        status_code = 200
        headers = {"content-type": "text/event-stream; charset=utf-8"}

        def iter_lines(self, decode_unicode=False):
            return iter((b"data: secret-model-body", b"", b"data: second-secret-chunk"))

        def close(self):
            return None

    class Session:
        def post(self, *args, **kwargs):
            return Response()

    sample = _measure_request(
        Session(),
        "http://127.0.0.1:8010",
        "in-memory-token",
        1.0,
        "hot",
        1,
        1,
    )

    assert sample["success"] is True
    assert sample["frame_count"] == 2
    assert "secret-model-body" not in str(sample)
    assert "in-memory-token" not in str(sample)
