# Defense Sheet

## Ten strongest design decisions

1. Provider abstraction keeps OpenAI details out of the agent core.
2. Plugin contract keeps SQL and chart logic out of orchestration.
3. Pydantic models generate tool schemas and validate runtime arguments.
4. SQLGlot AST validation is stronger than keyword filtering.
5. `agent_ro` is read-only at the database level.
6. Query results stay server-side behind artifact references.
7. Same-session turns use an `asyncio.Lock`.
8. Agent loops have bounded iterations.
9. Pins store replayable plans rather than ephemeral references.
10. Structured errors and trace IDs improve diagnosis.

## Ten weakest areas

1. No authentication.
2. No authorization or user-scoped pins.
3. No rate limiting.
4. No per-session budget.
5. No artifact/session expiry.
6. Hardcoded application database passwords.
7. Prompt injection remains model-dependent.
8. Provider timeout and retry behavior is incomplete.
9. No executable regression suite.
10. Unescaped server metadata can reach `innerHTML`.

## Ten biggest failure modes

1. Memory exhaustion from sessions and artifacts.
2. Unlimited expensive queries.
3. Cross-user pin access.
4. Reuse of a known session UUID.
5. Provider request hanging.
6. Database outage during a request.
7. Valid but semantically wrong SQL.
8. Prompt injection through message content.
9. Mixed-type chart data failure.
10. Wrong query/chart association during pinning.

## Ten most important files

1. [backend/app/agent/core.py](../backend/app/agent/core.py)
2. [backend/app/agent/provider.py](../backend/app/agent/provider.py)
3. [backend/app/agent/sql_guard.py](../backend/app/agent/sql_guard.py)
4. [backend/app/agent/prompts.py](../backend/app/agent/prompts.py)
5. [backend/app/plugins/base.py](../backend/app/plugins/base.py)
6. [backend/app/plugins/registry.py](../backend/app/plugins/registry.py)
7. [backend/app/plugins/query_plugin.py](../backend/app/plugins/query_plugin.py)
8. [backend/app/plugins/chart_plugin.py](../backend/app/plugins/chart_plugin.py)
9. [backend/scripts/schema.sql](../backend/scripts/schema.sql)
10. [backend/app/api/routes_chat.py](../backend/app/api/routes_chat.py)

## Twenty functions/classes to know

1. `ChatSession`
2. `run_turn`
3. `_run_turn_locked`
4. `LLMProvider.stream`
5. `OpenAIProvider.stream`
6. `_to_openai_messages`
7. `_to_openai_tools`
8. `register_plugin`
9. `discover_plugins`
10. `Plugin.parse_arguments`
11. `Plugin.tool_schema`
12. `ArtifactStore.put`
13. `ArtifactStore.get`
14. `QueryPlugin.execute`
15. `ChartPlugin.execute`
16. `ChartPlugin._build_aggregated`
17. `ChartPlugin._build_scatter`
18. `validate_select`
19. `run_pin_spec`
20. `load_settings`

## Twenty concepts to understand

1. Async generators
2. SSE
3. Provider abstraction
4. Function/tool calling
5. Pydantic validation
6. JSON Schema
7. Import-time registration
8. Dependency inversion
9. SQL AST parsing
10. SQL injection
11. Least privilege
12. Read-only database roles
13. Statement timeouts
14. Retry budgets
15. Conversation state
16. Concurrency locks
17. Process-local state
18. Replayable plans
19. Prompt injection
20. Semantic versus syntactic correctness

## Ten things never to claim

1. The agent cannot be prompt-injected.
2. The API is production secure.
3. The registry is a sandbox.
4. The row cap prevents expensive queries.
5. Nonretryable errors always stop immediately.
6. Pins are user-owned.
7. Chat survives restart.
8. Model-generated analytics are always correct.
9. The SQL guard blocks every database attack.
10. The project has comprehensive automated tests.

## Ten things you can confidently say

1. The core is decoupled from concrete plugins.
2. Pydantic models produce tool schemas.
3. SQL is AST-validated.
4. The agent uses a dedicated read-only DB role.
5. Database permissions back up application validation.
6. Large results remain server-side.
7. Query and chart are separate capabilities.
8. Pins replay deterministic plans.
9. Same-session turns are serialized.
10. The agent loop is bounded.

## One-week improvement plan

### First day

- Add authentication and authorization.
- Add rate limiting and resource budgets.
- Bound session and artifact retention.
- Fix provider timeout and plugin exception classification.
- Add tests for SQL, retries, chaining, charts, and pins.

### Remaining week

- Persist sessions or use Redis/Postgres shared state.
- Add query cost controls and column-level policy.
- Fix pin event correlation.
- Fix frontend escaping and failed action handling.
- Replace hardcoded role credentials with secrets.
- Add dependency scanning and operational metrics.
