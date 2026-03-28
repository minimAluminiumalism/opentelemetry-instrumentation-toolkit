#!/bin/bash
# Pre-flight CI check for a LoongSuite instrumentation package.
#
# Runs all checks that the GitHub Actions CI pipeline would run,
# so you can catch failures before pushing.
#
# Usage:
#   ./preflight.sh <path-to-instrumentation-package> [loongsuite-repo-root]
#
# Example:
#   ./preflight.sh /path/to/loongsuite-python-agent/instrumentation-loongsuite/loongsuite-instrumentation-a2a
#
# Checks performed (within your package scope only):
#   1. ruff lint
#   2. ruff format
#   3. License headers
#   4. CHANGELOG exists with ## Unreleased
#   5. Package structure (validate_structure.py)
#   6. Semconv compliance (validate_semconv.py)
#   7. Unit tests
#   8. test-requirements.txt exists
#   9. Scope check — no changes outside the package directory

set -euo pipefail

PKG_PATH="${1:?Usage: $0 <path-to-package> [repo-root]}"
PKG_PATH="$(cd "$PKG_PATH" && pwd)"
PKG_NAME="$(basename "$PKG_PATH")"

# Auto-detect repo root (two levels up from instrumentation-loongsuite/pkg)
REPO_ROOT="${2:-$(cd "$PKG_PATH/../.." && pwd)}"

# Auto-detect skills repo (look for scripts/ with our harness)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

PASS=0
FAIL=0
WARN=0

_check() {
    local label="$1"
    shift
    echo ""
    echo "--- [$label] ---"
    if "$@"; then
        echo "  RESULT: PASS"
        PASS=$((PASS + 1))
    else
        echo "  RESULT: FAIL"
        FAIL=$((FAIL + 1))
    fi
}

_warn() {
    local label="$1"
    local msg="$2"
    echo ""
    echo "--- [$label] ---"
    echo "  RESULT: WARN — $msg"
    WARN=$((WARN + 1))
}

echo "============================================================"
echo "Pre-flight CI Check: $PKG_NAME"
echo "  Package: $PKG_PATH"
echo "  Repo:    $REPO_ROOT"
echo "============================================================"

# 1. ruff lint
_check "ruff lint" python -m ruff check "$PKG_PATH"

# 2. ruff format
_check "ruff format" python -m ruff format --check "$PKG_PATH"

# 3. License headers
if [ -f "$REPO_ROOT/scripts/loongsuite/check_license_header.py" ]; then
    # Run the check and filter for our package
    echo ""
    echo "--- [license headers] ---"
    output=$(python "$REPO_ROOT/scripts/loongsuite/check_license_header.py" --check 2>&1 || true)
    our_issues=$(echo "$output" | grep "$PKG_NAME" || true)
    if [ -z "$our_issues" ]; then
        echo "  RESULT: PASS"
        PASS=$((PASS + 1))
    else
        echo "$our_issues"
        echo "  RESULT: FAIL"
        FAIL=$((FAIL + 1))
    fi
else
    _warn "license headers" "check_license_header.py not found"
fi

