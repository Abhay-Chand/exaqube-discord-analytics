# Failure and Security Review

## Severity

- **P0:** immediate production or tenant-isolation risk
- **P1:** high-impact correctness, availability, or security issue
- **P2:** meaningful edge case or reliability issue
- **P3:** low-impact polish or maintainability issue

## Hostile test matrix

| Attack/input | Likely current behavior | Handling | Severity | Fix |
|---|---|---|---|---|
| Empty message | Accepted and sent to the model | Partial | P2 | Require nonblank message |
| Very long message | No limit; context/provider failure possible | No | P1 | Add body and message limits |
| Nonsense question | Model usually gives a conversational response | Probabilistic | P2 | Add explicit intent/unsupported handling |
| Ambiguous question | Model chooses an interpretation | No guarantee | P2 | Require clarification for ambiguity |
| Missing tool field | Pydantic `INVALID_ARGUMENTS` | Yes | P2 | Add strict models and tests |
| Wrong field type | Pydantic catches many cases; coercion may occur | Partial | P2 | Use strict types where needed |
| Unknown tool name | `UNKNOWN_TOOL` tool message | Yes | P2 | Log and count unknown calls |
| Invalid JSON arguments | Converted to synthetic invalid argument | Partial | P2 | Validate provider output before history insertion |
| Tool unavailable | Unknown-tool or generic error | Partial | P1 | Health state and graceful capability removal |
| SQL syntax error | Structured SQL execution error | Yes | P2 | Sanitize public error text |
| Database timeout | Plugin timeout or Postgres error | Partial | P1 | Add cancellation and cost budgets |
| OpenAI timeout | Provider may remain open until SDK timeout | No | P1 | Configure explicit provider timeout |
| OpenAI network failure | SSE provider error | Partial | P1 | Retry transient failures with backoff |
| Unexpected provider chunk | Broad catch becomes provider error | Partial | P1 | Validate chunk shape and classify errors |
| Empty SQL result | Query succeeds; chart emits `EMPTY_RESULT` | Yes | P2 | Improve user-facing explanation |
| Incorrect SQL semantics | Valid but wrong answer may be explained confidently | No | P1 | Add query plans/templates/verification |
| Wrong tool selection | Model may call wrong or unnecessary tool | No | P1 | Add deterministic routing constraints |
| Multiple tools | Executed sequentially; partial success possible | Partial | P1 | Define transaction/compensation semantics |
| Repeated identical call | Exact-call retry cap applies | Partial | P2 | Enforce retryability in core |
| Repeated varied calls | Can consume all eight iterations | Bounded | P2 | Add tool/time/token budget |
| Infinite loop | Ends after `MAX_ITERATIONS` | Yes | P1 | Return reason and metrics |
| User prompt injection | Model may follow or resist it | Weak | P1 | Keep tools least-privileged; isolate data |
| Data prompt injection | Prompt rule only; preview reaches model | Weak | P1 | Separate untrusted data context and filtering |
| Rate abuse | Unlimited requests | No | P0 | Auth, quotas, rate limits |
| Missing environment variable | Startup fails | Yes | P2 | Keep fail-fast behavior |
| DB unavailable at startup | Service likely fails startup | Partial | P1 | Health/readiness and retry policy |
| DB unavailable during request | Generic API/SSE error | Partial | P1 | Classify and retry safe failures |
| Negative pagination | May reach Postgres and produce 500 | No | P2 | `ge=0` and `le` validation |
| Unexpected Unicode | Usually JSON-safe, no normalization policy | Mostly | P3 | Add encoding and normalization tests |
| Same-session concurrency | Lock serializes turns | Yes, one process | P1 | Shared state for multi-worker deployment |
| Different-session concurrency | No global budget | No | P1 | Global concurrency and DB pool limits |
| Session UUID reuse | Caller with UUID can reuse session | No auth | P0 | Bind session to authenticated subject |
| Session/artifact flooding | Memory grows indefinitely | No | P0 | TTL, quotas, eviction |
| Client disconnect | Stream closes; cancellation behavior is indirect | Partial | P2 | Explicit cancellation propagation |
| Malicious server name | Unescaped `innerHTML` option | No | P1 | Use `textContent`/DOM APIs |
| Malformed chart types | Pydantic catches enum errors | Yes | P2 | Add malformed row-shape tests |
| Mixed chart x-types | Category sort can raise `TypeError` | No | P2 | Normalize category values before sorting |
| Scatter cap edge case | Per-series rounding may exceed cap | No | P2 | Enforce final global cap |

