"""正式入口冷启动只读分段探针。

用法：python tests/startup_cold_probe.py --runs 3
不会进入 FastAPI lifespan，不启动 EventBus、scheduler 或外部 LLM 请求。
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time


RESULT_PREFIX = "STARTUP_PROFILE_JSON="
REPO_ROOT = Path(__file__).resolve().parents[1]


def _measure_child(mode: str) -> dict[str, float | int | str]:
    sys.path.insert(0, str(REPO_ROOT))
    started = time.perf_counter()
    import app.WealthButler.main as main

    imported = time.perf_counter()
    if mode == "parallel":
        with ThreadPoolExecutor(max_workers=1) as pool:
            scheduler_future = pool.submit(main._get_scheduler_client)
            main._register_routes_once(main.app)
            scheduler_client = scheduler_future.result()
    else:
        main._register_routes_once(main.app)
        scheduler_client = main._get_scheduler_client()
    routes_ready = time.perf_counter()

    scheduler_modules = main._register_scheduler_modules_once()
    main._assert_unique_scheduler_jobs(scheduler_client)
    scheduler_ready = time.perf_counter()
    return {
        "mode": mode,
        "import_main_ms": round((imported - started) * 1000, 1),
        "routes_scheduler_ms": round((routes_ready - imported) * 1000, 1),
        "scheduler_modules_ms": round((scheduler_ready - routes_ready) * 1000, 1),
        "scheduler_module_count": len(scheduler_modules),
        "total_ms": round((scheduler_ready - started) * 1000, 1),
    }


def _run_fresh_processes(count: int) -> dict:
    runs = {"sequential": [], "parallel": []}
    script = str(Path(__file__).resolve())
    for index in range(count):
        modes = ("sequential", "parallel") if index % 2 == 0 else ("parallel", "sequential")
        for mode in modes:
            completed = subprocess.run(
                [sys.executable, script, "--child", "--mode", mode],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            line = next(
                item for item in completed.stdout.splitlines()
                if item.startswith(RESULT_PREFIX)
            )
            runs[mode].append(json.loads(line.removeprefix(RESULT_PREFIX)))
    sequential_median = statistics.median(run["total_ms"] for run in runs["sequential"])
    parallel_median = statistics.median(run["total_ms"] for run in runs["parallel"])
    saved_ms = sequential_median - parallel_median
    return {
        "runs": runs,
        "median_sequential_total_ms": round(sequential_median, 1),
        "median_parallel_total_ms": round(parallel_median, 1),
        "median_saved_ms": round(saved_ms, 1),
        "median_saved_percent": round(saved_ms / sequential_median * 100, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--mode", choices=("sequential", "parallel"), default="parallel", help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    if args.child:
        print(RESULT_PREFIX + json.dumps(_measure_child(args.mode), ensure_ascii=False))
        return
    if args.runs <= 0:
        parser.error("--runs 必须为正整数")
    print(json.dumps(_run_fresh_processes(args.runs), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