# 4. CHANGELOG
echo ""
echo "--- [CHANGELOG] ---"
if [ -f "$PKG_PATH/CHANGELOG.md" ]; then
    if grep -q "## Unreleased" "$PKG_PATH/CHANGELOG.md"; then
        echo "  CHANGELOG.md exists with '## Unreleased' section"

        # Check if other packages' CHANGELOGs use PR links
        has_pr_pattern=false
        for other_cl in "$REPO_ROOT"/instrumentation-loongsuite/*/CHANGELOG.md; do
            if [ "$other_cl" = "$PKG_PATH/CHANGELOG.md" ]; then continue; fi
            if grep -qE '\(#[0-9]+\)|\[#[0-9]+\]' "$other_cl" 2>/dev/null; then
                has_pr_pattern=true
                break
            fi
        done

        if [ "$has_pr_pattern" = true ]; then
            if grep -qE '\(#[0-9]+\)|\[#[0-9]+\]' "$PKG_PATH/CHANGELOG.md"; then
                echo "  PR link found in CHANGELOG (matches repo convention)"
                echo "  RESULT: PASS"
                PASS=$((PASS + 1))
            else
                echo "  Other packages include PR links in CHANGELOG but yours doesn't"
                echo "  Hint: query latest PR with 'gh pr list --state all --limit 1 --json number'"
                echo "  RESULT: FAIL"
                FAIL=$((FAIL + 1))
            fi
        else
            echo "  RESULT: PASS"
            PASS=$((PASS + 1))
        fi
    else
        echo "  CHANGELOG.md exists but missing '## Unreleased' section"
        echo "  RESULT: FAIL"
        FAIL=$((FAIL + 1))
    fi
else
    echo "  CHANGELOG.md not found"
    echo "  RESULT: FAIL (CI requires at least one CHANGELOG file to be modified)"
    FAIL=$((FAIL + 1))
fi

# 4b. CHANGELOG style — entries should be concise (verb-first, short)
echo ""
echo "--- [CHANGELOG style] ---"
if [ -f "$PKG_PATH/CHANGELOG.md" ]; then
    # Check if any entry line exceeds 80 chars (sign of verbose description)
    long_lines=$(grep "^- " "$PKG_PATH/CHANGELOG.md" | awk 'length > 80' | head -3)
    if [ -n "$long_lines" ]; then
        echo "  WARNING: Some CHANGELOG entries are unusually long."
        echo "  Convention: short, verb-first (e.g., 'Initialize the instrumentation for X')"
        echo "$long_lines" | while read -r line; do echo "    > $line"; done
        echo "  RESULT: WARN"
        WARN=$((WARN + 1))
    else
        echo "  CHANGELOG entries look concise"
        echo "  RESULT: PASS"
        PASS=$((PASS + 1))
    fi
else
    echo "  Skipped (no CHANGELOG.md)"
fi

# 4c. README exists
echo ""
echo "--- [README] ---"
if [ -f "$PKG_PATH/README.rst" ] || [ -f "$PKG_PATH/README.md" ]; then
    readme_file=$(ls "$PKG_PATH"/README.* 2>/dev/null | head -1)
    line_count=$(wc -l < "$readme_file" | tr -d ' ')
    echo "  README found: $(basename "$readme_file") ($line_count lines)"
    # Warn if README is excessively long (other packages are ~30-50 lines)
    if [ "$line_count" -gt 80 ]; then
        echo "  WARNING: README is unusually long ($line_count lines)."
        echo "  Convention: brief — description, Installation, Usage, References"
        echo "  RESULT: WARN"
        WARN=$((WARN + 1))
    else
        echo "  RESULT: PASS"
        PASS=$((PASS + 1))
    fi
else
    echo "  No README.rst or README.md found"
    echo "  RESULT: FAIL"
    FAIL=$((FAIL + 1))
fi

# 5. Package structure (our harness)
if [ -f "$SCRIPT_DIR/validate_structure.py" ]; then
    _check "validate_structure" python "$SCRIPT_DIR/validate_structure.py" "$PKG_PATH"
else
    _warn "validate_structure" "validate_structure.py not found in $SCRIPT_DIR"
fi

# 6. Semconv compliance (our harness)
if [ -f "$SCRIPT_DIR/validate_semconv.py" ]; then
    _check "validate_semconv" python "$SCRIPT_DIR/validate_semconv.py" "$PKG_PATH"
else
    _warn "validate_semconv" "validate_semconv.py not found in $SCRIPT_DIR"
fi

# 7. Unit tests
echo ""
echo "--- [unit tests] ---"
TESTS_DIR="$PKG_PATH/tests"
if [ -d "$TESTS_DIR" ]; then
    # Need PYTHONPATH for the package source
    if PYTHONPATH="$PKG_PATH/src" python -m pytest "$TESTS_DIR" -v --tb=short 2>&1; then
        echo "  RESULT: PASS"
        PASS=$((PASS + 1))
    else
        echo "  RESULT: FAIL"
        FAIL=$((FAIL + 1))
    fi
else
    echo "  tests/ directory not found"
    echo "  RESULT: FAIL"
    FAIL=$((FAIL + 1))
fi

# 8. test-requirements.txt
echo ""
echo "--- [test requirements] ---"
if [ -f "$TESTS_DIR/test-requirements.txt" ] || [ -f "$TESTS_DIR/requirements.oldest.txt" ]; then
    echo "  Test requirements file found"
    echo "  RESULT: PASS"
    PASS=$((PASS + 1))
else
    echo "  No test-requirements.txt or requirements.oldest.txt in tests/"
    echo "  RESULT: FAIL (maintainer needs this for tox deps)"
    FAIL=$((FAIL + 1))
fi

# 9. __pycache__ check — clean up after unit tests, then verify none remain in source
echo ""
echo "--- [__pycache__] ---"
find "$PKG_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
pycache_dirs=$(find "$PKG_PATH" -type d -name "__pycache__" 2>/dev/null)
if [ -z "$pycache_dirs" ]; then
    echo "  No __pycache__ directories (cleaned after tests)"
    echo "  RESULT: PASS"
    PASS=$((PASS + 1))
else
    echo "  __pycache__ directories still present after cleanup:"
    echo "$pycache_dirs" | while read -r d; do echo "    $d"; done
    echo "  RESULT: FAIL"
    FAIL=$((FAIL + 1))
fi

# 10. Scope check — no changes outside the package
echo ""
echo "--- [scope check] ---"
if [ -d "$REPO_ROOT/.git" ]; then
    out_of_scope=$(git -C "$REPO_ROOT" diff --name-only HEAD 2>/dev/null | grep -v "^instrumentation-loongsuite/$PKG_NAME/" || true)
    untracked_out=$(git -C "$REPO_ROOT" ls-files --others --exclude-standard 2>/dev/null | grep -v "^instrumentation-loongsuite/$PKG_NAME/" | grep -v "^__pycache__" || true)
    all_out="$out_of_scope$untracked_out"
    if [ -z "$all_out" ]; then
        echo "  No changes outside package directory"
        echo "  RESULT: PASS"
        PASS=$((PASS + 1))
    else
        echo "  WARNING: changes detected outside your package:"
        echo "$out_of_scope" | head -10
        echo "$untracked_out" | head -10
        echo "  Do NOT commit these — only commit your package directory"
        echo "  RESULT: WARN"
        WARN=$((WARN + 1))
    fi
else
    echo "  Not a git repo, skipping scope check"
    WARN=$((WARN + 1))
fi

# Summary
echo ""
echo "============================================================"
echo "Pre-flight Results: $PASS passed, $FAIL failed, $WARN warnings"
if [ "$FAIL" -gt 0 ]; then
    echo "STATUS: FAILED — fix issues before pushing"
    echo "============================================================"
    exit 1
else
    echo "STATUS: READY TO COMMIT"
    echo "============================================================"
    exit 0
fi
