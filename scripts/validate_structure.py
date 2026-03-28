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

"""Validate the directory structure and package files of an OTel instrumentation.

Usage:
    python validate_structure.py <path_to_instrumentation_package>

Example:
    python validate_structure.py /path/to/loongsuite-instrumentation-cohere

Exit code 0 if all checks pass, 1 if any fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

_LICENSE_HEADER = "# Copyright The OpenTelemetry Authors"

_REQUIRED_DEPS = [
    "opentelemetry-api",
    "opentelemetry-instrumentation",
    "opentelemetry-semantic-conventions",
]


def _check(ok: bool, msg: str, errors: list[str]) -> None:
    if ok:
        print(f"  PASS: {msg}")
    else:
        print(f"  FAIL: {msg}")
        errors.append(msg)


def validate(pkg_path: Path) -> list[str]:
    errors: list[str] = []
    pkg_name = pkg_path.name  # e.g., loongsuite-instrumentation-cohere

    # Extract the short name (e.g., "cohere" from "loongsuite-instrumentation-cohere")
    parts = pkg_name.split("-")
    if len(parts) >= 3 and parts[0] == "loongsuite" and parts[1] == "instrumentation":
        short_name = "-".join(parts[2:])
    else:
        short_name = pkg_name
    # Convert hyphens to underscores for Python module name
    module_name = short_name.replace("-", "_")

    print(f"\n=== Structure Validation: {pkg_name} ===\n")

    # 1. pyproject.toml exists and has required fields
    pyproject = pkg_path / "pyproject.toml"
    _check(pyproject.exists(), "pyproject.toml exists", errors)

    if pyproject.exists():
        content = pyproject.read_text()

        _check(
            "[project.entry-points.opentelemetry_instrumentor]" in content,
            "pyproject.toml has opentelemetry_instrumentor entry point",
            errors,
        )

        _check(
            "[project.optional-dependencies]" in content,
            "pyproject.toml has optional-dependencies (instruments)",
            errors,
        )

        for dep in _REQUIRED_DEPS:
            _check(
                dep in content,
                f"pyproject.toml depends on {dep}",
                errors,
            )

        _check(
            "hatchling" in content,
            "pyproject.toml uses hatchling build backend",
            errors,
        )

    # 2. Source directory structure
    src_root = pkg_path / "src" / "opentelemetry" / "instrumentation" / module_name
    _check(
        src_root.is_dir(),
        f"Source dir exists: src/opentelemetry/instrumentation/{module_name}/",
        errors,
    )

    if src_root.is_dir():
        # __init__.py with Instrumentor class
        init_file = src_root / "__init__.py"
        _check(init_file.exists(), "__init__.py exists", errors)
        if init_file.exists():
            init_content = init_file.read_text()
            _check(
                "BaseInstrumentor" in init_content,
                "__init__.py subclasses BaseInstrumentor",
                errors,
            )
            _check(
                "_instrument" in init_content,
                "__init__.py implements _instrument()",
                errors,
            )
            _check(
                "_uninstrument" in init_content,
                "__init__.py implements _uninstrument()",
                errors,
            )
            _check(
                "instrumentation_dependencies" in init_content,
                "__init__.py implements instrumentation_dependencies()",
                errors,
            )

        # package.py
        pkg_file = src_root / "package.py"
        _check(pkg_file.exists(), "package.py exists", errors)
        if pkg_file.exists():
            pkg_content = pkg_file.read_text()
            _check(
                "_instruments" in pkg_content,
                "package.py defines _instruments",
                errors,
            )

        # version.py
        ver_file = src_root / "version.py"
        _check(ver_file.exists(), "version.py exists", errors)
        if ver_file.exists():
            ver_content = ver_file.read_text()
            _check(
                "__version__" in ver_content,
                "version.py defines __version__",
                errors,
            )

    # 3. Namespace packages
    for ns_init in [
        pkg_path / "src" / "opentelemetry" / "__init__.py",
        pkg_path / "src" / "opentelemetry" / "instrumentation" / "__init__.py",
    ]:
        if ns_init.exists():
            content = ns_init.read_text()
            # Strip license header and comments for size check
            code_lines = [
                ln
                for ln in content.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            # Should contain at most a pkgutil namespace extension
            _check(
                len(code_lines) <= 2,
                f"Namespace {ns_init.relative_to(pkg_path)} is minimal (not a real module)",
                errors,
            )

    # 4. License headers on all .py files
    py_files = (
        list((pkg_path / "src").rglob("*.py")) if (pkg_path / "src").exists() else []
    )
    for py_file in py_files:
        content = py_file.read_text()
        if content.strip():  # skip empty files
            _check(
                content.startswith(_LICENSE_HEADER) or not content.strip(),
                f"License header in {py_file.relative_to(pkg_path)}",
                errors,
            )

    # 5. Tests directory
    tests_dir = pkg_path / "tests"
    _check(tests_dir.is_dir(), "tests/ directory exists", errors)

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
        print("Usage: python validate_structure.py <path>", file=sys.stderr)
        sys.exit(1)

    pkg_path = Path(sys.argv[1]).resolve()
    if not pkg_path.is_dir():
        print(f"Error: {pkg_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    errors = validate(pkg_path)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
