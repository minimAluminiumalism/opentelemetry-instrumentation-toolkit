# E2E Test Template

After unit tests pass, write an end-to-end test file that sends real traces
to Jaeger and verifies them via the Jaeger Query API.

**IMPORTANT:** E2E test files are throwaway verification scripts. They must
NOT be placed inside the instrumentation package's `tests/` directory.
Place them in `/tmp/e2e_test_{name}.py` or another scratch location outside
the target repository.

## Workflow

```
1. scripts/jaeger.sh start                   # Start Jaeger in Docker
2. python /tmp/e2e_test_{name}.py            # Run the E2E test
3. scripts/e2e_verify.py -s e2e-{name}       # Verify traces in Jaeger
4. scripts/jaeger.sh stop                    # Clean up
```

## Deciding: Mock or Real API?

**Use mock when:**
- The target library supports it (e.g., `httpx.MockTransport`, `responses`)
- No API key is needed
- You want deterministic, repeatable results

**Ask the user for an API key when:**
- The library has no mock support
- The behavior you need to verify depends on real API responses
- You need to test streaming with real chunks

**How to ask:**
```
I need an API key for {library} to run the E2E test. 
Please provide it, or I can skip the E2E step.
```

## E2E Test File Template

Generate a file like `e2e_test_{name}.py` in the target repo:

```python
#!/usr/bin/env python3
"""E2E test for {Name} instrumentation.

Sends traces to Jaeger and verifies via the Jaeger Query API.

Prerequisites:
    1. Jaeger running: scripts/jaeger.sh start
    2. Dependencies: pip install {library} opentelemetry-sdk \
       opentelemetry-exporter-otlp-proto-http loongsuite-instrumentation-{name}

Usage:
    python e2e_test_{name}.py
    python e2e_test_{name}.py --api-key sk-xxx  # if real API needed
"""

import argparse
import sys
import time

# --- OTel setup ---
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

SERVICE_NAME = "e2e-{name}"
JAEGER_OTLP_ENDPOINT = "http://localhost:4318/v1/traces"


def setup_telemetry():
    """Configure OTel to export to Jaeger via OTLP HTTP."""
    resource = Resource.create({"service.name": SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=JAEGER_OTLP_ENDPOINT)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def instrument():
    """Activate the instrumentation."""
    from opentelemetry.instrumentation.{name} import {Name}Instrumentor
    {Name}Instrumentor().instrument()


def run_mock_scenario():
    """Run a test scenario using mock/fake objects."""
    # OPTION A: Use the library's built-in mock/test support
    # OPTION B: Use httpx.MockTransport or responses library
    # OPTION C: Patch the HTTP client to return canned responses

    # Example for a chat operation:
    # from {library} import Client
    # client = Client(api_key="fake-key", http_client=mock_http_client)
    # response = client.chat(model="test-model", messages=[
    #     {"role": "user", "content": "Hello"}
    # ])
    # print(f"Response: {response}")
    pass


def run_real_scenario(api_key: str):
    """Run a test scenario against the real API."""
    # from {library} import Client
    # client = Client(api_key=api_key)
    # response = client.chat(model="...", messages=[
    #     {"role": "user", "content": "Say hello in one word."}
    # ])
    # print(f"Response: {response}")
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", help="API key for real API calls")
    args = parser.parse_args()

    print(f"Setting up OTel (exporting to {JAEGER_OTLP_ENDPOINT})...")
    provider = setup_telemetry()

    print("Instrumenting {name}...")
    instrument()

    if args.api_key:
        print("Running real API scenario...")
        run_real_scenario(args.api_key)
    else:
        print("Running mock scenario (no API key)...")
        run_mock_scenario()

    # Flush all spans to Jaeger
    print("Flushing spans...")
    provider.force_flush(timeout_millis=5000)
    provider.shutdown()

    # Give Jaeger a moment to index
    time.sleep(2)

    print(f"Done. Verify traces at: http://localhost:16686/search?service={SERVICE_NAME}")
    print(f"Or run: python scripts/e2e_verify.py -s {SERVICE_NAME}")


if __name__ == "__main__":
    main()
```

## What the Agent Should Do

After generating the instrumentation code AND unit tests:

1. **Check mock availability**: Search the target library's docs/source for
   mock/test utilities. Many SDKs (httpx, OpenAI, Anthropic) provide them.

2. **Generate the e2e test file**: Fill in the template above with real
   mock setup or ask for API key.

3. **Run the e2e flow**:
   ```bash
   # Start Jaeger
   scripts/jaeger.sh start

   # Run the test
   python e2e_test_{name}.py

   # Verify traces
   python scripts/e2e_verify.py --service e2e-{name} --expect-operations chat,embeddings
   ```

4. **If verification fails**: Read the FAIL messages, fix the instrumentation
   code, and re-run.

5. **If API key is needed**: Stop and ask the user:
   ```
   The {library} SDK does not have built-in mock support. I need an API key
   to run the E2E verification. Please provide one, or I'll skip this step.
   ```

6. **Clean up**: `scripts/jaeger.sh stop`

## Verification Checks

The `e2e_verify.py` script checks:

- Every span has `gen_ai.operation.name` set
- Inference spans have `gen_ai.provider.name` and `gen_ai.request.model`
- Tool spans have `gen_ai.tool.name`
- Agent spans have `gen_ai.agent.name`
- Error spans have `error.type`
- Span hierarchy is valid (proper parent-child)
- Expected operations actually appear in the trace
