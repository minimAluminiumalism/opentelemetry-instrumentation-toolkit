# Pattern A: Handler-based Monkey-patch

Use this pattern for LLM SDK API calls (chat, embed, rerank) where the target
library has no built-in tracing interface.

**When to use:** Target library exposes direct API methods (e.g., `Client.chat()`,
`TextEmbedding.call()`) with no callback/hook system.

**Examples in LoongSuite:** DashScope, LangChain embedding

## Architecture

```
_instrument()
  ├── Create ExtendedTelemetryHandler(tracer_provider, meter_provider, logger_provider)
  ├── Define closure wrappers that capture `handler`
  └── wrap_function_wrapper(module, "Class.method", wrapper)

wrapper(wrapped, instance, args, kwargs)
  ├── Build invocation dataclass from args/kwargs
  ├── handler.start_llm(invocation)      # opens span
  ├── result = wrapped(*args, **kwargs)  # call original
  ├── Update invocation from result
  └── handler.stop_llm(invocation)       # closes span, records metrics
```

## Instrumentor Template

```python
# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# ...

from __future__ import annotations

import logging
from typing import Collection

from wrapt import wrap_function_wrapper

from opentelemetry.instrumentation.{name}.package import _instruments
from opentelemetry.instrumentation.{name}.version import __version__
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.utils import unwrap
from opentelemetry.util.genai.extended_handler import ExtendedTelemetryHandler

logger = logging.getLogger(__name__)

# Module paths for the target library
_MODULE_CHAT = "{library}.chat"
_MODULE_EMBED = "{library}.embeddings"


class {Name}Instrumentor(BaseInstrumentor):

    def instrumentation_dependencies(self) -> Collection[str]:
        return _instruments

    def _instrument(self, **kwargs):
        tracer_provider = kwargs.get("tracer_provider")
        meter_provider = kwargs.get("meter_provider")
        event_logger_provider = kwargs.get("logger_provider")

        handler = ExtendedTelemetryHandler(
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            logger_provider=event_logger_provider,
        )

        # Import patch functions
        from opentelemetry.instrumentation.{name}.patch import (
            wrap_chat_call,
            wrap_async_chat_call,
        )

        # Create closures that capture handler
        def _wrap_chat(wrapped, instance, args, kwargs):
            return wrap_chat_call(wrapped, instance, args, kwargs, handler=handler)

        async def _wrap_async_chat(wrapped, instance, args, kwargs):
            return await wrap_async_chat_call(wrapped, instance, args, kwargs, handler=handler)

        # Apply patches
        try:
            wrap_function_wrapper(_MODULE_CHAT, "Client.chat", _wrap_chat)
        except Exception as e:
            logger.warning("Failed to instrument Client.chat: %s", e)

        try:
            wrap_function_wrapper(_MODULE_CHAT, "AsyncClient.chat", _wrap_async_chat)
        except Exception as e:
            logger.warning("Failed to instrument AsyncClient.chat: %s", e)

    def _uninstrument(self, **kwargs):
        import {library}.chat  # noqa: PLC0415
        unwrap({library}.chat.Client, "chat")
        unwrap({library}.chat.AsyncClient, "chat")
```

## Patch Function Template (sync, non-streaming)

```python
from opentelemetry.util.genai.types import Error

def wrap_chat_call(wrapped, instance, args, kwargs, handler=None):
    model = kwargs.get("model")
    if not model or handler is None:
        return wrapped(*args, **kwargs)

    try:
        invocation = _build_invocation(kwargs, model)
        handler.start_llm(invocation)

        try:
            result = wrapped(*args, **kwargs)
            _update_invocation_from_response(invocation, result)
            handler.stop_llm(invocation)
            return result
        except Exception as e:
            handler.fail_llm(invocation, Error(message=str(e), type=type(e)))
            raise

    except Exception:
        # Fail-open: never break the user's code
        return wrapped(*args, **kwargs)
```

## Patch Function Template (async)

