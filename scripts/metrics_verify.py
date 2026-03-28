#!/usr/bin/env python3
# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""End-to-end metrics verification against Prometheus.

Queries the Prometheus Query API to verify that GenAI metrics
are being emitted correctly.

Usage:
    # Verify metrics exist for a service
    python metrics_verify.py --expect-metrics gen_ai.client.operation.duration

    # List all available metrics
    python metrics_verify.py --list-metrics

    # Custom Prometheus URL
    python metrics_verify.py --prometheus-url http://localhost:9090 --expect-metrics ...

Dependencies:
    None beyond stdlib (uses urllib).

Note:
    OTel metrics exported to Prometheus have their names transformed:
    - dots become underscores: gen_ai.client.operation.duration -> gen_ai_client_operation_duration
    - units are appended: gen_ai_client_operation_duration_seconds
    - histogram creates _bucket, _count, _sum suffixes
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.request import urlopen, Request
from urllib.error import URLError


PROMETHEUS_DEFAULT_URL = "http://localhost:9090"

# GenAI semconv metrics and their Prometheus names.
# OTel -> Prometheus name mapping: dots->underscores, unit suffix added.
GENAI_METRICS = {
    "gen_ai.client.operation.duration": {
        "prometheus_name": "gen_ai_client_operation_duration_seconds",
        "type": "histogram",
        "requirement": "Required",
        "expected_attrs": ["gen_ai_operation_name"],
    },
    "gen_ai.client.token.usage": {
        "prometheus_name": "gen_ai_client_token_usage",
        "type": "histogram",
        "requirement": "Recommended",
        "expected_attrs": ["gen_ai_operation_name", "gen_ai_token_type"],
    },
}


def _prom_get(prom_url: str, path: str) -> dict:
    """GET request to Prometheus Query API."""
    url = f"{prom_url}{path}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except URLError as e:
        print(f"Error connecting to Prometheus at {prom_url}: {e}", file=sys.stderr)
        print("Is Prometheus running? Start it with: scripts/prometheus.sh start", file=sys.stderr)
        sys.exit(1)


def list_metrics(prom_url: str) -> list[str]:
    """List all metric names in Prometheus."""
    data = _prom_get(prom_url, "/api/v1/label/__name__/values")
    return data.get("data", [])


def query_metric(prom_url: str, metric_name: str) -> list[dict]:
    """Query a metric's current values.

    Uses last_over_time to handle stale targets (e.g., E2E process exited
    but data was scraped and persisted).
    """
    # Try instant query first
    data = _prom_get(prom_url, f"/api/v1/query?query={metric_name}")
    results = data.get("data", {}).get("result", [])
    if results:
        return results

    # Fall back to last_over_time for stale/exited targets
    query = f"last_over_time({metric_name}[5m])"
    from urllib.parse import quote
    data = _prom_get(prom_url, f"/api/v1/query?query={quote(query)}")
    return data.get("data", {}).get("result", [])


def _check(ok: bool, msg: str, errors: list[str]) -> None:
    if ok:
        print(f"  PASS: {msg}")
    else:
        print(f"  FAIL: {msg}")
        errors.append(msg)


def verify_metrics(
    prom_url: str,
    expect_metrics: list[str],
) -> list[str]:
    """Verify expected GenAI metrics exist in Prometheus."""
    errors: list[str] = []

    print(f"\n{'='*60}")
    print(f"Metrics Verification (Prometheus)")
    print(f"{'='*60}")

    # Get all available metric names
    all_metrics = list_metrics(prom_url)
    genai_metrics = [m for m in all_metrics if "gen_ai" in m]

    print(f"\n  Available gen_ai metrics: {len(genai_metrics)}")
    for m in sorted(genai_metrics):
        print(f"    - {m}")

    if not genai_metrics:
        print("\n  WARN: No gen_ai metrics found. Possible causes:")
        print("    - Prometheus hasn't scraped the exporter yet (wait a few seconds)")
        print("    - The E2E test didn't configure a Prometheus exporter")
        print("    - The instrumentation doesn't record metrics yet")

    # Check each expected metric
    for otel_name in expect_metrics:
        info = GENAI_METRICS.get(otel_name)
        if not info:
            print(f"\n  WARN: Unknown metric '{otel_name}', skipping")
            continue

        prom_name = info["prometheus_name"]
        print(f"\n  --- Metric: {otel_name} ---")
        print(f"      Prometheus name: {prom_name}")
        print(f"      Requirement: {info['requirement']}")

        # For histograms, check _count suffix
        check_name = f"{prom_name}_count" if info["type"] == "histogram" else prom_name

        _check(
            check_name in all_metrics,
            f"Metric {check_name} exists in Prometheus",
            errors,
        )

        if check_name in all_metrics:
            results = query_metric(prom_url, check_name)
            _check(
                len(results) > 0,
                f"Metric {check_name} has data points (found {len(results)})",
                errors,
            )

            # Check expected attributes (labels)
            for result in results:
                labels = result.get("metric", {})
                value = result.get("value", [None, None])[1]
                print(f"      Labels: {dict(labels)}")
                print(f"      Value: {value}")

                for attr in info["expected_attrs"]:
                    _check(
                        attr in labels,
                        f"Label '{attr}' present on {prom_name}",
                        errors,
                    )

            # For histograms, also check _sum to verify values are plausible
            if info["type"] == "histogram":
                sum_name = f"{prom_name}_sum"
                sum_results = query_metric(prom_url, sum_name)
                for r in sum_results:
                    val = float(r.get("value", [0, 0])[1])
                    _check(
                        val > 0,
                        f"{sum_name} > 0 (got {val:.6f})",
                        errors,
                    )

    # Summary
    print(f"\n{'='*60}")
    if errors:
        print(f"FAILED: {len(errors)} issue(s)")
    else:
        print("ALL CHECKS PASSED")
    print(f"{'='*60}\n")

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Verify GenAI metrics in Prometheus"
    )
    parser.add_argument(
        "--expect-metrics", "-e",
        help="Comma-separated list of OTel metric names to verify "
             "(e.g., gen_ai.client.operation.duration,gen_ai.client.token.usage)",
    )
    parser.add_argument(
        "--prometheus-url", "-p",
        default=PROMETHEUS_DEFAULT_URL,
        help=f"Prometheus URL (default: {PROMETHEUS_DEFAULT_URL})",
    )
    parser.add_argument(
        "--list-metrics",
        action="store_true",
        help="List all available metrics and exit",
    )

    args = parser.parse_args()

    if args.list_metrics:
        metrics = list_metrics(args.prometheus_url)
        genai = [m for m in metrics if "gen_ai" in m]
        print("GenAI metrics in Prometheus:")
        for m in sorted(genai):
            print(f"  - {m}")
        if not genai:
            print("  (none found)")
        return

    if not args.expect_metrics:
        parser.error("--expect-metrics or --list-metrics is required")

    expect = [m.strip() for m in args.expect_metrics.split(",")]
    errors = verify_metrics(args.prometheus_url, expect)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
