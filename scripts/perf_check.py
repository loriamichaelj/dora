#!/usr/bin/env python3
"""Performance check for the DORA summary (§12): org-wide, 90-day window.

Target: p95 < 500 ms locally with ~100k deployments (`make seed-large`).
Standard library only and Python 3.10+ compatible (the host python3), so it runs
anywhere without a virtualenv.

    python3 scripts/perf_check.py [--api-url http://localhost:8080] [--requests 50]

Exits 1 if p95 misses the target.
"""

import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TARGET_P95_MS = 500.0


def timed_get(url: str) -> tuple[float, dict[str, object]]:
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310  # local, known URL
        body = json.load(resp)
    return (time.perf_counter() - started) * 1000, body


def percentile(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    rank = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered) + 0.5) - 1))
    return ordered[rank]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--api-url", default=os.environ.get("DORA_API_URL", "http://localhost:8080"))
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=5)
    args = parser.parse_args()

    to = datetime.now(timezone.utc)
    window = {"from": (to - timedelta(days=90)).isoformat(), "to": to.isoformat()}
    base = args.api_url.rstrip("/")
    endpoints = {
        "summary": f"{base}/api/v1/metrics/dora?{urllib.parse.urlencode(window)}",
        "timeseries": f"{base}/api/v1/metrics/dora/timeseries?"
        + urllib.parse.urlencode({**window, "bucket": "week"}),
    }

    summary_p95 = 0.0
    for name, url in endpoints.items():
        for _ in range(args.warmup):
            timed_get(url)
        samples = []
        for _ in range(args.requests):
            ms, body = timed_get(url)
            samples.append(ms)
        p95 = percentile(samples, 95)
        extra = ""
        if name == "summary":
            summary_p95 = p95
            freq = body["deployment_frequency"]
            assert isinstance(freq, dict)
            extra = f"  counted_deployments={freq['count']}"
        print(
            f"{name:<10} n={len(samples)}  p50={statistics.median(samples):7.1f} ms  "
            f"p95={p95:7.1f} ms  max={max(samples):7.1f} ms{extra}"
        )

    verdict = "PASS" if summary_p95 < TARGET_P95_MS else "FAIL"
    print(f"{verdict}: summary p95 {summary_p95:.1f} ms (target < {TARGET_P95_MS:.0f} ms)")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
