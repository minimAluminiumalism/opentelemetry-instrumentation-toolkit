# OpenLLMetry Reference

[OpenLLMetry](https://github.com/traceloop/openllmetry) by Traceloop is an
open-source project that provides OTel-based auto-instrumentation for many
GenAI libraries. It is a valuable reference for identifying which functions
to patch and how to extract attributes.

## How to Use This Reference

When instrumenting a new library, **before designing your own patch points**:

1. Check if OpenLLMetry already instruments this library:
   ```
   https://github.com/traceloop/openllmetry/tree/main/packages/opentelemetry-instrumentation-{library}
   ```

2. If it does, study:
   - **Which methods they patch** — these are the proven hook points
   - **How they extract model, tokens, messages** — the attribute mapping logic
   - **How they handle streaming** — streaming is the hardest part to get right
   - **What they got wrong** — OpenLLMetry predates the official GenAI semconv,
     so attribute names may differ. Always use the official semconv names.

3. Use their implementation as a **starting point**, not a copy. Key differences
   between OpenLLMetry and our LoongSuite approach:

| Aspect | OpenLLMetry | LoongSuite |
|---|---|---|
| Span management | Direct tracer calls | ExtendedTelemetryHandler (Pattern A) or direct (Pattern B/C) |
| Semconv compliance | Mixed (pre-standard + standard) | Must follow latest GenAI semconv |
| Metrics | Optional | Required (`gen_ai.client.operation.duration`) |
| Content capture | Various env vars | `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` only |
| Fail-open | Not always | Required on all patches |

## OpenLLMetry Instrumented Libraries

As of 2026, OpenLLMetry covers:

- **LLM SDKs**: OpenAI, Anthropic, Cohere, Google Generative AI, AWS Bedrock,
  Mistral, Groq, Ollama, Replicate, Together AI, HuggingFace
- **Frameworks**: LangChain, LlamaIndex, Haystack, CrewAI
- **Vector DBs**: Pinecone, Chroma, Qdrant, Weaviate, Milvus

## Example: Using OpenLLMetry as Reference

If you're adding Cohere instrumentation:

1. Read `openllmetry/packages/opentelemetry-instrumentation-cohere/`
2. Note they patch `Client.chat()`, `Client.embed()`, `Client.rerank()`
3. Note how they extract `response.meta.tokens` for usage tracking
4. Adapt to LoongSuite patterns:
   - Use `ExtendedTelemetryHandler.start_llm()` instead of raw tracer
   - Use official semconv attribute names
   - Add streaming wrapper for `Client.chat_stream()`
   - Add fail-open try/except around the whole wrapper
