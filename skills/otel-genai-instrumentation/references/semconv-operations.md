# GenAI Semantic Conventions - Operations Reference

Status: **Development** (all sections)
Opt-in: `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`

## Operation Types

Well-known values for `gen_ai.operation.name` (as of 2026-03, semconv
status: Development — this list may grow, check the
[official spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/)
for the latest):

| Operation | SpanKind | Span Name Pattern | Typical API |
|---|---|---|---|
| `chat` | CLIENT | `chat {model}` | OpenAI Chat, Anthropic Messages |
| `generate_content` | CLIENT | `generate_content {model}` | Gemini |
| `text_completion` | CLIENT | `text_completion {model}` | Legacy completions |
| `embeddings` | CLIENT | `embeddings {model}` | Embedding APIs |
| `retrieval` | CLIENT | `retrieval {data_source_id}` | Vector search / knowledge base |
| `execute_tool` | INTERNAL | `execute_tool {tool_name}` | Function / tool execution |
| `create_agent` | CLIENT | `create_agent {agent_name}` | Remote agent creation |
| `invoke_agent` | CLIENT or INTERNAL | `invoke_agent {agent_name}` | CLIENT=remote, INTERNAL=local |

## Span Hierarchy

```
invoke_agent "assistant"             (INTERNAL for local agent frameworks)
├── chat "gpt-4o"                    (CLIENT - first LLM turn)
│   finish_reasons: ["tool_calls"]
├── execute_tool "search_flights"    (INTERNAL)
├── chat "gpt-4o"                    (CLIENT - second LLM turn with tool result)
│   finish_reasons: ["stop"]
└── ...
```

## Attributes by Operation

### Inference Spans (chat / generate_content / text_completion)

**Set at span creation (sampling-critical):**

| Attribute | Requirement | Type |
|---|---|---|
| `gen_ai.operation.name` | Required | string |
| `gen_ai.provider.name` | Required | string |
| `gen_ai.request.model` | Cond. Required | string |
| `server.address` | Recommended | string |
| `server.port` | Cond. Required (if server.address set) | int |

**Set before span ends:**

| Attribute | Requirement | Type |
|---|---|---|
| `error.type` | Cond. Required (on error) | string |
| `gen_ai.response.model` | Recommended | string |
| `gen_ai.response.id` | Recommended | string |
| `gen_ai.response.finish_reasons` | Recommended | string[] |
| `gen_ai.usage.input_tokens` | Recommended | int |
| `gen_ai.usage.output_tokens` | Recommended | int |
| `gen_ai.usage.cache_read.input_tokens` | Recommended | int |
| `gen_ai.usage.cache_creation.input_tokens` | Recommended | int |
| `gen_ai.conversation.id` | Cond. Required (when available) | string |
| `gen_ai.output.type` | Cond. Required (if output format set) | string |
| `gen_ai.request.temperature` | Recommended | double |
| `gen_ai.request.max_tokens` | Recommended | int |
| `gen_ai.request.top_p` | Recommended | double |
| `gen_ai.request.top_k` | Recommended | double |
| `gen_ai.request.frequency_penalty` | Recommended | double |
| `gen_ai.request.presence_penalty` | Recommended | double |
| `gen_ai.request.stop_sequences` | Recommended | string[] |
| `gen_ai.request.seed` | Cond. Required (if applicable) | int |
| `gen_ai.request.choice.count` | Cond. Required (if != 1) | int |

**Opt-In (sensitive, off by default):**

| Attribute | Type | Notes |
|---|---|---|
| `gen_ai.input.messages` | any (JSON) | Contains PII |
| `gen_ai.output.messages` | any (JSON) | Contains PII |
| `gen_ai.system_instructions` | any (JSON) | May contain sensitive info |
| `gen_ai.tool.definitions` | any (JSON) | Can be very large |

### Embeddings Span

**Set at span creation:**

Same as inference: `gen_ai.operation.name`, `gen_ai.provider.name`,
`gen_ai.request.model`, `server.address`, `server.port`

**Set before span ends:**

| Attribute | Requirement | Type |
|---|---|---|
| `error.type` | Cond. Required (on error) | string |
| `gen_ai.embeddings.dimension.count` | Recommended | int |
| `gen_ai.request.encoding_formats` | Recommended | string[] |
| `gen_ai.usage.input_tokens` | Recommended | int |

### Retrieval Span

**Set at span creation:**

| Attribute | Requirement |
|---|---|
| `gen_ai.operation.name` | Required |
| `gen_ai.data_source.id` | Cond. Required |
| `gen_ai.provider.name` | Cond. Required |
| `gen_ai.request.model` | Cond. Required |

**Opt-In:**

