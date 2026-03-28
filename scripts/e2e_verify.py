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

"""End-to-end trace verification against Jaeger.

Queries the Jaeger Query API to retrieve traces and verify that spans
match the expected GenAI semantic conventions.

Usage:
    # Verify traces for a service, checking GenAI semconv compliance
    python e2e_verify.py --service my-genai-app

    # Verify a specific trace by ID
    python e2e_verify.py --trace-id abc123def456

    # Verify with specific expected operations
    python e2e_verify.py --service my-genai-app --expect-operations chat,embeddings

    # Custom Jaeger URL
    python e2e_verify.py --service my-app --jaeger-url http://localhost:16686

Dependencies:
    pip install requests  (only stdlib + requests needed)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError


JAEGER_DEFAULT_URL = "http://localhost:16686"

VALID_OPERATIONS = {
    "chat", "generate_content", "text_completion", "embeddings",
    "retrieval", "execute_tool", "create_agent", "invoke_agent",
}

# Attributes that MUST exist on inference spans (chat, embeddings, etc.)
REQUIRED_INFERENCE_ATTRS = {
    "gen_ai.operation.name",
}

RECOMMENDED_INFERENCE_ATTRS = {
    "gen_ai.provider.name",
    "gen_ai.request.model",
}

# Attributes for specific operations
OPERATION_SPECIFIC_ATTRS = {
    "execute_tool": {"gen_ai.tool.name"},
    "invoke_agent": {"gen_ai.agent.name"},
    "create_agent": {"gen_ai.agent.name"},
}


def _jaeger_get(jaeger_url: str, path: str) -> dict:
    """GET request to Jaeger Query API."""
    url = f"{jaeger_url}{path}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except URLError as e:
        print(f"Error connecting to Jaeger at {jaeger_url}: {e}", file=sys.stderr)
        print("Is Jaeger running? Start it with: scripts/jaeger.sh start", file=sys.stderr)
        sys.exit(1)


def get_services(jaeger_url: str) -> list[str]:
    """List all services that have reported traces."""
    data = _jaeger_get(jaeger_url, "/api/services")
    return data.get("data", [])


def get_traces(jaeger_url: str, service: str, limit: int = 20) -> list[dict]:
    """Get recent traces for a service."""
    data = _jaeger_get(jaeger_url, f"/api/traces?service={service}&limit={limit}")
    return data.get("data", [])


def get_trace(jaeger_url: str, trace_id: str) -> dict | None:
    """Get a specific trace by ID."""
    data = _jaeger_get(jaeger_url, f"/api/traces/{trace_id}")
    traces = data.get("data", [])
    return traces[0] if traces else None


def _extract_span_tags(span: dict) -> dict[str, Any]:
    """Extract span tags into a simple dict."""
    tags = {}
    for tag in span.get("tags", []):
        tags[tag["key"]] = tag["value"]
    return tags


def _check(ok: bool, msg: str, errors: list[str]) -> None:
    if ok:
        print(f"  PASS: {msg}")
    else:
        print(f"  FAIL: {msg}")
        errors.append(msg)


def verify_span(span: dict, errors: list[str]) -> None:
    """Verify a single span against GenAI semconv."""
    tags = _extract_span_tags(span)
    span_name = span.get("operationName", "")
    span_id = span.get("spanID", "?")

    operation = tags.get("gen_ai.operation.name")

    print(f"\n  --- Span: {span_name} (id={span_id[:8]}...) ---")
    print(f"      operation={operation}, kind={tags.get('span.kind', '?')}")

    # 1. operation.name must be set and valid
    _check(
        operation is not None,
        f"[{span_name}] gen_ai.operation.name is set",
        errors,
    )

    if operation and operation in VALID_OPERATIONS:
        _check(True, f"[{span_name}] operation '{operation}' is a valid GenAI operation", errors)
    elif operation:
        # Not a standard GenAI operation — might be a framework-specific span, just warn
        print(f"  WARN: [{span_name}] operation '{operation}' is not a standard GenAI operation")

    # 2. Inference operations need provider + model
    if operation in ("chat", "generate_content", "text_completion", "embeddings"):
        _check(
            "gen_ai.provider.name" in tags or "gen_ai.system" in tags,
            f"[{span_name}] gen_ai.provider.name is set",
            errors,
        )
        _check(
            "gen_ai.request.model" in tags,
            f"[{span_name}] gen_ai.request.model is set",
            errors,
        )

        # Token usage (recommended, not required)
        if "gen_ai.usage.input_tokens" in tags:
            print(f"      input_tokens={tags['gen_ai.usage.input_tokens']}")
        else:
            print(f"  WARN: [{span_name}] gen_ai.usage.input_tokens not set")
        if "gen_ai.usage.output_tokens" in tags:
            print(f"      output_tokens={tags['gen_ai.usage.output_tokens']}")
        else:
            print(f"  WARN: [{span_name}] gen_ai.usage.output_tokens not set")

        # Content capture (opt-in, validate format if present)
        for msg_attr in ("gen_ai.input.messages", "gen_ai.output.messages"):
            if msg_attr not in tags:
                continue
            val = str(tags[msg_attr])
            preview = val[:80] + ("..." if len(val) > 80 else "")
            print(f"      {msg_attr.split('.')[-1]}={preview}")

            # Must be valid JSON, not a Python repr like <object at 0x...>
            is_python_repr = val.startswith("<") and "object at" in val
            _check(
                not is_python_repr,
                f"[{span_name}] {msg_attr} is structured data, not Python repr",
                errors,
            )
            if not is_python_repr:
                try:
                    json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    # Not strict JSON — could be a plain string, which is OK
                    # but warn if it looks like it should be JSON
                    if val.startswith("[") or val.startswith("{"):
                        print(f"  WARN: [{span_name}] {msg_attr} looks like JSON but fails to parse")

    # 3. Operation-specific attributes
    kind = tags.get("span.kind", "")
    if operation in OPERATION_SPECIFIC_ATTRS:
        for attr in OPERATION_SPECIFIC_ATTRS[operation]:
            if attr in tags:
                _check(True, f"[{span_name}] {attr} is set for {operation}", errors)
            elif kind == "server":
                # SERVER spans may not have access to all metadata (e.g.,
                # server-side handler may not know the agent name)
                print(f"  WARN: [{span_name}] {attr} not set on SERVER {operation} span (acceptable)")
            else:
                _check(False, f"[{span_name}] {attr} is set for {operation}", errors)

    # 4. Error spans should have error.type
    if tags.get("otel.status_code") == "ERROR":
        _check(
            "error.type" in tags or "error" in tags,
            f"[{span_name}] error span has error.type or error tag",
            errors,
        )

    # 5. Span kind check
    if operation in ("execute_tool",):
        # Should be internal (or unset, which Jaeger shows as "unspecified")
        if kind and kind not in ("internal", "unspecified"):
            print(f"  WARN: [{span_name}] execute_tool should be INTERNAL, got {kind}")
    elif operation in ("chat", "embeddings", "generate_content", "text_completion"):
        if kind and kind not in ("client",):
            print(f"  WARN: [{span_name}] {operation} should be CLIENT, got {kind}")


def verify_trace_hierarchy(trace: dict, errors: list[str]) -> None:
    """Verify parent-child relationships and detect broken chains."""
    spans = trace.get("spans", [])
    span_map = {s["spanID"]: s for s in spans}
    trace_id = trace.get("traceID", "?")[:16]

    print(f"\n  --- Trace Chain Verification ({len(spans)} spans) ---")

    roots = []
    orphans = []
    for span in spans:
        refs = span.get("references", [])
        parent_id = None
        for ref in refs:
            if ref.get("refType") == "CHILD_OF":
                parent_id = ref.get("spanID")
                break

        if parent_id is None:
            roots.append(span)
        elif parent_id not in span_map:
            # Parent span ID referenced but not present in this trace
            orphans.append(span)

    # Print tree
    def _print_tree(span_id, depth=0):
        sp = span_map.get(span_id)
        if not sp:
            return
        name = sp.get("operationName", "?")
        tags = _extract_span_tags(sp)
        op = tags.get("gen_ai.operation.name", "")
        indent = "    " + "  " * depth
        print(f"{indent}└── {name} [{op}] (id={span_id[:8]})")
        for child in spans:
            for ref in child.get("references", []):
                if ref.get("refType") == "CHILD_OF" and ref.get("spanID") == span_id:
                    _print_tree(child["spanID"], depth + 1)

    for root in roots:
        _print_tree(root["spanID"])

    # Checks
    _check(
        len(roots) >= 1,
        f"Trace has at least one root span (found {len(roots)})",
        errors,
    )

    _check(
        len(roots) <= 1,
        f"Trace has exactly one root span (found {len(roots)} — "
        f"multiple roots suggest broken context propagation)",
        errors,
    )

    _check(
        len(orphans) == 0,
        f"No orphan spans (spans referencing a parent not in this trace): "
        f"found {len(orphans)}",
        errors,
    )
    for orphan in orphans:
        name = orphan.get("operationName", "?")
        refs = orphan.get("references", [])
        parent_ref = next(
            (r.get("spanID", "?") for r in refs if r.get("refType") == "CHILD_OF"),
            "?",
        )
        print(f"    ORPHAN: {name} references parent {parent_ref[:8]} which is missing")

    # Verify all spans share the same traceID
    trace_ids = {s.get("traceID") for s in spans}
    _check(
        len(trace_ids) == 1,
        f"All spans share the same traceID (found {len(trace_ids)} distinct IDs)",
        errors,
    )


def verify_resource_attrs(trace: dict, errors: list[str]) -> None:
    """Verify resource-level attributes on the trace."""
    processes = trace.get("processes", {})
    if not processes:
        print("\n  WARN: No process/resource info found in trace")
        return

    print("\n  --- Resource Attributes ---")
    for pid, proc in processes.items():
        service_name = proc.get("serviceName", "")
        tags = {t["key"]: t["value"] for t in proc.get("tags", [])}

        print(f"    Process {pid}: service.name={service_name}")
        for k, v in sorted(tags.items()):
            print(f"      {k} = {v}")

        _check(
            bool(service_name) and service_name != "unknown_service",
            f"service.name is set and meaningful (got '{service_name}')",
            errors,
        )

        # Check for telemetry SDK info (recommended)
        has_sdk_info = any(
            k.startswith("telemetry.sdk.") for k in tags
        )
        if has_sdk_info:
            print(f"    PASS: telemetry.sdk.* attributes present")
        else:
            print(f"    WARN: telemetry.sdk.* attributes missing (recommended)")


def wait_for_traces(jaeger_url: str, service: str, timeout: int = 15) -> list[dict]:
    """Wait for traces to appear in Jaeger (export can be async)."""
    print(f"Waiting for traces from service '{service}'...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        traces = get_traces(jaeger_url, service, limit=5)
        if traces:
            print(f"Found {len(traces)} trace(s).")
            return traces
        time.sleep(1)
    print(f"No traces found within {timeout}s.", file=sys.stderr)
    return []


def verify_service(jaeger_url: str, service: str,
                   expect_operations: set[str] | None = None,
                   wait: bool = True) -> list[str]:
    """Full verification of traces from a service."""
    errors: list[str] = []

    print(f"\n{'='*60}")
    print(f"E2E Verification: service={service}")
    print(f"{'='*60}")

    if wait:
        traces = wait_for_traces(jaeger_url, service)
    else:
        traces = get_traces(jaeger_url, service)

    if not traces:
        errors.append(f"No traces found for service '{service}'")
        print(f"\nFAILED: No traces found")
        return errors

    # Verify each trace
    found_operations: set[str] = set()
    for trace in traces:
        spans = trace.get("spans", [])
        print(f"\n  Trace: {trace.get('traceID', '?')[:16]}... ({len(spans)} spans)")

        for span in spans:
            verify_span(span, errors)
            tags = _extract_span_tags(span)
            op = tags.get("gen_ai.operation.name")
            if op:
                found_operations.add(op)

        if len(spans) > 1:
            verify_trace_hierarchy(trace, errors)

        verify_resource_attrs(trace, errors)

    # Check expected operations
    if expect_operations:
        for op in expect_operations:
            _check(
                op in found_operations,
                f"Expected operation '{op}' found in traces",
                errors,
            )

    # Summary
    print(f"\n{'='*60}")
    print(f"Operations found: {sorted(found_operations)}")
    if errors:
        print(f"FAILED: {len(errors)} issue(s)")
    else:
        print("ALL CHECKS PASSED")
    print(f"{'='*60}\n")

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Verify GenAI traces in Jaeger against OTel semconv"
    )
    parser.add_argument(
        "--service", "-s",
        help="Service name to query traces for",
    )
    parser.add_argument(
        "--trace-id", "-t",
        help="Specific trace ID to verify",
    )
    parser.add_argument(
        "--expect-operations", "-e",
        help="Comma-separated list of expected operation names",
    )
    parser.add_argument(
        "--jaeger-url", "-j",
        default=JAEGER_DEFAULT_URL,
        help=f"Jaeger Query API URL (default: {JAEGER_DEFAULT_URL})",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for traces to appear",
    )
    parser.add_argument(
        "--list-services",
        action="store_true",
        help="List all services and exit",
    )

    args = parser.parse_args()

    if args.list_services:
        services = get_services(args.jaeger_url)
        print("Services with traces:")
        for s in sorted(services):
            print(f"  - {s}")
        return

    if args.trace_id:
        trace = get_trace(args.jaeger_url, args.trace_id)
        if not trace:
            print(f"Trace {args.trace_id} not found", file=sys.stderr)
            sys.exit(1)
        errors: list[str] = []
        for span in trace.get("spans", []):
            verify_span(span, errors)
        verify_trace_hierarchy(trace, errors)
        sys.exit(1 if errors else 0)

    if not args.service:
        parser.error("--service or --trace-id is required")

    expect_ops = None
    if args.expect_operations:
        expect_ops = set(args.expect_operations.split(","))

    errors = verify_service(
        args.jaeger_url,
        args.service,
        expect_operations=expect_ops,
        wait=not args.no_wait,
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
