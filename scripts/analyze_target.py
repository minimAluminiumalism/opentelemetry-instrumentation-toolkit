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

"""Analyze a Python library's public API to identify instrumentable methods.

Usage:
    python analyze_target.py <library_name>

Example:
    python analyze_target.py cohere
    python analyze_target.py anthropic

Output: JSON report of classes, methods, and their signatures with
annotations about likely GenAI operation types.
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from typing import Any


# Keywords that suggest a method's GenAI operation type
_OPERATION_HINTS = {
    "chat": ["chat", "complete", "completions", "converse", "messages"],
    "generate_content": ["generate", "generate_content"],
    "text_completion": ["text_completion", "completions"],
    "embeddings": ["embed", "embedding", "embeddings", "encode"],
    "retrieval": ["search", "query", "retrieve", "retrieval", "find"],
    "execute_tool": ["tool", "function", "execute_tool", "call_tool"],
    "invoke_agent": ["run", "invoke", "execute", "kickoff", "start"],
    "create_agent": ["create_agent", "register_agent", "build_agent"],
}

# Keywords that suggest streaming support
_STREAMING_HINTS = ["stream", "streaming", "iter", "generator"]

# Keywords that suggest async variant
_ASYNC_HINTS = ["async", "aio", "Async"]


def _classify_method(name: str, sig: inspect.Signature) -> dict[str, Any]:
    """Classify a method by its likely GenAI operation type."""
    info: dict[str, Any] = {
        "name": name,
        "params": [],
        "likely_operation": None,
        "has_stream_param": False,
        "is_async": False,
    }

    # Check params
    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        param_info = {"name": param_name}
        if param.default is not inspect.Parameter.empty:
            try:
                json.dumps(param.default)
                param_info["default"] = param.default
            except (TypeError, ValueError):
                param_info["default"] = str(param.default)
        if param.annotation is not inspect.Parameter.empty:
            param_info["type"] = str(param.annotation)
        info["params"].append(param_info)

        # Check for streaming param
        if param_name.lower() in ("stream", "streaming"):
            info["has_stream_param"] = True

    # Classify by method name
    name_lower = name.lower()
    for op, hints in _OPERATION_HINTS.items():
        if any(h in name_lower for h in hints):
            info["likely_operation"] = op
            break

    # Check if async
    info["is_async"] = inspect.iscoroutinefunction(
        sig  # type: ignore[arg-type]
    ) or any(h in name for h in _ASYNC_HINTS)

    return info


def _analyze_class(cls: type) -> dict[str, Any]:
    """Analyze a class for instrumentable methods."""
    class_info: dict[str, Any] = {
        "name": cls.__name__,
        "module": cls.__module__,
        "methods": [],
        "has_async_variant": False,
    }

    if "Async" in cls.__name__ or "Aio" in cls.__name__:
        class_info["has_async_variant"] = True

    for attr_name in sorted(dir(cls)):
        if attr_name.startswith("_"):
            continue
        try:
            attr = getattr(cls, attr_name)
        except Exception:
            continue

        if not callable(attr):
            continue

        try:
            sig = inspect.signature(attr)
        except (ValueError, TypeError):
            continue

        method_info = _classify_method(attr_name, sig)
        method_info["is_async"] = inspect.iscoroutinefunction(attr)

        # Only include methods that look like GenAI operations
        if method_info["likely_operation"] or method_info["has_stream_param"]:
            class_info["methods"].append(method_info)

    return class_info


def _has_tracing_interface(module: Any) -> list[str]:
    """Check if a module exposes a built-in tracing/callback interface."""
    hints = []
    for name in dir(module):
        name_lower = name.lower()
        if any(
            kw in name_lower
            for kw in [
                "tracingprocessor",
                "tracing_processor",
                "callbackmanager",
                "callback_manager",
                "tracer",
                "trace_provider",
            ]
        ):
            hints.append(name)
    return hints


def analyze_library(library_name: str) -> dict[str, Any]:
    """Analyze a library and return a structured report."""
    report: dict[str, Any] = {
        "library": library_name,
        "installed_version": None,
        "classes": [],
        "tracing_interfaces": [],
        "suggested_pattern": None,
        "errors": [],
    }

    # Try to import the library
    try:
        lib = importlib.import_module(library_name)
    except ImportError as e:
        report["errors"].append(f"Cannot import {library_name}: {e}")
        return report

    # Get version
    report["installed_version"] = getattr(lib, "__version__", "unknown")

    # Check for built-in tracing
    tracing_hints = _has_tracing_interface(lib)

    # Also check common submodules
    for sub in ["tracing", "callbacks", "hooks", "telemetry"]:
        try:
            sub_mod = importlib.import_module(f"{library_name}.{sub}")
            tracing_hints.extend(f"{sub}.{h}" for h in _has_tracing_interface(sub_mod))
        except ImportError:
            pass

    report["tracing_interfaces"] = tracing_hints

    # Scan public classes
    for attr_name in sorted(dir(lib)):
        if attr_name.startswith("_"):
            continue
        try:
            attr = getattr(lib, attr_name)
        except Exception:
            continue
        if not inspect.isclass(attr):
            continue

        class_info = _analyze_class(attr)
        if class_info["methods"]:
            report["classes"].append(class_info)

    # Suggest pattern
    if tracing_hints:
        report["suggested_pattern"] = "C (Callback Bridge)"
    elif any(
        any(
            m["likely_operation"] in ("chat", "embeddings", "retrieval")
            for m in c["methods"]
        )
        for c in report["classes"]
    ):
        report["suggested_pattern"] = "A (Handler-based Monkey-patch)"
    else:
        report["suggested_pattern"] = "B (Direct Tracer Monkey-patch)"

    return report


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_target.py <library_name>", file=sys.stderr)
        sys.exit(1)

    library_name = sys.argv[1]
    report = analyze_library(library_name)
    print(json.dumps(report, indent=2, default=str))

    # Summary
    print("\n--- Summary ---", file=sys.stderr)
    print(
        f"Library: {report['library']} {report['installed_version']}", file=sys.stderr
    )
    print(
        f"Classes with instrumentable methods: {len(report['classes'])}",
        file=sys.stderr,
    )
    total_methods = sum(len(c["methods"]) for c in report["classes"])
    print(f"Total instrumentable methods: {total_methods}", file=sys.stderr)
    if report["tracing_interfaces"]:
        print(
            f"Built-in tracing interfaces: {report['tracing_interfaces']}",
            file=sys.stderr,
        )
    print(f"Suggested pattern: {report['suggested_pattern']}", file=sys.stderr)


if __name__ == "__main__":
    main()
