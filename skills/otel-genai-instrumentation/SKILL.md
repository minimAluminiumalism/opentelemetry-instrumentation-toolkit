---
name: otel-genai-instrumentation
description: >
  Generate OpenTelemetry GenAI auto-instrumentation for Python libraries.
  Use when asked to "add instrumentation", "add tracing", "instrument",
  or "add OTel support" for a GenAI framework or LLM SDK. Covers OpenAI,
  Anthropic, Cohere, DashScope, LangChain, CrewAI, and any Python GenAI library.
---

# OTel GenAI Instrumentation Generator

Generate complete, semconv-compliant OpenTelemetry auto-instrumentation packages
for GenAI Python libraries targeting the LoongSuite Python Agent repository.

## Workflow

### Step 0: Git Setup

Before writing any code, create a feature branch in the target repository:

```bash
cd /path/to/loongsuite-python-agent
git checkout main && git pull
git checkout -b feat/add-{name}-instrumentation
```

All generated code must be committed to this branch, NOT to main or any
other existing branch.

### Step 1: Research Target Library

Before writing any code, understand what you're instrumenting.

1. **Clone the target library source code.** Ask the user for the GitHub repo
   URL if not obvious, then clone it to a temp directory:
   ```bash
   git clone --depth 1 https://github.com/{org}/{library}.git /tmp/{library}-src
   ```
   This is a throwaway clone for analysis — keep it until all validation
   (Step 4 + Step 5) passes and the user is satisfied, then clean up:
   ```bash
   rm -rf /tmp/{library}-src
   ```
   Reading source code directly is far more valuable than reflection scanning.
   Focus on:
   - **Core client classes**: find the main `Client` / `AsyncClient` and their
     public methods (`chat`, `embed`, `rerank`, `run`, etc.)
   - **Internal HTTP/transport layer**: how requests are actually sent — this
     tells you what to wrap and where response data lives
   - **Streaming implementation**: look for `yield`, `async for`, generator
     patterns — this is the hardest part to instrument correctly
   - **Built-in tracing/callback interfaces**: search for classes like
     `TracingProcessor`, `CallbackManager`, `Tracer`, hook registries — if
     these exist, Pattern C (Callback Bridge) may be possible
   - **Test fixtures and mocks**: search `tests/` for fake clients, mock
     transports, or test utilities — reuse these for unit tests and E2E tests
   - **Type definitions**: check response objects, usage objects, message
     formats — you need to know exactly how to extract `model`, `tokens`,
     `finish_reason` from responses

