# Short Interview Answers

## 30-second project summary

This is a FastAPI and Postgres Discord analytics application. A user asks a natural-language question in the browser. The agent uses an OpenAI provider and two plugins: `query` generates and executes a read-only SQL query, and `chart` transforms a query result into a Chart.js specification. Results are passed between plugins through server-side references rather than through the model context. Charts can be pinned by storing the query and chart arguments so they can be replayed later.

## 60-second architecture answer

The browser sends `POST /api/chat` through nginx. `routes_chat.py` creates an in-memory `ChatSession` and calls `run_turn()` in `agent/core.py`. The core owns the conversation loop, provider calls, plugin lookup, structured errors, retries, and the eight-iteration limit. It does not know SQL or chart details. The registry discovers decorated plugin classes and builds tool schemas from their Pydantic input models. The query plugin validates SQL with SQLGlot and executes it using the read-only `agent_ro` role. It stores full rows in an `ArtifactStore` and returns a preview plus reference. The chart plugin resolves that reference and returns a chart specification. The frontend receives SSE events and renders the chart with Chart.js.

## Plugin layer answer

The plugin layer is an extensibility boundary. A plugin defines `name`, `description`, `input_model`, and `execute()`. `discover_plugins()` imports plugin modules, and `@register_plugin` adds instances to the registry. The agent builds its available tool list from that registry. Arguments are validated by Pydantic before execution, and results use `PluginResult` and `ResultRef`. Adding a plugin requires a new module, a Pydantic model, an implementation, and the decorator. The design is reasonable for one repository, but it is not a sandbox, permission system, or production plugin marketplace.

## SQL safety answer

SQL is parsed as a PostgreSQL AST by SQLGlot. The guard permits exactly one `SELECT`, rejects DML and DDL anywhere in the tree, rejects `SELECT INTO`, blocks selected dangerous functions, and applies a maximum row limit. The database connection independently uses `agent_ro`, read-only transactions, and a five-second statement timeout. This is defense in depth. It does not guarantee semantic correctness, prevent every expensive legal query, or replace authentication and authorization.

## Artifact answer

The query plugin stores the complete result server-side and returns only a UUID reference, row count, and 15-row preview. The chart plugin receives the reference and resolves the full rows without sending them through the LLM. This protects context size and reduces exposure of user-authored message content. The trade-off is that artifacts are in memory, scoped to one process and one session, and have no eviction policy.

## Retry answer

A plugin failure becomes a structured tool message containing a code, message, retryable flag, and details. The model can correct invalid arguments or SQL. Identical tool calls are counted and the complete turn is limited to eight iterations. A limitation is that `retryable=False` is advisory; the core does not immediately stop a model from trying a different call.

## State answer

`ChatSession` contains conversation messages, an `ArtifactStore`, and an `asyncio.Lock`. The lock prevents concurrent requests for the same session from corrupting history. State is process-local and lost on restart. Pins are separate and durable because they store replayable SQL and chart arguments, not artifact references.

## Pin answer

A pin stores the query SQL, chart arguments, cached chart specification, and title. Refreshing a pin directly calls the query and chart plugins; it does not call the LLM. That makes refresh deterministic and allows pins to survive chat-session loss. A known frontend risk is that the current UI tracks the latest tool-call events and can associate the wrong query with a chart after multiple calls.

## Biggest weaknesses

1. No authentication or authorization.
2. No rate limiting or request budget.
3. Sessions and artifacts never expire.
4. Provider timeout/retry handling is incomplete.
5. Prompt injection is mostly prompt-level mitigation.
6. Database role passwords are hardcoded.
7. There are no real executable tests.
8. Server metadata is inserted into frontend `innerHTML` without escaping.
9. Semantic SQL correctness is not verified.
10. Pins are not user-scoped.

## Biggest strengths

1. Clear separation between agent, provider, plugins, and API.
2. Pydantic schemas generate both validation and tool definitions.
3. SQLGlot AST validation is stronger than keyword filtering.
4. Database-level read-only permissions back up the SQL guard.
5. Artifact references avoid passing full result sets through the model.
6. Same-session turns are protected by a lock.
7. Agent loops have iteration limits.
8. Pins replay deterministic plans instead of ephemeral references.
9. Errors have structured codes and trace IDs.
10. The frontend avoids rendering assistant links and images as live HTML.

## Safe phrases

- "That is not implemented yet."
- "The current code handles this partially, but it is not a complete production control."
- "The SQL guard protects execution safety more than semantic correctness."
- "The prompt is a mitigation, not a security boundary."
- "I chose this because the project is one repository and one container; a larger plugin ecosystem would justify entry points or a manifest."
- "The session lock solves same-session mutation races in one process, not distributed state."

## Claims to avoid

- "The agent cannot be prompt-injected."
- "The API is production secure."
- "The registry sandboxes plugins."
- "The row cap prevents expensive queries."
- "Pins are user-owned."
- "Chat survives restart."
- "All errors are retryable or correctly classified."
- "The model always produces correct analytics."
- "The SQL guard prevents every attack."
- "The project has comprehensive tests."