```python
async def wrap_async_chat_call(wrapped, instance, args, kwargs, handler=None):
    model = kwargs.get("model")
    if not model or handler is None:
        return await wrapped(*args, **kwargs)

    try:
        invocation = _build_invocation(kwargs, model)
        handler.start_llm(invocation)

        try:
            result = await wrapped(*args, **kwargs)
            _update_invocation_from_response(invocation, result)
            handler.stop_llm(invocation)
            return result
        except Exception as e:
            handler.fail_llm(invocation, Error(message=str(e), type=type(e)))
            raise

    except Exception:
        return await wrapped(*args, **kwargs)
```

## Streaming Wrapper Template

```python
import timeit

def _wrap_sync_generator(generator, handler, invocation):
    last_response = None
    first_token = False
    try:
        for chunk in generator:
            if not first_token:
                first_token = True
                invocation.monotonic_first_token_s = timeit.default_timer()
            last_response = chunk
            yield chunk
        if last_response:
            _update_invocation_from_response(invocation, last_response)
        handler.stop_llm(invocation)
    except Exception as e:
        handler.fail_llm(invocation, Error(message=str(e), type=type(e)))
        raise


async def _wrap_async_generator(generator, handler, invocation):
    last_response = None
    first_token = False
    try:
        async for chunk in generator:
            if not first_token:
                first_token = True
                invocation.monotonic_first_token_s = timeit.default_timer()
            last_response = chunk
            yield chunk
        if last_response:
            _update_invocation_from_response(invocation, last_response)
        handler.stop_llm(invocation)
    except Exception as e:
        handler.fail_llm(invocation, Error(message=str(e), type=type(e)))
        raise
```

## Invocation Builder Template

```python
from opentelemetry.util.genai.types import LLMInvocation

def _build_invocation(kwargs, model):
    """Build LLMInvocation from call kwargs."""
    return LLMInvocation(
        model=model,
        operation_name="chat",
        provider_name="{provider}",
        input_messages=_extract_messages(kwargs) if _should_capture() else None,
        temperature=kwargs.get("temperature"),
        max_tokens=kwargs.get("max_tokens"),
        top_p=kwargs.get("top_p"),
        stop_sequences=kwargs.get("stop"),
    )

def _update_invocation_from_response(invocation, response):
    """Update invocation with response data."""
    invocation.response_model = getattr(response, "model", None)
    invocation.response_id = getattr(response, "id", None)
    usage = getattr(response, "usage", None)
    if usage:
        invocation.input_tokens = getattr(usage, "prompt_tokens", None)
        invocation.output_tokens = getattr(usage, "completion_tokens", None)
    # Extract finish reason
    choices = getattr(response, "choices", None)
    if choices:
        invocation.finish_reasons = [
            getattr(c, "finish_reason", None) for c in choices
        ]
    invocation.output_messages = _extract_output(response) if _should_capture() else None
```

## Handler Methods Reference

The `ExtendedTelemetryHandler` provides these start/stop/fail triples:

| Operation | start | stop | fail |
|---|---|---|---|
| LLM inference | `start_llm(invocation)` | `stop_llm(inv)` | `fail_llm(inv, error)` |
| Embeddings | `start_embedding(inv)` | `stop_embedding(inv)` | `fail_embedding(inv, err)` |
| Tool execution | `start_execute_tool(inv)` | `stop_execute_tool(inv)` | `fail_execute_tool(inv, err)` |
| Agent invocation | `start_invoke_agent(inv)` | `stop_invoke_agent(inv)` | `fail_invoke_agent(inv, err)` |
| Agent creation | `start_create_agent(inv)` | `stop_create_agent(inv)` | `fail_create_agent(inv, err)` |
| Retrieval | `start_retrieval(inv)` | `stop_retrieval(inv)` | `fail_retrieval(inv, err)` |
| Rerank | `start_rerank(inv)` | `stop_rerank(inv)` | `fail_rerank(inv, err)` |

Each also has a `@contextmanager` variant: `handler.llm(inv)`, `handler.embedding(inv)`, etc.
