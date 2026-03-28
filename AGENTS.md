# OpenTelemetry Skills - Repository Rules

This repository contains **skills** (domain knowledge + workflows) and
**harness scripts** (validation + analysis tools) for generating OpenTelemetry
auto-instrumentation code for GenAI Python libraries.

The primary target codebase is the **LoongSuite Python Agent** repository
(`loongsuite-python-agent`), a distribution of OpenTelemetry Python contrib
with enhanced GenAI framework support.

## Rules

- Follow Apache 2.0 license header on all generated Python files
- All GenAI instrumentations must comply with OTel GenAI Semantic Conventions
  (status: Development, opt-in: `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`)
- Generated code must pass `scripts/validate_structure.py` and `scripts/validate_semconv.py`
- Never break the target library: all instrumentation patches must be **fail-open**
  (wrap in try/except, call original on failure)
- Sensitive data (`gen_ai.input.messages`, `gen_ai.output.messages`, etc.) must NOT
  be captured by default; gate behind `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`
- Sampling-critical attributes (`gen_ai.operation.name`, `gen_ai.provider.name`,
  `gen_ai.request.model`, `server.address`, `server.port`) must be set at span
  creation time, not after

## Code Style

- **Comments: be restrained.** Only add comments at genuinely critical or
  non-obvious code points (e.g., why a fail-open try/except exists, why a
  specific attribute must be set at span creation). Do NOT add trivial comments
  that restate what the code already says. Let the code speak for itself.

## File Hygiene

- **Separate deliverables from throwaway artifacts.** The target repo's
  `tests/` directory is for unit tests that get committed. E2E tests,
  scratch scripts, debug helpers, and other verification artifacts must
  NOT be placed inside the deliverable codebase. Use `/tmp/` or a scratch
  directory outside the repo.
- Only commit files that are part of the final deliverable. If in doubt,
  check: "would this file be useful to the next developer?" If not, keep
  it outside the repo.

## Python Environment

- **Always use virtual environments.** Use `uv` as the preferred tool for
  creating venvs, installing packages, and running Python commands.
  ```bash
  uv venv .venv
  uv pip install -e ".[instruments]"
  uv run pytest tests/
  ```
- **NEVER install packages directly into the system/global Python.** Always
  operate within a project venv (`.venv/`) or a temporary venv.
- If the target repo already has a `.venv/`, use it. If not, create one.

## CI / Pre-commit

- Before considering any task "done", check whether the target repo has a
  CI pipeline (`.github/workflows/`) or pre-commit config (`.pre-commit-config.yaml`).
- If pre-commit hooks exist, run `pre-commit run --files <changed_files>` after
  writing code. Fix any issues before presenting results.
- If CI lint/type-check jobs exist, replicate the relevant checks locally
  (e.g., `ruff check`, `mypy`) before committing.

## CI Pipeline Tracking After PR

- After pushing a branch and creating a PR, **actively track the CI pipeline**:
  1. Use `gh pr checks <pr_number>` or `gh pr view <pr_number> --json
     statusCheckRollup` to monitor CI status.
  2. If you created the PR via `gh pr create`, capture the PR URL from the
     output. If you don't have it, use `gh pr list --head <branch_name>` to
     find it, or ask the user for the PR link.
  3. Poll CI status periodically until all checks complete.
  4. If any check **fails**, read the failure logs (`gh run view <run_id>
     --log-failed`), diagnose the issue, fix the code, commit, and push
     again. Repeat until CI is green.
  5. Do NOT consider the task "done" until CI passes on the PR.
  6. If you cannot determine the PR URL automatically, ask the user:
     ```
     I need the PR URL to track CI pipeline status. Could you provide
     the link, or should I search for it?
     ```

## Git Rules

- When committing or creating PRs on behalf of the user:
  - Write a clear, concise commit message describing the change.
  - **NEVER add the coding agent (Claude, GPT, Codex, etc.) as a co-author.**
    Do not add `Co-authored-by` trailers referencing any AI model or tool.
    The commit author must be the human user only.
  - Do not force-push to main/master unless explicitly asked.

## Scope of Changes — Do Not Overstep

- **Only modify your own instrumentation package.** Do NOT touch:
  - CI workflow files (`.github/workflows/*.yml`) — these are auto-generated
    by the maintainers
  - `tox.ini` or `tox-loongsuite.ini` — tox registration is the maintainer's
    responsibility
  - Bootstrap generation scripts or their outputs (`bootstrap_gen.py`)
  - Other packages' code or configuration
- If you notice that the CI pipeline, tox config, or workflow generation
  needs updating for your new package, **document it in the PR description**
  as a follow-up item for the maintainer. Do not make the changes yourself.
- Your PR should contain ONLY:
  - The new instrumentation package directory (source, tests, pyproject.toml,
    CHANGELOG.md, README.rst, test-requirements.txt)
  - Nothing outside `instrumentation-loongsuite/loongsuite-instrumentation-{name}/`

## Available Skills

| Skill | Description |
|---|---|
| `otel-genai-instrumentation` | Generate complete OTel GenAI instrumentation packages |

## Project Structure

```
skills/                    # Skills (domain knowledge + workflows)
  otel-genai-instrumentation/
    SKILL.md               # Workflow + decision tree
    references/            # Semconv specs, code pattern templates, repo conventions

scripts/                   # Harness (validation + analysis tools, shared across skills)
  validate_structure.py    # Verify package directory structure
  validate_semconv.py      # Verify OTel GenAI semconv compliance
  analyze_target.py        # Auto-scan target library's public API
  jaeger.sh                # Start/stop Jaeger Docker for trace E2E
  e2e_verify.py            # Verify traces in Jaeger (spans, attrs, chain)
  prometheus.sh            # Start/stop Prometheus Docker for metrics E2E
  metrics_verify.py        # Verify metrics in Prometheus

install.sh                 # Symlink installer for Claude Code / Codex / OpenCode
AGENTS.md                  # Cross-platform rules (Codex + OpenCode)
CLAUDE.md                  # Claude Code rules
```