| Attribute | Type |
|---|---|
| `gen_ai.retrieval.query.text` | string (sensitive) |
| `gen_ai.retrieval.documents` | JSON (array of {id, score}) |

### Execute Tool Span

SpanKind: **INTERNAL**

| Attribute | Requirement | Type |
|---|---|---|
| `gen_ai.operation.name` | Required | string (= `execute_tool`) |
| `gen_ai.tool.name` | Recommended | string |
| `gen_ai.tool.call.id` | Recommended | string |
| `gen_ai.tool.type` | Recommended | string: `function` / `extension` / `datastore` |
| `gen_ai.tool.description` | Recommended | string |
| `error.type` | Cond. Required (on error) | string |
| `gen_ai.tool.call.arguments` | Opt-In | any (sensitive) |
| `gen_ai.tool.call.result` | Opt-In | any (sensitive) |

### Agent Spans (create_agent / invoke_agent)

`invoke_agent` has the **union** of inference attrs + agent attrs:

| Attribute | Requirement | Type |
|---|---|---|
| `gen_ai.agent.name` | Cond. Required | string |
| `gen_ai.agent.id` | Cond. Required | string |
| `gen_ai.agent.description` | Cond. Required | string |
| `gen_ai.agent.version` | Cond. Required | string |
| (plus all inference span attributes) | | |

`create_agent` is CLIENT kind, used for remote agent services.

## Metrics

| Metric | Type | Unit | Requirement |
|---|---|---|---|
| `gen_ai.client.operation.duration` | Histogram | `s` | **Required** |
| `gen_ai.client.token.usage` | Histogram | `{token}` | Recommended |

`gen_ai.client.token.usage` requires `gen_ai.token.type` attribute with value
`input` or `output`.

Bucket boundaries for duration:
`[0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]`

Bucket boundaries for tokens:
`[1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]`

## Content Capture

Controlled by env var `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`.

- Default: **off** (do not record content)
- When on, messages follow the parts-based JSON schema:

```json
[
  {
    "role": "system|user|assistant|tool",
    "parts": [
      {"type": "text", "content": "..."},
      {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}},
      {"type": "tool_call_response", "id": "...", "response": "..."},
      {"type": "reasoning", "content": "..."},
      {"type": "blob", "data": "base64...", "mime_type": "image/png"},
      {"type": "uri", "uri": "https://...", "mime_type": "..."}
    ],
    "finish_reason": "stop|tool_calls|..."
  }
]
```

## Events (Logs-based)

Old per-message span events are **deprecated**. Current spec uses Logs API:

| Event Name | Purpose |
|---|---|
| `gen_ai.client.inference.operation.details` | Full inference details (opt-in) |
| `gen_ai.evaluation.result` | Evaluation scores |

Most language SDKs don't fully support Logs-based events yet.
For now, use span attributes for content capture (this is what LoongSuite does).

## Well-Known Provider Names

`openai`, `anthropic`, `aws.bedrock`, `azure.ai.inference`, `azure.ai.openai`,
`cohere`, `deepseek`, `gcp.gemini`, `gcp.gen_ai`, `gcp.vertex_ai`, `groq`,
`ibm.watsonx.ai`, `mistral_ai`, `perplexity`, `x_ai`

## gen_ai.system vs gen_ai.provider.name

The semconv is migrating from `gen_ai.system` to `gen_ai.provider.name`.
For new instrumentations:

- **LLM SDKs** (OpenAI, Anthropic, Cohere, etc.): use `gen_ai.provider.name`
  with one of the well-known values above.
- **Frameworks/protocols** (CrewAI, A2A, MCP, LangChain): use `gen_ai.system`
  with the framework/protocol name (e.g., `"a2a"`, `"crewai"`, `"langchain"`).
  These are not LLM providers — they orchestrate across providers.

When in doubt, set both: `gen_ai.system` for the framework name AND
`gen_ai.provider.name` for the underlying LLM provider (if known at
instrumentation time).

## Protocol-Layer Instrumentation (A2A, MCP)

Protocol frameworks like A2A and MCP operate at the **transport/protocol
layer** between agents, not at the LLM API layer. Key differences:

- **Dual-side spans**: instrument both CLIENT (outgoing call) and SERVER
  (incoming handler) sides.
- **No model/tokens**: these protocols don't directly call LLMs, so
  `gen_ai.request.model`, `gen_ai.usage.*` are typically not applicable.
- **Agent metadata**: extract `gen_ai.agent.name`, `gen_ai.agent.description`,
  `gen_ai.agent.version` from the protocol's agent discovery mechanism
  (e.g., AgentCard in A2A).
- **Primary operation**: usually `invoke_agent` (CLIENT for outgoing,
  SERVER for incoming).
- **Built-in tracing**: these protocols often have their own OTel tracing
  already. Your instrumentation adds GenAI semantic attributes on top.
