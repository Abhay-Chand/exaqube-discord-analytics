# Questions and Walkthrough Practice

## Ten difficult plugin questions

### 1. Why is the registry not hardcoded?
**Testing:** extensibility. **Answer:** `discover_plugins()` imports modules and decorators register instances, so `core.py` does not change for each tool. **Follow-up:** What breaks? **Answer:** An import failure can fail startup; there is no isolation.

### 2. Why use both scanning and decorators?
**Testing:** mechanism versus policy. **Answer:** scanning imports modules; decorators explicitly choose which classes become tools. **Follow-up:** Is scanning itself registration? **Answer:** No.

### 3. Is the plugin layer a sandbox?
**Answer:** No. It is an abstraction and discovery boundary. Database permissions and SQL validation provide the relevant query safety.

### 4. How do arguments reach a plugin?
**Answer:** Provider JSON becomes `ToolCallRequest.arguments`, then `parse_arguments()` creates the Pydantic model, then `execute()` receives the typed object.

### 5. How does chart consume query output?
**Answer:** Through a session-local `ref_id` resolved by `ArtifactStore`.

### 6. What happens with an invalid reference?
**Answer:** `UNKNOWN_REF` becomes a structured plugin error returned to the model.

### 7. What happens if the model sends extra fields?
**Answer:** The current Pydantic configuration does not explicitly forbid extras, so they may be ignored.

### 8. What happens if a plugin returns malformed data?
**Answer:** Some errors become generic stream errors because only `PluginError` and timeout are caught.

### 9. Why no progress events for query/chart?
**Answer:** Each is one database or in-memory operation at this dataset size; fake progress would be misleading.

### 10. How would you add Excel export?
**Answer:** Add a Pydantic model, subclass `Plugin`, implement `execute`, register it, and add real progress/cancellation for long work. A download endpoint would still be needed.

## 20 basic questions

1. **What does the project do?** Natural-language Discord analytics with charts and pins.
2. **Where does FastAPI start?** `backend/app/main.py`.
3. **What is the chat endpoint?** `POST /api/chat`.
4. **How does the browser receive progress?** SSE over a POST response.
5. **What is a session?** In-memory messages, artifacts, and a lock.
6. **Which tools exist?** `query` and `chart`.
7. **What validates arguments?** Pydantic.
8. **What validates SQL?** SQLGlot AST traversal.
9. **What role runs agent SQL?** `agent_ro`.
10. **What does query return?** A result reference and preview.
11. **What does chart consume?** A query result reference.
12. **What do pins store?** Query SQL, chart args, cache, and title.
13. **What happens on restart?** Sessions/artifacts disappear; pins remain.
14. **What is the row cap?** 5,000.
15. **What is the query preview?** 15 rows.
16. **What is the iteration cap?** Eight rounds.
17. **Why is Chart.js local?** To avoid CDN failure.
18. **Why are there two DB roles?** Least privilege.
19. **What is the main frontend risk?** Unescaped server metadata in `innerHTML`.
20. **What is the biggest production gap?** No auth, authorization, or rate limiting.

## 20 intermediate questions

1. **Why does core not know SQL?** Dependency inversion through `Plugin`.
2. **Why use an artifact reference?** Avoid context flooding.
3. **Why are pins replayable?** Refs are ephemeral.
4. **Why use two pools?** Different database permissions.
5. **How does retry work?** Errors become tool messages; exact calls are counted.
6. **What does `retryable=False` do?** Informs the model, but does not hard-stop the loop.
7. **How are streamed tool calls assembled?** Argument fragments accumulate by call index.
8. **Why separate scatter?** Raw points have different semantics from aggregates.
9. **What does `consumes` do?** Documentation only; not automatic type enforcement.
10. **Why not entry points?** One repository and container.
11. **What does the lock prevent?** Same-session history races.
12. **What does it not prevent?** Global overload or distributed-state problems.
13. **How does frontend render a chart?** It sees a chart-spec tool result.
14. **What happens with empty rows?** Chart returns `EMPTY_RESULT`.
15. **How is LIMIT enforced?** SQL rewrite plus database/application controls.
16. **What is semantic SQL failure?** Valid SQL answering the wrong question.
17. **How is data injection addressed?** Prompt instruction plus least-privileged tools.
18. **What happens when config is missing?** Startup fails loudly.
19. **Why no ORM?** Small schema and transparent analytical SQL.
20. **What is not tested?** There are no real test functions in `backend/tests`.

