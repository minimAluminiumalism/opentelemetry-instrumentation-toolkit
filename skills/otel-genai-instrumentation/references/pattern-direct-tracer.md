# Pattern B: Direct Tracer Monkey-patch

Use this pattern for agent/orchestration frameworks where the target library
manages workflows, agents, tasks, and tools — not direct LLM API calls.

**When to use:** Target library is a framework that orchestrates agent runs,
task execution, tool calls, and multi-step pipelines. It does NOT directly
call LLM APIs (those are traced separately by the LLM SDK instrumentation).

**Examples in LoongSuite:** CrewAI, LangGraph

## Architecture

```
_instrument()
  ├── Get tracer = trace_api.get_tracer(__name__, tracer_provider=...)
  ├── Create GenAIHookHelper() for content capture
  └── wrap_function_wrapper(module, "Class.method", WrapperClass(tracer, helper))

WrapperClass.__call__(wrapped, instance, args, kwargs)
  ├── Extract span name and attributes from instance/args
  ├── with tracer.start_as_current_span(name, kind=INTERNAL, attributes=...) as span:
  │     ├── result = wrapped(*args, **kwargs)
  │     ├── helper.on_completion(span, inputs, outputs)
  │     └── span.set_status(OK or ERROR)
  └── return result
```

## Instrumentor Template

```python
from __future__ import annotations

import logging
from typing import Any, Collection

from wrapt import wrap_function_wrapper

from opentelemetry import trace as trace_api
from opentelemetry.instrumentation.{name}.package import _instruments
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.utils import unwrap
from opentelemetry.semconv._incubating.attributes import gen_ai_attributes
from opentelemetry.trace import SpanKind, Status, StatusCode

logger = logging.getLogger(__name__)


class {Name}Instrumentor(BaseInstrumentor):

    def instrumentation_dependencies(self) -> Collection[str]:
        return _instruments

    def _instrument(self, **kwargs: Any) -> None:
        tracer_provider = kwargs.get("tracer_provider")
        tracer = trace_api.get_tracer(__name__, "", tracer_provider=tracer_provider)

        # Wrap agent run
        try:
            wrap_function_wrapper(
                module="{library}.agent",
                name="Agent.run",
                wrapper=_AgentRunWrapper(tracer),
            )
        except Exception as e:
            logger.warning("Could not wrap Agent.run: %s", e)

        # Wrap tool execution
        try:
            wrap_function_wrapper(
                module="{library}.tools",
                name="Tool.execute",
                wrapper=_ToolExecuteWrapper(tracer),
            )
        except Exception as e:
            logger.warning("Could not wrap Tool.execute: %s", e)

    def _uninstrument(self, **kwargs: Any) -> None:
        import {library}.agent
        import {library}.tools
        unwrap({library}.agent.Agent, "run")
        unwrap({library}.tools.Tool, "execute")
```

## Wrapper Class Template (Agent)

```python
class _AgentRunWrapper:
    def __init__(self, tracer):
        self._tracer = tracer

    def __call__(self, wrapped, instance, args, kwargs):
        agent_name = getattr(instance, "name", "agent")

        with self._tracer.start_as_current_span(
            name=f"invoke_agent {agent_name}",
            kind=SpanKind.INTERNAL,
            attributes={
                gen_ai_attributes.GEN_AI_OPERATION_NAME: "invoke_agent",
                "gen_ai.agent.name": agent_name,
                gen_ai_attributes.GEN_AI_SYSTEM: "{system_name}",
            },
        ) as span:
            try:
                result = wrapped(*args, **kwargs)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
```

## Wrapper Class Template (Tool)