2. **Check for existing observability implementations.** Before designing
   from scratch, search for:
   - Does the target library already have built-in tracing/telemetry?
   - Is there an existing OTel instrumentation in `opentelemetry-python-contrib`
     or other community projects?
   - Does [OpenLLMetry (Traceloop)](https://github.com/traceloop/openllmetry)
     already instrument this library? If so, study which functions they patch
     and how they extract attributes. See `references/openllmetry-reference.md`.
   - Does [OpenLIT](https://github.com/openlit/openlit) instrument it?
     Use as a secondary reference. See `references/openlit-reference.md`.
   - Can any existing implementation be reused or extended?

3. **If existing tracing exists, analyze it in depth and treat it as your
   baseline.** This is critical — your instrumentation must be a **superset**
   of the existing tracing, not a subset. Specifically:
   - **List every span** the existing tracing creates (which classes/methods)
   - **List every attribute** it extracts (from args, responses, config)
   - **Identify data fields** it accesses (message IDs, task IDs, agent
     names, session IDs, error details, etc.)
   - **Your instrumentation must capture at least the same information**
     plus GenAI semantic convention attributes on top. If the existing
     tracing extracts `task_id` from a message object, you must too.
   - **Build a comparison table**: existing spans vs your planned spans,
     attribute by attribute. Present this table before generating code.
     No information loss is acceptable.
   - If the existing tracing covers operations you hadn't planned to
     instrument (like `get_task`, `cancel_task`), evaluate whether to
     add them.

4. Optionally, run `scripts/analyze_target.py {library_name}` for a quick
   automated scan of the public API surface (requires the library to be
   pip-installed). This supplements but does NOT replace source code reading.

5. Classify each API method into the GenAI operations defined in
   `references/semconv-operations.md`.

### Step 2: Select Instrumentation Pattern

Based on the research, pick ONE of three patterns:

**Decision tree:**

```
Does the library have a built-in tracing/callback interface?
  (e.g., TracingProcessor, CallbackManager, hooks)
├── YES → Is it a pluggable runtime registry?
│         (Can you register/unregister a processor at runtime?)
│   ├── YES → Pattern C: Callback Bridge
│   │         Reference: references/pattern-callback-bridge.md
│   │         Example: OpenAI Agents SDK (TracingProcessor)
│   └── NO → The tracing exists but is compile-time decorators or
│            non-pluggable. Use Pattern B and let your spans coexist
│            with the library's built-in spans. Consider recommending
│            users disable the library's built-in tracing if it
│            creates too much noise.
│            Reference: references/pattern-direct-tracer.md
│            Example: A2A SDK (@trace_class decorators)
└── NO → What kind of operations?
         ├── LLM API calls (chat, embed, rerank)
         │   → Pattern A: Handler-based Monkey-patch
         │     Reference: references/pattern-handler-monkeypatch.md
         │     Example: DashScope (Generation.call, TextEmbedding.call)
         └── Framework/protocol orchestration (agent run, workflow, pipeline)
             → Pattern B: Direct Tracer Monkey-patch
               Reference: references/pattern-direct-tracer.md
               Example: CrewAI (Crew.kickoff, Agent.execute_task)
```

**Coexisting with built-in tracing:** If the target library already has OTel
tracing (like A2A's `@trace_class` decorators), your instrumentation adds
GenAI semantic convention spans on top. The built-in spans will appear as
siblings or children. This is acceptable — the built-in spans lack GenAI
attributes, which is the whole point of our instrumentation. Document in
the README that users can disable the library's built-in tracing if they
want cleaner traces (e.g., `OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false`).

### Step 3: Generate Code

Read `references/loongsuite-conventions.md` for repo-specific rules (directory
layout, naming, dependencies, license header).

Instrumentation produces two signal types: **Traces** and **Metrics**. Both
must follow the GenAI semantic conventions and be implemented together.

#### Traces

**Use semconv constants, not strings.** Import attribute names from
`opentelemetry.semconv._incubating.attributes.gen_ai_attributes` (e.g.,
`gen_ai_attributes.GEN_AI_OPERATION_NAME`). Do NOT redefine them as local
string constants like `_GEN_AI_SYSTEM = "gen_ai.system"`. Only define local
constants for domain-specific attributes that don't exist in the semconv
package. See `references/loongsuite-conventions.md` Import Conventions.

**Attribute richness rule:** Your wrapper functions must extract as much
contextual data as possible from the wrapped method's arguments, instance
state, and return values. At minimum:
- All GenAI semconv required/recommended attributes (see `references/semconv-operations.md`)
- All data fields that the library's existing tracing captures (if any)
- Domain-specific IDs available in the call context (task IDs, message IDs,
  session IDs, conversation IDs)

Do NOT generate thin wrappers that only set `gen_ai.operation.name` and
`gen_ai.system`. Inspect the method signature, the `instance` object, and
the `args/kwargs` to find every useful field. If the library's response
object contains usage data, model names, or status information, extract it.

**Custom operation names:** If a method doesn't fit any standard
`gen_ai.operation.name` value (chat, embeddings, execute_tool, invoke_agent,
etc.), use the closest standard value. For example, an "agent step" is part
of `invoke_agent`, so use `gen_ai.operation.name = "invoke_agent"` and
differentiate via the span name (e.g., `invoke_agent step 3`). Do NOT
invent non-standard operation name values.

**Overlapping with LLM SDK instrumentors:** If the target framework calls
LLM SDKs directly (e.g., browser-use calls OpenAI), users may have both
your framework instrumentor AND the SDK instrumentor active. This produces
nested spans: your `chat {model}` span wraps the SDK's `chat {model}` span.
This is acceptable and expected — your span adds framework context (which
agent/step triggered the call) while the SDK span adds raw API details.
Do NOT try to suppress or deduplicate these spans.

**Wrap at the right layer for data extraction:** If a high-level method
(e.g., `Agent.get_model_output()`) discards the LLM response data
(tokens, finish reason) before returning, wrapping that method alone
won't give you enough attributes. In this case, also intercept the
actual LLM call (e.g., `llm.ainvoke()`) to capture the full response.
Use techniques like temporary monkey-patching of `instance.llm.ainvoke`
within the wrapper to capture intermediate `ChatInvokeCompletion` objects
that the high-level method discards.

**Content serialization:** When setting `gen_ai.input.messages` and
`gen_ai.output.messages`, values MUST be structured data (JSON strings),
never Python object repr like `<SomeClass object at 0x...>`. Use:
- `json.dumps(messages_list)` for input messages
- `model.model_dump()` + `json.dumps()` for Pydantic output models
- `json.dumps(dict)` for dict outputs
- `str(value)` only for plain string outputs

The E2E harness validates this — Python repr will be flagged as FAIL.

**Content capture applies to tool spans too:** `execute_tool` spans should
capture `gen_ai.tool.call.arguments` (the action parameters) and
`gen_ai.tool.call.result` (the action result), gated by the same
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` env var. Use
`model_dump()` / `json.dumps()` for Pydantic models, same as chat outputs.

#### Metrics

The GenAI semconv defines the following metrics (see `references/semconv-operations.md`
for bucket boundaries and attributes):

| Metric | Type | Requirement | When to record |
|---|---|---|---|
| `gen_ai.client.operation.duration` | Histogram (seconds) | **Required** | Every operation |
| `gen_ai.client.token.usage` | Histogram (tokens) | Recommended | When token counts available |

Implementation approach:
- In `_instrument()`, create a `Meter` from the `meter_provider` kwarg.
- Create histogram instruments once at instrumentation time.
- In each wrapper, measure wall-clock duration (`time.monotonic()` before
  and after the call) and record it to the duration histogram.
- If token usage is available in the response, record input/output token
  counts to the token usage histogram with `gen_ai.token.type` attribute.
- If the target library or an existing instrumentation already records
  metrics, study which metrics it provides and ensure you cover at least
  the same set plus the semconv-required metrics.

```python
from opentelemetry.metrics import Histogram

class {Name}Instrumentor(BaseInstrumentor):
    def _instrument(self, **kwargs):
        meter_provider = kwargs.get("meter_provider")
        meter = metrics.get_meter(_TRACER_NAME, __version__, meter_provider=meter_provider)
        duration_histogram = meter.create_histogram(
            name="gen_ai.client.operation.duration",
            unit="s",
            description="Duration of GenAI operation",
        )
        token_histogram = meter.create_histogram(
            name="gen_ai.client.token.usage",
            unit="{token}",
            description="Token usage for GenAI operation",
        )
        # Pass histograms to wrapper classes
```

Generate the following files in order:

#### 3a. Package scaffold

```
instrumentation-loongsuite/loongsuite-instrumentation-{name}/
├── pyproject.toml
├── README.rst
├── src/opentelemetry/instrumentation/{name}/
│   ├── __init__.py          # {Name}Instrumentor(BaseInstrumentor)
│   ├── package.py           # _instruments = ("{library} >= {version}",)
│   ├── version.py           # __version__ = "0.1.0.dev"
│   └── patch/               # (Pattern A only)
│       ├── __init__.py      # re-export all wrap_* functions
│       └── {operation}.py   # one file per operation type
└── tests/
    ├── conftest.py
    └── test_{operation}.py  # one file per operation type
```

**CHANGELOG.md**: Create a `CHANGELOG.md` following Keep a Changelog format.
Match the tone and style of existing CHANGELOGs in the repo — typically
short, verb-first entries (e.g., "Initialize the instrumentation for X").
Do NOT write verbose descriptions.
If existing CHANGELOGs include PR number links (e.g.,
`([#123](https://github.com/.../pull/123))`), you must include one too.
To determine the PR number before creating the PR:
1. Query the latest PR number: `gh pr list --repo {org}/{repo} --state all --limit 1 --json number`
2. The next PR will be that number + 1
3. Add the link: `([#{next}](https://github.com/{org}/{repo}/pull/{next}))`

**README**: Create a README (.rst or .md, match the repo convention).
Keep it brief — match the style and length of existing READMEs in the
repo. Typically: one-line description, Installation, Usage code block,
References. No lengthy explanations.

**Docs check**: After writing all code, review whether any repo-level
documentation needs updating (e.g., a supported-frameworks table, a
top-level README listing all instrumentations). If so, note it in the
PR description as a follow-up — do NOT modify files outside your package.

#### 3b. Instrumentor class (`__init__.py`)

- Subclass `BaseInstrumentor`
- Implement `instrumentation_dependencies()` returning `_instruments`
- In `_instrument(**kwargs)`:
  - Extract `tracer_provider`, `meter_provider`, `logger_provider` from kwargs
  - Create `ExtendedTelemetryHandler` (Pattern A) or `tracer` (Pattern B)
  - `wrap_function_wrapper()` for each target method
  - Wrap each call in try/except so failed patching doesn't break the app
- In `_uninstrument(**kwargs)`:
  - Import target modules
  - `unwrap()` every method that was wrapped in `_instrument`

#### 3c. Patch functions (Pattern A)

For each operation, generate a wrapper following this skeleton:

```python
def wrap_{operation}_call(wrapped, instance, args, kwargs, handler=None):
    model = kwargs.get("model")
    if not model or handler is None:
        return wrapped(*args, **kwargs)
    try:
        invocation = _build_invocation(kwargs, model)
        handler.start_llm(invocation)          # opens span
        try:
            result = wrapped(*args, **kwargs)
            if _is_streaming(result):
                return _wrap_sync_generator(result, handler, invocation)
            _update_invocation(invocation, result)
            handler.stop_llm(invocation)        # closes span
            return result
        except Exception as e:
            handler.fail_llm(invocation, Error(message=str(e), type=type(e)))
            raise
    except Exception:
        return wrapped(*args, **kwargs)         # fail-open
```

Always generate both sync and async variants. If streaming is supported, also
generate `_wrap_sync_generator` and `_wrap_async_generator`.

#### 3d. Tests

Generate tests that:
- Use `InMemorySpanExporter` + `SimpleSpanProcessor`
- Create fake/mock objects instead of calling real APIs
- Verify span name, kind, and all required attributes
- Verify error handling sets span status to ERROR
- Verify content capture is off by default, on when env var is set

### Step 4: Validate

After generating code, run these validation scripts:

```bash
python scripts/validate_structure.py \
  /path/to/loongsuite-python-agent/instrumentation-loongsuite/loongsuite-instrumentation-{name}

python scripts/validate_semconv.py \
  /path/to/loongsuite-python-agent/instrumentation-loongsuite/loongsuite-instrumentation-{name}
```

Then check the target repo's CI and pre-commit setup:

1. Look for `.pre-commit-config.yaml` in the target repo root. If it exists,
   run `pre-commit run --files <all_new_or_changed_files>` and fix any issues.
2. Look for `.github/workflows/` CI configs. Replicate relevant lint/type-check
   steps locally (e.g., `ruff check src/`, `mypy src/`).
3. Do NOT present the code as "done" until all checks pass.

Fix any reported issues before presenting the code to the user.

### Step 5: E2E Verification

After static validation passes, run end-to-end tests to verify both
**traces** and **metrics** in real backends.

**E2E test file location:** E2E tests are throwaway verification scripts,
NOT deliverables. They must NEVER be placed inside the instrumentation
package's `tests/` directory (which is for unit tests that get committed).
Instead, place E2E test files in a temporary location:
- `/tmp/e2e_test_{name}.py` (preferred — auto-cleaned on reboot), or
- A scratch directory outside the target repo

The instrumentation package's `tests/` directory should only contain
unit tests that are part of the committed codebase.

#### Step 5a: Trace Verification (Jaeger)

1. Start Jaeger: `scripts/jaeger.sh start`
2. Check if the target library has mock/test support:
   - **Has mock** → generate `/tmp/e2e_test_{name}.py` using mock
   - **No mock, needs API key** → ask the user
3. Run the E2E test: `python /tmp/e2e_test_{name}.py`
4. Verify traces: `python scripts/e2e_verify.py -s e2e-{name} --expect-operations invoke_agent`
5. If verification fails, fix and re-run

**Trace verification must check:**

- **Span attributes**: every span has the correct `gen_ai.*` and domain
  attributes. Use standard semconv attribute names when they exist; only
  use custom namespaces (e.g., `a2a.*`) when semconv has no equivalent.
- **Resource attributes**: `service.name` is set on the trace, and any
  other resource-level metadata (SDK version, telemetry scope) is present.
- **Trace chain continuity** (critical): when instrumentation creates
  multiple spans in a single flow (e.g., `invoke_agent` → `chat` →
  `execute_tool`), all spans must belong to the **same trace** with
  correct parent-child relationships. Broken chains (orphan spans with
  no parent, or spans on separate trace IDs) indicate context propagation
  bugs. The E2E test MUST include at least one multi-span scenario that
  verifies parent-child linkage.

#### Step 5b: Metrics Verification (Prometheus)

1. Start Prometheus: `scripts/prometheus.sh start`
2. The E2E test script should configure an OTLP metrics exporter (or
   Prometheus exporter on port 9464). The same `/tmp/e2e_test_{name}.py`
   can cover both traces and metrics in a single run.
3. After the test run, verify metrics:
   `python scripts/metrics_verify.py -s e2e-{name} --expect-metrics gen_ai.client.operation.duration`
4. If verification fails, fix and re-run

**Metrics verification must check:**

- `gen_ai.client.operation.duration` histogram exists with correct
  attributes (`gen_ai.operation.name`, `gen_ai.system` or
  `gen_ai.provider.name`)
- `gen_ai.client.token.usage` histogram exists when token data is
  available, with `gen_ai.token.type` = `input` | `output`
- Metric values are plausible (duration > 0, token counts > 0)
- If the target library's existing instrumentation produces custom metrics,
  verify those are also captured or superseded

#### Cleanup

After both trace and metrics verification pass:
```bash
scripts/jaeger.sh stop
scripts/prometheus.sh stop
```

### Step 6: Submit PR

1. Commit only your instrumentation package:
   ```bash
   git add instrumentation-loongsuite/loongsuite-instrumentation-{name}/
   git commit -m "feat: add {name} auto-instrumentation"
   ```
   **Do NOT commit changes to files outside your package** — no workflow
   YAMLs, no tox configs, no bootstrap scripts. See AGENTS.md
   "Scope of Changes" for details.

2. Push the branch and create a PR:
   ```bash
   git push -u origin feat/add-{name}-instrumentation
   gh pr create --title "feat: add {name} instrumentation" --body "..."
   ```

3. In the PR description, note any follow-up items the maintainer needs
   to do (e.g., "Please register this package in tox-loongsuite.ini and
   regenerate workflow files").

4. **Track CI**: poll `gh pr checks <number>` until all checks complete.
   If any check fails on your code, read the logs, fix, and push again.
   If a check fails because the package isn't registered in tox yet,
   that's expected — note it in the PR and let the maintainer handle it.

## Key Rules

- **Git branch**: Always create a feature branch before writing code (Step 0).
  Never write instrumentation code directly on main.
- **Fail-open**: Instrumentation must NEVER break the target library. All
  patching wrapped in try/except.
- **No content by default**: `gen_ai.input.messages`, `gen_ai.output.messages`,
  `gen_ai.system_instructions` are NOT set unless
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`.
- **Sampling-critical attributes at span creation**: `gen_ai.operation.name`,
  `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`,
  `server.port` MUST be set in the `start_span()` call, not after.
- **License header**: Every `.py` file must start with the Apache 2.0 header.
- **Coexist with built-in tracing**: If the library has its own OTel tracing,
  your instrumentation adds GenAI semantic attributes on top. Do NOT disable
  or conflict with existing spans. Document coexistence in README.
