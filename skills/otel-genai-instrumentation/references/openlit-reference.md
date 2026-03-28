# OpenLIT Reference

[OpenLIT](https://github.com/openlit/openlit) is an open-source observability
platform that provides OTel-based auto-instrumentation for GenAI libraries.
It can be used as a secondary reference (after OpenLLMetry) for identifying
instrumentable methods and attribute extraction patterns.

## How to Use This Reference

When instrumenting a new library:

1. Check if OpenLIT already instruments it:
   ```
   https://github.com/openlit/openlit/tree/main/sdk/python/src/openlit/instrumentation/{library}
   ```

2. If it does, study:
   - **Which methods they patch** — confirm against OpenLLMetry findings
   - **How they extract attributes** — OpenLIT may cover attributes that
     OpenLLMetry misses (or vice versa)
   - **Streaming handling** — compare approaches

3. Priority: **OpenLLMetry first, OpenLIT second.** If they disagree on
   which methods to patch, prefer OpenLLMetry's choices (it's more closely
   aligned with OTel community conventions). Use OpenLIT to fill gaps.

## Key Differences from OpenLLMetry

| Aspect | OpenLLMetry | OpenLIT |
|---|---|---|
| Focus | Pure OTel instrumentation | Full observability platform (OTel + UI) |
| Semconv alignment | Closer to official GenAI semconv | Mixed (own conventions + semconv) |
| Attribute names | Mostly standard | Some non-standard (e.g., `gen_ai.hub.owner`) |
| Span structure | Per-operation spans | Per-operation + wrapper spans |

## OpenLIT Instrumented Libraries

As of 2026, OpenLIT covers (Python SDK):

- **LLM SDKs**: OpenAI, Anthropic, Cohere, Mistral, Google AI, AWS Bedrock,
  Azure OpenAI, Groq, Ollama, Together AI, HuggingFace, DeepSeek, xAI
- **Frameworks**: LangChain, LlamaIndex, Haystack, CrewAI, AG2,
  ControlFlow, Julep, Letta, Phidata, Dynamiq
- **Vector DBs**: Pinecone, Chroma, Qdrant, Milvus, AstraDB
- **GPU monitoring**: NVIDIA GPU metrics