```python
class _ToolExecuteWrapper:
    def __init__(self, tracer):
        self._tracer = tracer

    def __call__(self, wrapped, instance, args, kwargs):
        tool_name = getattr(instance, "name", "unknown_tool")

        with self._tracer.start_as_current_span(
            name=f"execute_tool {tool_name}",
            kind=SpanKind.INTERNAL,
            attributes={
                gen_ai_attributes.GEN_AI_OPERATION_NAME: "execute_tool",
                gen_ai_attributes.GEN_AI_TOOL_NAME: tool_name,
                gen_ai_attributes.GEN_AI_SYSTEM: "{system_name}",
            },
        ) as span:
            if hasattr(instance, "description"):
                span.set_attribute("gen_ai.tool.description", instance.description)
            try:
                result = wrapped(*args, **kwargs)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
```

## Async Wrapper Variant

```python
class _AsyncAgentRunWrapper:
    def __init__(self, tracer):
        self._tracer = tracer

    async def __call__(self, wrapped, instance, args, kwargs):
        agent_name = getattr(instance, "name", "agent")

        with self._tracer.start_as_current_span(
            name=f"invoke_agent {agent_name}",
            kind=SpanKind.INTERNAL,
            attributes={
                gen_ai_attributes.GEN_AI_OPERATION_NAME: "invoke_agent",
                "gen_ai.agent.name": agent_name,
                gen_ai_attributes.GEN_AI_SYSTEM: "{system_name}",
            },
        ) as span:
            try:
                result = await wrapped(*args, **kwargs)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
```

## Async Generator Wrapper (for streaming methods)

When the wrapped method is an async generator (uses `yield`), the span must
stay open across the entire iteration. Use manual `start_span()` +
`context.attach()` instead of `start_as_current_span` context manager,
and end the span in `finally`:

```python
from opentelemetry import context, trace

class _AsyncGeneratorWrapper:
    """Wraps an async generator method. The span stays open until the
    iterator is fully consumed or an error occurs."""

    def __init__(self, tracer):
        self._tracer = tracer

    async def __call__(self, wrapped, instance, args, kwargs):
        agent_name = getattr(instance, "name", "agent")

        span = self._tracer.start_span(
            name=f"invoke_agent {agent_name}",
            kind=SpanKind.CLIENT,
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.system": "{system_name}",
                "gen_ai.agent.name": agent_name,
            },
        )
        ctx = trace.set_span_in_context(span)
        token = context.attach(ctx)
        try:
            async for item in wrapped(*args, **kwargs):
                yield item
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise
        finally:
            span.end()
            context.detach(token)
```

Key points:
- `__call__` itself is an `async def` that uses `yield` — making it an
  async generator function. wrapt handles this correctly.
- Manual `start_span()` + `context.attach()` because `start_as_current_span`
  context manager doesn't work across `yield` boundaries.
- `finally` block ensures span is always ended and context detached.

## Server-Side Wrapper (SpanKind.SERVER)

For protocol/transport frameworks (like A2A, MCP) that have both client and
server sides, add SERVER spans for the request handler:

```python
class _ServerHandlerWrapper:
    def __init__(self, tracer):
        self._tracer = tracer

    async def __call__(self, wrapped, instance, args, kwargs):
        with self._tracer.start_as_current_span(
            name="invoke_agent",
            kind=SpanKind.SERVER,
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.system": "{system_name}",
            },
        ) as span:
            try:
                result = await wrapped(*args, **kwargs)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
```

When to use SpanKind.SERVER:
- The method handles **incoming** requests from another agent/service
- Example: `DefaultRequestHandler.on_message_send()` in A2A

When to use SpanKind.CLIENT:
- The method makes **outgoing** calls to a remote agent/service
- Example: `BaseClient.send_message()` in A2A

## Key Differences from Pattern A

| Aspect | Pattern A (Handler) | Pattern B (Direct Tracer) |
|---|---|---|
| Span lifecycle | `handler.start_*/stop_*/fail_*` | `tracer.start_as_current_span` context manager |
| Metrics | Automatic via handler | Not included (framework-level, not API-level) |
| Streaming | Needs generator wrapping | Typically not applicable |
| SpanKind | CLIENT | INTERNAL |
| Use case | LLM SDK API calls | Framework orchestration |