## Security findings

### 1. No authentication or authorization

**Where:** all routes.

**Risk:** Any network caller can query data, create/delete/refresh pins, and use any known session UUID.

**Current protection:** None.

**Fix:** Add authentication, bind sessions and pins to an authenticated subject, and enforce ownership on every route.

### 2. Hardcoded database role passwords

**Where:** `backend/scripts/schema.sql` and `docker-compose.yml`.

**Risk:** Predictable credentials and weak deployment hygiene.

**Current protection:** The superuser password is environment-based, but role passwords are fixed.

**Fix:** Use secrets management or provision roles outside the application image.

### 3. Wildcard CORS

**Where:** `backend/app/main.py`.

**Risk:** Any origin may make browser requests. The configured `cors_origins` is unused.

**Fix:** Pass `settings.cors_origins` to `CORSMiddleware` and restrict methods/headers.

### 4. Stored XSS through server metadata

**Where:** `frontend/app.js`, `loadServers()`.

**Risk:** `server_id` and `server_name` are written into `innerHTML` without escaping.

**Fix:** Build `option` elements and assign `.value` and `.textContent`.

### 5. Prompt injection through data

**Where:** `agent/prompts.py` and query previews.

**Risk:** User-authored message content, usernames, and topics can influence model behavior.

**Current protection:** The system prompt says query data is inert. SQL and database permissions provide separate execution protection.

**Missing protection:** No structural separation of data from instructions and no model-independent semantic filter.

### 6. Resource exhaustion

**Where:** session map, artifact store, chat route, query plugin.

**Risk:** Unlimited sessions, artifacts, requests, and expensive legal queries.

**Fix:** Authentication, quotas, concurrency limits, per-turn budgets, TTLs, and bounded artifact storage.

### 7. Error-detail exposure

**Where:** provider error events, SQL execution errors, health endpoint.

**Risk:** Internal implementation and database details can reach clients.

**Fix:** Use public error codes/messages and keep raw details only in protected logs.

### 8. Database data exposure

**Where:** `query` plugin.

**Risk:** Any authorized caller of the current unauthenticated API can ask the agent to read permitted analytics columns, including message content.

**Fix:** Add identity-aware row/column policy and restrict sensitive columns when necessary.

### 9. Supply-chain and dependency risk

**Where:** pinned Python requirements and vendored Chart.js.

**Risk:** Pinned versions improve reproducibility but still require vulnerability monitoring. Vendored JavaScript requires manual update review.

**Fix:** Run dependency scanning and document update cadence.

## What is actually defended

- SQL is parsed structurally rather than filtered with regexes.
- Database writes are blocked by both the guard and the role.
- `pinned_charts` is inaccessible to `agent_ro`.
- Tool arguments use Pydantic validation.
- Query output is capped and summarized.
- Agent loops are bounded.
- Same-session history is lock-protected.
- Assistant HTML is escaped before restricted markdown rendering.

## Five improvements before the interview

1. Add executable tests for SQL guard, agent retries, plugin chaining, chart limits, and pin correlation.
2. Fix frontend server metadata escaping.
3. Fix negative pagination and provider timeout behavior.
4. Add bounded session/artifact retention and request budgets.
5. Prepare an explicit production plan for authentication, authorization, and secrets.
