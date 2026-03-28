# LoongSuite Repository Conventions

Rules specific to the `loongsuite-python-agent` repository.

## Directory Layout

New GenAI instrumentations go under `instrumentation-loongsuite/`:

```
instrumentation-loongsuite/
└── loongsuite-instrumentation-{name}/
    ├── pyproject.toml
    ├── README.rst
    ├── CHANGELOG.md           # optional
    └── src/
        └── opentelemetry/
            ├── __init__.py    # empty (namespace package)
            └── instrumentation/
                ├── __init__.py    # empty (namespace package)
                └── {name}/
                    ├── __init__.py    # Instrumentor class
                    ├── package.py     # _instruments tuple
                    ├── version.py     # __version__
                    ├── utils.py       # helpers (optional)
                    └── patch/         # (Pattern A only)
                        ├── __init__.py
                        └── {operation}.py
```

The namespace `__init__.py` files are empty or contain only the namespace
package declaration. Do NOT put code in them.

## pyproject.toml Template

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "loongsuite-instrumentation-{name}"
dynamic = ["version"]
description = "LoongSuite {Name} instrumentation"
readme = "README.rst"
license = "Apache-2.0"
requires-python = ">=3.9"
```

**Python version:** The default is `>=3.9`, but check the target library's
own `requires-python`. If it requires a higher version (e.g., browser-use
requires `>=3.11`), use that instead. Also adjust the `classifiers` list
to match (remove unsupported versions like 3.9, 3.10).
authors = [
  { name = "OpenTelemetry Authors", email = "cncf-opentelemetry-contributors@lists.cncf.io" },
]
classifiers = [
  "Development Status :: 4 - Beta",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: Apache Software License",
  "Programming Language :: Python",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.9",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
]
dependencies = [
  "opentelemetry-api ~= 1.37",
  "opentelemetry-instrumentation >= 0.58b0",
  "opentelemetry-semantic-conventions >= 0.58b0",
  "opentelemetry-util-genai > 0.2b0",
]

[project.optional-dependencies]
instruments = [
  "{library} >= {min_version}",
]

[project.entry-points.opentelemetry_instrumentor]
{name} = "opentelemetry.instrumentation.{name}:{Name}Instrumentor"

[project.urls]
Homepage = "https://github.com/alibaba/loongsuite-python-agent/tree/main/instrumentation-loongsuite/loongsuite-instrumentation-{name}"
Repository = "https://github.com/alibaba/loongsuite-python-agent"

[tool.hatch.version]
path = "src/opentelemetry/instrumentation/{name}/version.py"

[tool.hatch.build.targets.sdist]
include = ["/src", "/tests"]

[tool.hatch.build.targets.wheel]
packages = ["src/opentelemetry"]
```

## package.py

```python
_instruments = ("{library} >= {min_version}",)
_supports_metrics = False
```

## version.py

```python
__version__ = "0.1.0.dev"
```

## License Header

Every `.py` file MUST start with:

```python
# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
```

## Dependencies

All LoongSuite GenAI instrumentations depend on:

| Package | Version Constraint | Purpose |
|---|---|---|
| `opentelemetry-api` | `~= 1.37` | Core API |
| `opentelemetry-instrumentation` | `>= 0.58b0` | BaseInstrumentor, unwrap |
| `opentelemetry-semantic-conventions` | `>= 0.58b0` | Attribute constants |
| `opentelemetry-util-genai` | `> 0.2b0` | TelemetryHandler, types (Pattern A only) |

Version constraint style:
- `opentelemetry-api` uses `~=` (compatible release) because breaking changes
  across major versions are expected.
- All other OTel packages use `>=` (minimum version) to allow flexible upgrades.
- Do NOT mix `~=` and `>=` inconsistently. Follow the table above exactly.

Optional: `wrapt` is a transitive dependency of `opentelemetry-instrumentation`.

## Import Conventions

```python
# BaseInstrumentor
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.utils import unwrap

# Semantic conventions — ALWAYS use these, never redefine as strings
from opentelemetry.semconv._incubating.attributes import gen_ai_attributes

# Handler (Pattern A)
from opentelemetry.util.genai.extended_handler import ExtendedTelemetryHandler

# Types (Pattern A)
from opentelemetry.util.genai.types import LLMInvocation, Error
from opentelemetry.util.genai.extended_types import (
    EmbeddingInvocation,
    ExecuteToolInvocation,
    InvokeAgentInvocation,
)

# Tracer (Pattern B)
from opentelemetry import trace as trace_api
from opentelemetry.trace import SpanKind, Status, StatusCode

# Metrics
from opentelemetry import metrics as metrics_api

# Monkey-patching
from wrapt import wrap_function_wrapper
```

**Semconv attribute constants rule:** Use `gen_ai_attributes.GEN_AI_*`
constants from `opentelemetry-semantic-conventions` for all standard
GenAI attributes. Do NOT redefine them as local string constants like
`_GEN_AI_SYSTEM = "gen_ai.system"`. This ensures:
- Centralized management — attribute names update with the semconv package
- Consistency across all instrumentations
- No risk of typos in attribute name strings

Only define local constants for domain-specific attributes that do NOT
exist in the semconv package (e.g., `_BU_TASK = "browser_use.task"`).

## Bootstrap Registration

After creating the package, run:

```bash
python scripts/loongsuite/generate_loongsuite_bootstrap.py
```

This scans `instrumentation-loongsuite/*/pyproject.toml` and regenerates
`loongsuite-distro/src/loongsuite/distro/bootstrap_gen.py`.

The entry point in pyproject.toml (`[project.entry-points.opentelemetry_instrumentor]`)
is what auto-instrumentation uses to discover your instrumentor at runtime.

## Test Conventions

```
tests/
├── conftest.py          # fixtures: exporter, provider, instrument/uninstrument
├── test_{operation}.py  # one file per operation type
```

### conftest.py pattern

```python
import os
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter

@pytest.fixture
def span_exporter():
    return InMemorySpanExporter()

@pytest.fixture
def tracer_provider(span_exporter):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    return provider

@pytest.fixture(autouse=True)
def environment():
    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "gen_ai_latest_experimental"
    yield
    os.environ.pop("OTEL_SEMCONV_STABILITY_OPT_IN", None)

@pytest.fixture
def instrument(tracer_provider):
    from opentelemetry.instrumentation.{name} import {Name}Instrumentor
    instrumentor = {Name}Instrumentor()
    instrumentor.instrument(tracer_provider=tracer_provider)
    yield
    instrumentor.uninstrument()
```
