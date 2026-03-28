# opentelemetry-harness

Skills and harness for generating OpenTelemetry auto-instrumentation packages
for GenAI Python libraries.

Designed to work with [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
[Codex](https://github.com/openai/codex), and [OpenCode](https://opencode.ai/) —
load the skill, give it a target library, and it generates a complete, semconv-compliant
instrumentation package with traces, metrics, and tests.

## What's in this repo

```
skills/                              Domain knowledge + workflows
  otel-genai-instrumentation/
    SKILL.md                         Main workflow (8 steps)
    references/                      Semconv specs, code pattern templates

scripts/                             Harness — validation + E2E tooling
  preflight.sh                       One-command pre-commit CI check
  validate_structure.py              Package directory structure check
  validate_semconv.py                GenAI semantic conventions compliance
  analyze_target.py                  Auto-scan target library's public API
  jaeger.sh                          Start/stop Jaeger Docker (trace E2E)
  e2e_verify.py                      Verify traces in Jaeger
  prometheus.sh                      Start/stop Prometheus Docker (metrics E2E)
  metrics_verify.py                  Verify metrics in Prometheus
```

## Quick start

```bash
# 1. Clone and install skill for your coding agent
git clone https://github.com/minimAluminiumalism/opentelemetry-harness.git
cd opentelemetry-harness
./install.sh    # creates symlinks for Claude Code, Codex, and OpenCode

# 2. Ask your coding agent
> Add OpenTelemetry auto-instrumentation for the Cohere Python SDK
```

The agent will automatically pick up the skill and follow the workflow:
research target → select pattern → generate code → validate → E2E verify.

## Preflight check

Before committing a new instrumentation package, run the preflight script
to catch CI failures locally:

```bash
./scripts/preflight.sh /path/to/loongsuite-python-agent/instrumentation-loongsuite/loongsuite-instrumentation-{name}
```

Checks: ruff lint/format, license headers, CHANGELOG, package structure,
semconv compliance, unit tests, README, test-requirements, scope.

## Supported instrumentation patterns

| Pattern | When to use | Example |
|---|---|---|
| A — Handler-based monkey-patch | LLM SDK API calls (chat, embed, rerank) | DashScope |
| B — Direct tracer monkey-patch | Framework/protocol orchestration | CrewAI, A2A |
| C — Callback bridge | Library has built-in tracing interface | OpenAI Agents |

## License

Apache 2.0