## 20 advanced questions

1. **Is AST validation sufficient?** No; it is one layer.
2. **Can a SELECT be expensive?** Yes; row caps do not cap intermediate work.
3. **What if a plugin raises `KeyError`?** Generic stream/API failure.
4. **What if the provider hangs?** No explicit application provider timeout.
5. **Can sessions be hijacked?** A caller with a UUID can reuse one.
6. **Can pins be cross-user?** Yes; users are not modeled.
7. **Can artifacts exhaust memory?** Yes; no eviction exists.
8. **Can data influence model reasoning?** Yes; prompt defense is not structural.
9. **Can chart sorting fail?** Yes, with mixed x-axis types.
10. **Can scatter exceed its cap?** Potentially due to per-series rounding.
11. **Can pagination cause a 500?** Negative values may reach Postgres.
12. **Can an assistant tool message be malformed?** Yes, if provider IDs/names are missing.
13. **What does a restart lose?** Conversation history and refs.
14. **Does the app scale horizontally?** Not without shared session state.
15. **What does database least privilege not solve?** Data overexposure to an authorized caller.
16. **Can pins become stale?** Yes, after schema changes.
17. **Can partial tool failure occur?** Yes, multi-tool calls continue sequentially.
18. **Why is the prompt not a security boundary?** The model can disobey or be influenced.
19. **What should replace unlimited retries?** Token, time, tool, and cost budgets.
20. **What is the first production change?** Auth plus resource controls.

## 20 design-breaking questions

1. Can I write to Postgres? Normally no: AST guard and `agent_ro` block writes.
2. Can I read pinned charts through the agent? No: role lacks permission.
3. Can I create unlimited sessions? Yes: no auth or quotas.
4. Can I create unlimited artifacts? Yes: no eviction.
5. Can I issue 500 expensive questions? Yes: no rate limit or budget.
6. Can I access another user’s pins? Yes: no user ownership.
7. Can I reuse a known session UUID? Yes: no identity binding.
8. Can a message body prompt-inject the model? Potentially: mitigation is prompt-level.
9. Can a server name XSS the browser? Potentially: unescaped `innerHTML`.
10. Can I force an infinite single turn? Not forever: eight iterations.
11. Can I force a long request? Yes: no chat/provider request limit.
12. Can a legal query be wrong? Yes: semantic correctness is not checked.
13. Can a chart fail on data shape? Yes: mixed types and malformed rows.
14. Can pinning select the wrong query? Yes: frontend tracks latest calls rather than correlated successes.
15. Can partial tool results be committed? Yes: tools execute independently.
16. Can a broken plugin prevent startup? Yes: import occurs during discovery.
17. Can the model call a nonretryable tool again? It can attempt it; core does not hard-stop immediately.
18. Can the API reveal SQL/database errors? Some paths expose raw details.
19. Can CORS allow any site? Yes: wildcard configuration.
20. Is this production-ready? No; it needs tenancy, budgets, secrets, tests, and stronger operational controls.

## 20-30 minute walkthrough

**Interviewer:** Walk me through the project.

**Me:** The browser sends a chat request through nginx to FastAPI. The chat route retrieves a session and streams agent events. The agent core sends conversation messages and dynamically generated plugin schemas to the provider. The model can call query, then chart. Query validates SQL and stores a result reference. Chart resolves it and returns a frontend chart specification.

**Interviewer:** Why not put SQL in the route?

**Me:** The route should handle HTTP and streaming. SQL is a plugin capability, so the agent can orchestrate it without knowing implementation details.

**Interviewer:** How is a plugin discovered?

**Me:** Startup scans the plugin package and imports modules. The `@register_plugin` decorator instantiates and registers each plugin. The registry is then converted into tool schemas.

