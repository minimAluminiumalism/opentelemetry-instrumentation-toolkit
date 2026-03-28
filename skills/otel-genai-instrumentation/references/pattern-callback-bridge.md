# Pattern C: Callback Bridge

Use this pattern when the target library has a **built-in tracing or callback
interface** that can be hooked into without monkey-patching.

**When to use:** Target library exposes a `TracingProcessor`, `CallbackManager`,
or similar hook system designed for tracing integrations.

**Examples in LoongSuite:** OpenAI Agents SDK (built-in `TracingProcessor`)

## Architecture

```
_instrument()
  ├── Create ExtendedTelemetryHandler(tracer_provider, meter_provider, logger_provider)
  ├── Create OTelProcessor(handler, capture_content)
  └── library.add_trace_processor(processor)     # register, no monkey-patch

OTelProcessor (implements library's TracingProcessor)
  on_span_start(span_data):
    ├── Map span_data.type to GenAI operation name
    ├── Create OTel span with tracer.start_span()
    ├── Attach context for parent-child relationship
    └── Store span in internal map
  on_span_end(span_data):
    ├── Look up OTel span from internal map
    ├── Set response attributes (tokens, model, finish_reason)
    └── End span
```

## Instrumentor Template

```python
from __future__ import annotations

import logging
from typing import Any, Collection, Optional

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.{name}.package import _instruments
from opentelemetry.util.genai.extended_handler import ExtendedTelemetryHandler

logger = logging.getLogger(__name__)

_ENV_CAPTURE_CONTENT = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"


class {Name}Instrumentor(BaseInstrumentor):

    _handler: Optional[ExtendedTelemetryHandler] = None
    _processor: Optional[Any] = None

    def instrumentation_dependencies(self) -> Collection[str]:
        return _instruments

    def _instrument(self, **kwargs: Any) -> None:
        tracer_provider = kwargs.get("tracer_provider")
        meter_provider = kwargs.get("meter_provider")
        logger_provider = kwargs.get("logger_provider")

        {Name}Instrumentor._handler = ExtendedTelemetryHandler(
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            logger_provider=logger_provider,
        )

        import os
        capture_content = os.environ.get(_ENV_CAPTURE_CONTENT, "").lower() not in (
            "false", "0", "no", "off", ""
        )

        from {library}.tracing import add_trace_processor
        from opentelemetry.instrumentation.{name}._processor import OTelProcessor

        processor = OTelProcessor(
            handler={Name}Instrumentor._handler,
            capture_content=capture_content,
        )
        {Name}Instrumentor._processor = processor
        add_trace_processor(processor)

    def _uninstrument(self, **kwargs: Any) -> None:
        processor = {Name}Instrumentor._processor
        if processor is None:
            return
        try:
            from {library}.tracing.setup import get_trace_provider
            provider = get_trace_provider()
            if hasattr(provider, "_multi_processor"):
                procs = provider._multi_processor._processors
                if processor in procs:
                    procs.remove(processor)
        except Exception as e:
            logger.debug("Failed to remove processor: %s", e)
        processor.shutdown()
        {Name}Instrumentor._processor = None
        {Name}Instrumentor._handler = None
```

## Processor Template

```python
from opentelemetry import context, trace

# Map library span types to GenAI operation names
_SPAN_TYPE_MAP = {
    "agent": "invoke_agent",
    "generation": "chat",
    "function": "execute_tool",
    "handoff": "invoke_agent",
    # ... add more as needed
}

_SPAN_KIND_MAP = {
    "agent": trace.SpanKind.INTERNAL,
    "generation": trace.SpanKind.CLIENT,
    "function": trace.SpanKind.INTERNAL,
}


class OTelProcessor:
    """Bridge between the library's tracing system and OpenTelemetry."""

    def __init__(self, handler, capture_content=False):
        self._handler = handler
        self._capture_content = capture_content
        self._span_map = {}       # library_span_id -> otel_span
        self._context_map = {}    # library_span_id -> context_token

    def on_trace_start(self, trace_data):
        """Called when a new trace (top-level run) starts."""
        pass  # Optionally create a root span

    def on_trace_end(self, trace_data):
        """Called when a trace completes."""
        pass

    def on_span_start(self, span_data):
        """Called when a library-level span starts."""
        span_type = span_data.type  # e.g., "agent", "generation", "function"
        operation = _SPAN_TYPE_MAP.get(span_type, span_type)
        kind = _SPAN_KIND_MAP.get(span_type, trace.SpanKind.INTERNAL)

        # Determine span name
        name_parts = [operation]
        if hasattr(span_data, "name") and span_data.name:
            name_parts.append(span_data.name)
        span_name = " ".join(name_parts)

        # Set up parent context
        parent_ctx = context.get_current()
        if span_data.parent_id and span_data.parent_id in self._span_map:
            parent_span = self._span_map[span_data.parent_id]
            parent_ctx = trace.set_span_in_context(parent_span)

        # Create OTel span
        tracer = self._handler._tracer
        otel_span = tracer.start_span(
            name=span_name,
            kind=kind,
            context=parent_ctx,
            attributes={
                "gen_ai.operation.name": operation,
                "gen_ai.provider.name": "{provider}",
            },
        )

        # Attach context so children see this as parent
        token = context.attach(trace.set_span_in_context(otel_span))
        self._span_map[span_data.span_id] = otel_span
        self._context_map[span_data.span_id] = token

    def on_span_end(self, span_data):
        """Called when a library-level span ends."""
        otel_span = self._span_map.pop(span_data.span_id, None)
        token = self._context_map.pop(span_data.span_id, None)

        if otel_span is None:
            return

        # Apply response attributes from span_data
        if hasattr(span_data, "model"):
            otel_span.set_attribute("gen_ai.request.model", span_data.model)
        if hasattr(span_data, "usage") and span_data.usage:
            otel_span.set_attribute("gen_ai.usage.input_tokens", span_data.usage.input_tokens)
            otel_span.set_attribute("gen_ai.usage.output_tokens", span_data.usage.output_tokens)

        # Set error status if needed
        if hasattr(span_data, "error") and span_data.error:
            otel_span.set_status(trace.Status(trace.StatusCode.ERROR, str(span_data.error)))
        else:
            otel_span.set_status(trace.Status(trace.StatusCode.OK))

        otel_span.end()

        if token is not None:
            context.detach(token)

    def shutdown(self):
        """Clean up any remaining spans."""
        for span_id in list(self._span_map):
            span = self._span_map.pop(span_id)
            span.end()
            token = self._context_map.pop(span_id, None)
            if token:
                context.detach(token)
```

## Key Differences from Pattern A/B

| Aspect | Pattern C (Callback Bridge) |
|---|---|
| Patching | None - registers processor via library API |
| Uninstrument | Remove processor from library's provider |
| Complexity | Highest - must manage span/context maps manually |
| Reliability | Most robust - no monkey-patch fragility |
| Prerequisite | Library must expose a tracing/callback hook |
