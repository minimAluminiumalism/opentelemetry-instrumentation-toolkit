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

"""Validate semconv compliance of an OTel GenAI instrumentation package.

Uses AST analysis to check that the instrumentation code follows
OpenTelemetry GenAI semantic conventions.

Usage:
    python validate_semconv.py <path_to_instrumentation_package>

Example:
    python validate_semconv.py /path/to/loongsuite-instrumentation-cohere

Exit code 0 if all checks pass, 1 if any fail.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Well-known operation names from the GenAI semconv (2026-03).
# Update this set when the spec adds new operations.
# Source: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/
VALID_OPERATIONS = {
    "chat",
    "generate_content",
    "text_completion",
    "embeddings",
    "retrieval",
    "execute_tool",
    "create_agent",
    "invoke_agent",
}

# Attributes that should appear somewhere in the codebase
REQUIRED_ATTRIBUTES = {
    "gen_ai.operation.name": "Must identify the operation type",
}

RECOMMENDED_ATTRIBUTES = {
    "gen_ai.provider.name": "Should identify the GenAI provider",
}

# Attributes that must NOT be set by default (require opt-in)
SENSITIVE_ATTRIBUTES = {
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.system_instructions",
    "gen_ai.tool.definitions",
    "gen_ai.tool.call.arguments",
    "gen_ai.tool.call.result",
    "gen_ai.retrieval.query.text",
    "gen_ai.retrieval.documents",
}

# Environment variable that controls content capture
CAPTURE_ENV_VAR = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"


class SemconvVisitor(ast.NodeVisitor):
    """AST visitor that collects semconv-related patterns."""

    def __init__(self):
        self.string_literals: set[str] = set()
        self.attribute_sets: list[dict] = []  # {attr_name, file, line}
        self.has_capture_check = False
        self.has_fail_open = False  # outer try/except around wrapped call
        self.handler_calls: set[str] = set()  # start_llm, stop_llm, etc.
        self.method_calls: set[str] = set()  # all method calls seen
        self.unwrap_calls: list[str] = []
        self.wrap_calls: list[str] = []

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.string_literals.add(node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check for handler.start_*/stop_*/fail_* calls and tracer methods
        if isinstance(node.func, ast.Attribute):
            method = node.func.attr
            self.method_calls.add(method)
            if method.startswith(("start_", "stop_", "fail_")) and method not in (
                "start_as_current_span",
                "start_span",
            ):
                self.handler_calls.add(method)
            if method == "set_attribute" and node.args:
                if isinstance(node.args[0], ast.Constant) and isinstance(
                    node.args[0].value, str
                ):
                    self.attribute_sets.append(
                        {
                            "attr": node.args[0].value,
                            "line": node.lineno,
                        }
                    )
            if method in ("unwrap",):
                self.unwrap_calls.append(str(node.lineno))
            if method in ("wrap_function_wrapper",):
                self.wrap_calls.append(str(node.lineno))

        # Check for os.environ.get(CAPTURE_ENV_VAR)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == CAPTURE_ENV_VAR:
                    self.has_capture_check = True
                # Also check if using a Name reference to a constant
                if isinstance(arg, ast.Name) and "CAPTURE" in arg.id.upper():
                    self.has_capture_check = True

        # Also check for string reference to the env var
        for arg in node.args:
            if isinstance(arg, ast.Constant) and arg.value == CAPTURE_ENV_VAR:
                self.has_capture_check = True

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Check for GEN_AI_OPERATION_NAME etc. from semconv module
        if "GEN_AI" in node.attr.upper() or "gen_ai" in node.attr:
            self.string_literals.add(node.attr)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        # Heuristic: if there's a try/except that calls wrapped() in the
        # except handler, that's a fail-open pattern
        for handler in node.handlers:
            for child in ast.walk(handler):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name) and child.func.id == "wrapped":
                        self.has_fail_open = True
                    if (
                        isinstance(child.func, ast.Attribute)
                        and child.func.attr == "wrapped"
                    ):
                        self.has_fail_open = True
        self.generic_visit(node)


def _check(ok: bool, msg: str, errors: list[str]) -> None:
    if ok:
        print(f"  PASS: {msg}")
    else:
        print(f"  FAIL: {msg}")
        errors.append(msg)


def validate(pkg_path: Path) -> list[str]:
    errors: list[str] = []

    # Find the module name
    parts = pkg_path.name.split("-")
    if len(parts) >= 3 and parts[0] == "loongsuite" and parts[1] == "instrumentation":
        module_name = "_".join(parts[2:])
    else:
        module_name = pkg_path.name.replace("-", "_")

    src_root = pkg_path / "src" / "opentelemetry" / "instrumentation" / module_name

    if not src_root.is_dir():
        print(f"Error: source dir not found: {src_root}")
        return [f"Source directory {src_root} does not exist"]

    print(f"\n=== Semconv Validation: {pkg_path.name} ===\n")

    # Collect all Python source
    py_files = list(src_root.rglob("*.py"))
    all_visitors: list[SemconvVisitor] = []
    all_strings: set[str] = set()

    for py_file in py_files:
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError as e:
            errors.append(f"Syntax error in {py_file.name}: {e}")
            continue

        visitor = SemconvVisitor()
        visitor.visit(tree)
        all_visitors.append(visitor)
        all_strings.update(visitor.string_literals)

    # Merge results
    all_handler_calls: set[str] = set()
    all_method_calls: set[str] = set()
    all_attr_sets: list[dict] = []
    has_capture_check = False
    has_fail_open = False
    total_wraps = 0
    total_unwraps = 0

    for v in all_visitors:
        all_handler_calls.update(v.handler_calls)
        all_method_calls.update(v.method_calls)
        all_attr_sets.extend(v.attribute_sets)
        if v.has_capture_check:
            has_capture_check = True
        if v.has_fail_open:
            has_fail_open = True
        total_wraps += len(v.wrap_calls)
        total_unwraps += len(v.unwrap_calls)

    set_attrs = {a["attr"] for a in all_attr_sets}

    # Pre-compute usage patterns
    uses_handler = bool(all_handler_calls)
    uses_tracer = (
        "start_as_current_span" in all_method_calls or "start_span" in all_method_calls
    )

    # --- Checks ---

    # 1. Operation name is set
    # Pattern A: set via handler invocation (operation_name field in dataclass)
    # Pattern B: set via span attributes directly
    # Both patterns also reference GEN_AI_OPERATION_NAME constant
    has_operation = (
        "gen_ai.operation.name" in all_strings
        or "gen_ai.operation.name" in set_attrs
        or "GEN_AI_OPERATION_NAME" in all_strings
        or any("operation_name" in s for s in all_strings)
        # Pattern A: handler.start_llm() sets it from invocation.operation_name
        or "start_llm" in all_handler_calls
        or "start_embedding" in all_handler_calls
        or "start_execute_tool" in all_handler_calls
        or "start_invoke_agent" in all_handler_calls
        or "start_create_agent" in all_handler_calls
        or "start_retrieval" in all_handler_calls
        or "start_rerank" in all_handler_calls
    )
    _check(has_operation, "gen_ai.operation.name is set somewhere", errors)

    # 2. Provider/system name is set
    # Pattern A: set via invocation.provider_name in handler
    # Pattern B: set via span attributes directly — may use either
    #   gen_ai.provider.name (for LLM SDKs) or gen_ai.system (for frameworks)
    has_provider = (
        "gen_ai.provider.name" in all_strings
        or "gen_ai.provider.name" in set_attrs
        or "gen_ai.system" in all_strings
        or "gen_ai.system" in set_attrs
        or "GEN_AI_PROVIDER_NAME" in all_strings
        or "GEN_AI_SYSTEM" in all_strings
        or any("provider_name" in s for s in all_strings)
        # If handler is used, provider is set in invocation
        or uses_handler
    )
    _check(has_provider, "gen_ai.provider.name or gen_ai.system is set somewhere", errors)

    # 3. Operation names are valid
    for s in all_strings:
        if s in VALID_OPERATIONS:
            print(f"  INFO: Found operation name: {s}")

    # 4. Handler lifecycle or tracer usage
    _check(
        uses_handler or uses_tracer,
        "Uses TelemetryHandler or Tracer for span management",
        errors,
    )

    if uses_handler:
        # Check for balanced start/stop
        starts = {c for c in all_handler_calls if c.startswith("start_")}
        stops = {
            c.replace("stop_", "start_")
            for c in all_handler_calls
            if c.startswith("stop_")
        }
        fails = {
            c.replace("fail_", "start_")
            for c in all_handler_calls
            if c.startswith("fail_")
        }

        for start in starts:
            op = start.replace("start_", "")
            _check(
                start in stops or start in fails,
                f"Handler start_{op} has matching stop_{op} or fail_{op}",
                errors,
            )

    # 5. Content capture is gated
    # Check both string literals AND semconv constant references
    has_sensitive_literal = any(
        attr in all_strings or attr in set_attrs
        for attr in SENSITIVE_ATTRIBUTES
    )
    has_sensitive_constant = False
    sensitive_constant_names = {
        "GEN_AI_INPUT_MESSAGES",
        "GEN_AI_OUTPUT_MESSAGES",
        "GEN_AI_SYSTEM_INSTRUCTIONS",
        "GEN_AI_TOOL_CALL_ARGUMENTS",
        "GEN_AI_TOOL_CALL_RESULT",
    }
    for py_file in py_files:
        content = py_file.read_text()
        for const in sensitive_constant_names:
            if f"gen_ai_attributes.{const}" in content:
                has_sensitive_constant = True
                break

    has_sensitive = has_sensitive_literal or has_sensitive_constant

    if has_sensitive:
        _check(
            has_capture_check,
            f"Content capture gated by {CAPTURE_ENV_VAR}",
            errors,
        )
    else:
        print(
            "  WARN: No input/output message capture found. "
            "Chat spans should capture gen_ai.input.messages "
            "and gen_ai.output.messages (gated by "
            f"{CAPTURE_ENV_VAR})."
        )

    # 6. Fail-open pattern
    if total_wraps > 0:
        _check(
            has_fail_open,
            "Fail-open pattern: outer try/except calls wrapped() on instrumentation error",
            errors,
        )

    # 7. Uninstrument balance
    if total_wraps > 0 and total_unwraps > 0:
        _check(
            total_unwraps >= total_wraps,
            f"Uninstrument covers all patches (wraps={total_wraps}, unwraps={total_unwraps})",
            errors,
        )
    elif total_wraps > 0:
        # Pattern C doesn't use wrap/unwrap
        print(f"  INFO: {total_wraps} wraps found, {total_unwraps} unwraps")

    # 8. Attribute richness check (WARN level, not FAIL)
    # Count distinct gen_ai.* attribute keys — from string literals AND
    # from gen_ai_attributes.GEN_AI_* constant references
    genai_attrs_used = set()
    for s in all_strings:
        if s.startswith("gen_ai.") or s.startswith("server."):
            genai_attrs_used.add(s)
    for a in all_attr_sets:
        attr = a["attr"]
        if attr.startswith("gen_ai.") or attr.startswith("server."):
            genai_attrs_used.add(attr)

    # Also count gen_ai_attributes.GEN_AI_* constant usages
    # These map to gen_ai.* attributes but aren't string literals
    _CONSTANT_MAP = {
        "GEN_AI_SYSTEM": "gen_ai.system",
        "GEN_AI_OPERATION_NAME": "gen_ai.operation.name",
        "GEN_AI_AGENT_NAME": "gen_ai.agent.name",
        "GEN_AI_AGENT_DESCRIPTION": "gen_ai.agent.description",
        "GEN_AI_AGENT_ID": "gen_ai.agent.id",
        "GEN_AI_AGENT_VERSION": "gen_ai.agent.version",
        "GEN_AI_REQUEST_MODEL": "gen_ai.request.model",
        "GEN_AI_RESPONSE_MODEL": "gen_ai.response.model",
        "GEN_AI_RESPONSE_ID": "gen_ai.response.id",
        "GEN_AI_RESPONSE_FINISH_REASONS": "gen_ai.response.finish_reasons",
        "GEN_AI_USAGE_INPUT_TOKENS": "gen_ai.usage.input_tokens",
        "GEN_AI_USAGE_OUTPUT_TOKENS": "gen_ai.usage.output_tokens",
        "GEN_AI_TOOL_NAME": "gen_ai.tool.name",
        "GEN_AI_TOOL_CALL_ID": "gen_ai.tool.call.id",
        "GEN_AI_CONVERSATION_ID": "gen_ai.conversation.id",
        "GEN_AI_INPUT_MESSAGES": "gen_ai.input.messages",
        "GEN_AI_OUTPUT_MESSAGES": "gen_ai.output.messages",
        "GEN_AI_DATA_SOURCE_ID": "gen_ai.data_source.id",
    }
    for py_file in py_files:
        content = py_file.read_text()
        for const_name, attr_name in _CONSTANT_MAP.items():
            if f"gen_ai_attributes.{const_name}" in content:
                genai_attrs_used.add(attr_name)

    print(f"\n  INFO: Distinct gen_ai.*/server.* attributes used: {len(genai_attrs_used)}")
    for attr in sorted(genai_attrs_used):
        print(f"    - {attr}")

    if len(genai_attrs_used) <= 3:
        print(
            "  WARN: Very few semantic attributes set. Consider extracting more "
            "context from the library's data model (IDs, metadata, status). "
            "Your instrumentation should be a superset of any existing tracing."
        )

    # 9. Semconv import check — should use gen_ai_attributes constants,
    #    not redefine as local string variables
    has_semconv_import = False
    redefined_constants = []
    for py_file in py_files:
        content = py_file.read_text()
        if "gen_ai_attributes" in content:
            has_semconv_import = True
        # Detect patterns like: _GEN_AI_SYSTEM = "gen_ai.system"
        for line in content.splitlines():
            stripped = line.strip()
            if (
                stripped.startswith("_GEN_AI")
                and "=" in stripped
                and '"gen_ai.' in stripped
            ):
                redefined_constants.append(
                    f"{py_file.name}: {stripped[:70]}"
                )

    if redefined_constants:
        print(
            f"\n  WARN: {len(redefined_constants)} hardcoded semconv constant(s) found."
        )
        print(
            "  Use gen_ai_attributes.GEN_AI_* from "
            "opentelemetry.semconv._incubating.attributes instead."
        )
        for rc in redefined_constants[:5]:
            print(f"    > {rc}")

    # Summary
    print(f"\n{'=' * 50}")
    if errors:
        print(f"FAILED: {len(errors)} issue(s) found")
    else:
        print("ALL CHECKS PASSED")
    print(f"{'=' * 50}\n")

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_semconv.py <path>", file=sys.stderr)
        sys.exit(1)

    pkg_path = Path(sys.argv[1]).resolve()
    if not pkg_path.is_dir():
        print(f"Error: {pkg_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    errors = validate(pkg_path)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