**Interviewer:** Why is the schema not handwritten?

**Me:** The Pydantic input model is both the runtime validator and the source of the JSON schema sent to the model, reducing drift.

**Interviewer:** What happens after query execution?

**Me:** Full rows remain server-side in `ArtifactStore`; the model receives a reference, row count, and preview. Chart receives the reference and builds a chart spec.

**Interviewer:** What stops SQL writes?

**Me:** SQLGlot requires a single SELECT and walks the AST for DML, DDL, SELECT INTO, and dangerous functions. The database role is read-only as a second boundary.

**Interviewer:** Is it impossible to abuse?

**Me:** No. Expensive legal SELECTs, data overexposure, prompt injection, and unauthenticated access remain risks.

**Interviewer:** What happens on tool failure?

**Me:** `PluginError` becomes a structured tool message. The model may retry. Exact repeated calls are limited, and the turn stops after eight iterations.

**Interviewer:** What is imperfect about that retry design?

**Me:** `retryable=False` is advisory rather than enforced directly, and cosmetically different calls can consume the full iteration budget.

**Interviewer:** What happens with concurrent requests?

**Me:** The per-session lock serializes them. That fixes same-process history races but does not solve multi-worker state or queue overload.

**Interviewer:** What happens after a restart?

**Me:** Chat sessions and artifact references disappear. Pins remain because they store query and chart arguments and replay both plugins.

**Interviewer:** Find a pin bug.

**Me:** The frontend records the latest query and chart call events. With multiple or failed calls, it can store a query that does not correspond to the chart being pinned.

**Interviewer:** Find a security bug.

**Me:** There is no authentication or authorization. In addition, server metadata is inserted into `innerHTML` without escaping and CORS is wildcarded.

**Interviewer:** What would you fix first?

**Me:** Authentication and ownership, then rate/resource budgets and memory eviction. I would also add executable tests for the SQL guard, plugin chaining, retries, chart limits, and pin correlation.

## Thirty “why this way?” prompts

1. **Why structure the core around interfaces?** To isolate orchestration from vendors and tools.
2. **Why scan a directory?** It is simple for one repository.
3. **Why use a decorator?** It makes registration explicit.
4. **Why use Pydantic?** One model drives validation and tool schema.
5. **Why use references?** Avoid passing full data through the model.
6. **Why keep artifacts in memory?** Simple session-local chaining.
7. **Why make pins replayable?** They must survive conversation loss.
8. **Why separate query and chart?** Retrieval and presentation are different capabilities.
9. **Why separate scatter logic?** Scatter does not aggregate by x.
10. **Why use AST parsing?** Regexes do not understand SQL structure.
11. **Why use a read-only role?** Database enforcement is defense in depth.
12. **Why use separate pools?** Different permissions for different responsibilities.
13. **Why use SSE?** It streams over ordinary HTTP.
14. **Why vendor Chart.js?** Avoid CDN availability failures.
15. **Why handwritten SQL?** Analytical SQL stays visible and direct.
16. **Why cap rows?** Protect model context and response size.
17. **Why cap iterations?** Prevent infinite tool loops.
18. **Why lock sessions?** Prevent concurrent history mutation.
19. **Why structured errors?** Let the model react without string parsing.
20. **Why allow model retries?** It can correct generated SQL.
21. **Why let the model generate SQL?** Support open-ended analytics.
22. **Why put dataset rules in the prompt?** Give date, grain, and data-quality context.
23. **Why return specs instead of images?** They are replayable and frontend-stylable.
24. **Why separate data-access queries?** Keep deterministic API SQL out of route handlers.
25. **Why last-row-wins duplicate members?** Deterministic idempotent loading.
26. **Why interpret timestamps as UTC?** Source timestamps have no offset.
27. **Why use a global registry?** The plugin set is static in one process.
28. **Why expose only a preview?** Give the model shape without flooding context.
29. **Why disable the chat UI during a turn?** Make backend serialization visible to users.
30. **Why not implement Excel/PPT now?** Avoid claiming capabilities that do not work.
