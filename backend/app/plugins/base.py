"""
The plugin contract.

A plugin is a self-contained capability the agent can call as an LLM tool.
Adding one means writing one file in this package and nothing else — no
edits to the agent core, the router, or the system prompt. The agent's tool
list and the JSON schema it sends to the LLM are both derived from
`PluginRegistry` at request time (see registry.py), never hardcoded.

Design decisions, and what they cost:

- Chaining is done through `ArtifactStore` refs, not by handing raw data
  back to the LLM. When `query` returns 4,000 rows, the agent does not see
  4,000 rows of JSON — it sees a `ResultRef` (id + shape + a small preview).
  A later plugin call in the same turn (e.g. `chart`) takes that ref as an
  argument and the *server* resolves it, never round-tripping the full
  payload through the model. This is a deliberate answer to "how does a
  plugin consume another plugin's output": by reference, not by value.
  Cost: plugins that want to inspect the LLM's view of the data have to
  resolve the ref themselves; the LLM only ever reasons about shape/preview.

- Errors are structured (`PluginError`) with a `retryable` flag rather than
  a raw exception string, so the agent loop can decide "feed this back to
  the model and let it try again" vs "this will never succeed, surrender
  now" without string-sniffing a message.

- Streaming progress is optional (`stream_progress`), because not every
  plugin has meaningful intermediate states — `query` genuinely doesn't
  (it's one round-trip to Postgres), `chart` doesn't either at this
  dataset's size. The hook exists on the base class so a slower plugin
  (a real `excel`/`pptx` export doing multiple sheets) can use it without
  changing the interface. We do not fake progress events for query/chart —
  a progress bar with one fake tick is worse than no progress bar.

- Argument validation is a pydantic model per plugin (`input_model`), not
  hand-rolled dict checks. Validation errors become PluginError(code=
  "INVALID_ARGUMENTS", retryable=True) so the agent can see exactly what was
  wrong and retry with corrected arguments, rather than the plugin crashing.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, ClassVar

from pydantic import BaseModel, ValidationError


class PluginError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = True, details: dict | None = None):
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable, "details": self.details}


@dataclass
class ResultRef:
    """A reference to a plugin's output, stored server-side. The LLM sees
    `ref_id` + `preview` + `row_count`/`shape` — never the full payload — so
    a 5,000-row result doesn't blow the context window or give the model
    something to be manipulated by (e.g. injected text inside message
    content) when it's just supposed to be forwarding data to a chart."""

    ref_id: str
    kind: str  # "result_set" | "chart_spec" | ...
    row_count: int | None = None
    preview: Any = None
    full_data: Any = None  # only ever read server-side by another plugin

    def summary(self) -> dict:
        return {"ref_id": self.ref_id, "kind": self.kind, "row_count": self.row_count, "preview": self.preview}


@dataclass
class PluginResult:
    ref: ResultRef
    display_text: str  # what the agent should say to the user about this result
    progress_events: list[dict] = field(default_factory=list)


class ArtifactStore:
    """In-memory, per-conversation store for ResultRefs, so one plugin's
    output can be handed to the next by reference within the same turn.
    Deliberately not persisted — pinning (a *separate* concept) copies out
    the query+args it needs, not a ref into this store, so a pin survives
    process restarts and this store doesn't have to."""

    def __init__(self):
        self._refs: dict[str, ResultRef] = {}

    def put(self, kind: str, full_data: Any, preview: Any, row_count: int | None = None) -> ResultRef:
        ref = ResultRef(ref_id=str(uuid.uuid4()), kind=kind, row_count=row_count, preview=preview, full_data=full_data)
        self._refs[ref.ref_id] = ref
        return ref

    def get(self, ref_id: str) -> ResultRef:
        if ref_id not in self._refs:
            raise PluginError("UNKNOWN_REF", f"No such result ref: {ref_id}", retryable=True)
        return self._refs[ref_id]


@dataclass
class PluginContext:
    """Everything a plugin's execute() gets besides its own arguments."""

    store: ArtifactStore
    db_pool: Any  # asyncpg.Pool, typed loosely here to avoid a circular import
    row_cap: int = 5_000


class Plugin(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]
    # Declares what kind of ResultRef this plugin can consume as input, if
    # any — used only for documentation/introspection right now; the actual
    # binding happens because the input_model has a `ref_id: str` field.
    consumes: ClassVar[str | None] = None
    produces: ClassVar[str] = "result_set"
    supports_progress: ClassVar[bool] = False

    def parse_arguments(self, raw_args: dict) -> BaseModel:
        try:
            return self.input_model.model_validate(raw_args)
        except ValidationError as e:
            raise PluginError(
                "INVALID_ARGUMENTS",
                f"{self.name}: arguments failed validation: {e}",
                retryable=True,
                details={"errors": e.errors()},
            ) from e

    @abstractmethod
    async def execute(self, args: BaseModel, ctx: PluginContext) -> PluginResult: ...

    async def stream_progress(self, args: BaseModel, ctx: PluginContext) -> AsyncIterator[dict]:
        """Default: no intermediate progress. Override + set
        supports_progress=True for plugins with real intermediate state."""
        return
        yield  # pragma: no cover - makes this an async generator

    def tool_schema(self) -> dict:
        """What gets sent to the LLM as a callable tool. Derived from the
        pydantic model, never hand-written, so the schema can't drift from
        what parse_arguments() actually accepts."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }
