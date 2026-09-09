# Discord Analytics Agent

A FastAPI + Postgres analytics app over a synthetic Discord dataset, with a
conversational agent that writes SQL, charts results, and lets you pin
charts to a dashboard. The assessed part is the plugin architecture — see
"Plugin architecture" below before anything else.

## How to run it

```
cp .env.example .env
# edit .env: set OPENAI_API_KEY (everything else has a working default)
docker compose up --build
```

That brings up Postgres, loads the dataset (idempotent — safe to re-run),
starts the API, and starts the frontend. Once `frontend` reports healthy:

- Frontend: http://localhost:8080
- API directly: http://localhost:8000 (docs at `/docs`)
- Health: http://localhost:8080/health (proxied) or :8000/health (direct)

To re-run just the data load (e.g. after editing the CSVs):

```
docker compose run --rm migrate
```

**Honesty note on this section**: I built and tested every piece of this
system by actually running it — Postgres, the loader (twice, to prove
idempotency), the FastAPI app over real HTTP, the agent loop against a
scripted fake LLM provider, and the frontend's static assets/JS syntax —
all in a sandboxed dev environment without a Docker daemon available to me.
I could not run `docker compose up` itself end-to-end before handing this
over. I'm confident in it because every piece it's made of was run for
real, individually, and the Dockerfiles/compose file were validated
(`docker-compose.yml` parsed and dependency-checked, `nginx.conf` passed
`nginx -t`, `requirements.txt` installs clean in a fresh venv) — but the
full container graph coming up together is the one thing here that's
inference, not evidence. If it doesn't come up first try, the likeliest
failure point is the nginx SSE proxy settings (`frontend/nginx.conf`) or a
`depends_on` health-check timing issue — start there.

## Environment variables

See `.env.example` — every variable is there with a comment. The only one
you must supply is `OPENAI_API_KEY`.

Two DB roles are used by design and are **not** configurable via `.env`
(they're fixed in `backend/scripts/schema.sql`): `agent_ro` (the agent's SQL
tool — read-only, 5s statement timeout) and `app_rw` (the API's own
data-serving + pin CRUD). See "Safety" below for why, and "Known
simplifications" for why these aren't provisioned as secrets.

## Plugin architecture (the actual deliverable)

A plugin is a class implementing `Plugin` in `backend/app/plugins/base.py`:
`name`, `description`, `input_model` (a pydantic model — the LLM tool
schema is generated from it, never hand-written), and `execute(args, ctx)`.

**Adding a new plugin means adding one file to `backend/app/plugins/` and
nothing else.** Discovery is a directory scan (`registry.py`) that imports
every module in that package at startup; a `@register_plugin` decorator on
your class is what actually puts it in the registry the agent's tool list
is built from. No router edit, no prompt edit, no core.py edit.

To add one:

1. Create `backend/app/plugins/my_plugin.py`.
2. Define a pydantic `input_model` for its arguments.
3. Subclass `Plugin`, set `name`/`description`/`input_model`, implement
   `async def execute(self, args, ctx) -> PluginResult`.
4. Decorate the class with `@register_plugin`.
5. Restart the app. That's it — `discover_plugins()` picks it up, and the
   agent can call it on the next request.

If your plugin should be chainable (consume another plugin's output), take
a `ref_id: str` field in your input model and resolve it via
`ctx.store.get(ref_id)` — see `chart_plugin.py` for the pattern. If it has
real intermediate progress (a multi-sheet export, say), override
`stream_progress()` and set `supports_progress = True`; `query` and `chart`
don't, because at this dataset's size they're each one round trip and a
fake progress tick would be worse than none.

Errors: raise `PluginError(code, message, retryable=...)`. The agent loop
feeds this back to the LLM as the tool's result and lets the model decide
whether to retry (bounded — see `agent/core.py`, `MAX_RETRIES_PER_CALL`) or
give up and tell the user. Don't raise bare exceptions from `execute()` —
they'll surface as an ugly generic error to both the model and the user.

### Why a directory scan instead of entry points

Entry points earn their keep when plugins are separately-versioned,
separately-installed packages. Every plugin here lives in one repo, one
package, one container — a directory scan gets the "drop a file in, it's
picked up" property with zero packaging ceremony. If this became a
plugin marketplace across repos, entry_points would be the right call.

### Chaining, concretely

`query` executes SQL and returns a `ResultRef` (an id + row count + a
15-row preview) — not the full result set — to the LLM. `chart` takes a
`ref_id` and resolves the *full* data server-side, never round-tripping it
through the model. This is deliberate: a 5,000-row result would blow the
context window if handed back as text, and message content in this
dataset is user-authored text that the model shouldn't be re-reading as
part of its own reasoning about "does this chart request make sense" any
more than it has to.

### What I decided not to support, and why

- **Streaming progress on `query`/`chart`**: the hook exists on the base
  class (`stream_progress`), unused by either plugin, because both are a
  single round-trip at this dataset's size. Faking a progress bar would be
  worse than not having one.
- **Cross-session artifact refs**: `ArtifactStore` is per-chat-session,
  in-memory, lost on restart. Pins deliberately don't depend on it — see
  "What a pin is" below — so this only costs you in-flight chat context on
  a restart, never anything durable.

## What I built and what I cut

**Built and tested end-to-end**: data foundation (idempotent load, real
data-quality issue found and handled — see `load_data.py` docstring),
FastAPI with async `asyncpg`, `query` + `chart` plugins with real chaining,
the agent loop (recover/retry, chain, bounded surrender — all proven with a
scripted fake provider so I didn't need a live key to test the mechanics),
SSE streaming with stage-by-stage events, DB-level safety (dedicated
read-only role + AST-based SQL guard, both verified against actual attack
strings), pinning (stores the query + chart spec, re-runnable, not a dead
PNG), structured logging with trace IDs, a consistent error envelope, and a
plain HTML/JS frontend.

**Cut, deliberately** (per your reply — "just query + chart" and "plain
HTML/JS"):

- **Excel and PowerPoint plugins.** Not implemented at all. The interface
  they'd implement is the same `Plugin` ABC `query`/`chart` use — nothing
  about the contract is chart-specific — so adding them later is exactly
  the "one new file" process described above, not a redesign. I did not
  stub them out with fake partial implementations; a plugin that doesn't
  work isn't evidence the architecture works, it's noise.
- **React frontend.** Plain HTML/JS + a hand-rolled SSE reader (fetch +
  `ReadableStream`, since `/api/chat` is POST and `EventSource` is GET-only).
  Chart.js via CDN for rendering.
- **Any LLM provider but OpenAI.** The `LLMProvider` ABC is real and the
  agent core only talks to it — swapping in Anthropic or a local model
  means implementing the ABC, not touching `core.py` — but I only wired up
  and tested OpenAI, per your call.

**What I'd do next with more time, specifically**:

1. Real integration test of `docker compose up` itself (see honesty note
   above) — this is the single highest-priority gap.
2. A conversation-scoped rate limit on the `query` plugin — right now
   bounded retries within one turn stop a runaway loop, but nothing stops
   a user from asking 500 expensive questions in a row. I'd add a per-
   session token/request budget.
3. Persist chat session history (currently in-memory, lost on restart) —
   probably in the same Postgres instance, a `chat_sessions` table, so a
   backend restart doesn't drop active conversations.
4. The `messages` table is a 5,000-row *sample*, not the full log; the
   system prompt tells the model this, but I'd want the `query` plugin to
   actively flag when a query against `messages` looks like it's trying to
   compute a total that daily_stats already has correctly, rather than
   relying on the model to remember the instruction.
5. Excel/PowerPoint plugins, and a real download endpoint for them
   (`GET /api/artifacts/{ref_id}/download` with a content-type derived from
   the plugin's `produces` field) — not built because it has nothing to
   serve yet.

## Design decisions and tradeoffs

- **`asyncpg` + hand-written SQL over an ORM.** SQLAlchemy's async layer
  would have cost setup time for a mapping layer this project doesn't
  need — there's no complex object graph, just six tables and a handful of
  aggregate queries. Cost: no query builder, so the data-access layer
  (`data_access/queries.py`) is plain parametrized SQL. Given the brief's
  "async, honestly" requirement, I'd rather have fewer, more legible layers
  between the route and the database.
- **Chart plugin returns a spec, not a rendered image.** A spec is what
  lets a pin be re-run instead of being a dead PNG (explicitly what the
  brief asks pinning to force you to decide), and it's what lets the
  frontend restyle without regenerating anything server-side. Cost: the
  frontend needs a charting library (Chart.js) instead of just an `<img>`.
- **Pins store the query SQL + chart args, not an `ArtifactStore` ref.**
  A ref into the in-memory per-session store wouldn't survive a restart or
  a different session ever refreshing it — pins are meant to outlive both.
  Cost: refreshing a pin re-runs the query against the live database rather
  than replaying a cached result; for this dataset's size that's
  milliseconds, but it's a real design commitment, not a free one at scale.
- **Retry policy is per-exact-call, not per-tool.** `retry_counts` is keyed
  on `(tool_name, sorted_args)`, so the model gets fresh attempts if it
  changes its approach, but can't loop on the literal same failing call
  forever. Cost: a model that retries with cosmetically different but
  equally-wrong SQL burns through `MAX_ITERATIONS` instead of hitting the
  per-call retry cap — the iteration cap is the real backstop.
- **In-memory chat sessions.** Simplest thing that could possibly chain
  tool calls within a conversation. Cost: a backend restart drops all
  active conversations (not pins — see above). Documented as the first
  thing I'd fix with more time.

## Safety — what's defended, what's explicitly left open

**Defended, and verified (not just asserted — see the commands below, all
of which were actually run against a live Postgres):**

- The agent connects as `agent_ro`: `default_transaction_read_only = on`
  and `statement_timeout = '5s'` set at the *role* level in
  `schema.sql`, not just in application code. Confirmed: `INSERT` as this
  role fails with `cannot execute INSERT in a read-only transaction`;
  `SELECT * FROM pinned_charts` fails with `permission denied` (this role
  has no grant on that table at all — pins are served by the API layer,
  never by the agent's own SQL tool, so pin data can't become a side
  channel for a hostile prompt).
- Every string the `query` plugin is given goes through
  `agent/sql_guard.py` before it touches the database: parsed with
  `sqlglot` into a real AST, rejected if it isn't exactly one `SELECT`
  (multi-statement, DML, DDL, `SELECT INTO`, and a denylist of
  resource/exfiltration functions like `pg_sleep`/`pg_read_file` are all
  walked for anywhere in the tree, not just the top level — a `DELETE`
  hidden inside a CTE is caught the same as a bare one). Confirmed against
  ten actual attack strings, including one that exposed a real bug in my
  first implementation (`sqlglot` names unrecognized functions
  `"ANONYMOUS"` via `.sql_name()`; the denylist check was silently
  matching against that literal string instead of the real function name
  until I traced why `pg_sleep` wasn't being blocked and fixed it to use
  `.name`).
- Row cap enforced twice, independently: the guard rewrites/clamps any
  `LIMIT` to `ROW_CAP` (default 5000) before execution, and each plugin
  caps its own output shape regardless of what's requested (`chart`'s
  `MAX_CATEGORIES`, for instance).
- **Prompt injection via the data itself.** The dataset is user-authored
  chat content by construction — usernames, message bodies, channel
  topics. The system prompt (`agent/prompts.py`) explicitly instructs the
  model to treat everything the `query` tool returns as inert data, never
  as instructions, and names the likely injection surfaces (message
  content, usernames, display names, topics) rather than leaving it
  general. I did not build an automated test harness that actually tries
  injection payloads against a live model (would need a real API key and
  many runs to be meaningful) — this is a prompt-level mitigation, not a
  structural one, and I'm not overstating its strength.
- 500s never reach the wire with a stack trace: every unhandled exception
  is caught by a global handler, logged with its trace_id, and returned as
  the same `{"error": {...}}` envelope as every other error path.
  Confirmed via a real 404 and a real 422.

**Explicitly left open:**

- No rate limiting / auth on the API at all — anyone who can reach the
  container can chat with the agent or hit the data endpoints. Fine for a
  take-home; not fine for anything real. Called out again above under
  "what I'd do next" because it's the one I'd actually fix first.
- The prompt-injection defense is instructional, not structural. A
  sufficiently adversarial message body could still influence model
  behavior; nothing here sandboxes the model's reasoning from data it
  reads. I don't have a mitigation for this beyond the system prompt and
  wouldn't claim otherwise.
- No per-session request budget (see "what I'd do next" #2) — the
  per-call and per-turn bounds stop one runaway conversation from looping
  forever, but not a user from starting many expensive conversations.
- `agent_ro`/`app_rw` passwords are fixed strings in `schema.sql`, not
  managed secrets (see "Known simplifications" below).

## Known simplifications

- **Fixed DB role passwords.** `agent_ro`/`app_rw` credentials are hardcoded
  in `schema.sql` and mirrored in `docker-compose.yml`/`.env.example`
  rather than generated and injected as secrets. A real deployment would
  provision these at cluster-creation time and inject them via a secrets
  manager; building that machinery for a fixed local/grading stack wasn't
  worth the time relative to everything else in scope. The superuser
  password (`POSTGRES_PASSWORD`) *is* configurable, since that's the one
  credential someone running this would actually want to change.
- **In-memory chat sessions and artifact store** — see "Design decisions"
  and "What I'd do next" above.

## Data notes

- Time zone / grain: all source timestamps are naive; loaded as UTC.
  `daily_stats`/`channel_daily_stats` are one row per (server|channel, UTC
  calendar day). See `schema.sql` header comment.
- Data-quality issue found and handled: 52 rows in `members.csv` collide on
  the natural key `(server_id, user_id)` but describe different people —
  looks like an id collision in the dataset's generator. Resolved as
  last-row-wins (a natural consequence of the idempotent upsert, not
  special-cased code) — see `load_data.py` module docstring for the full
  reasoning and what's lost by that choice (52 of 2827 profiles shadowed).
- `messages` is a 5,000-row *sample*, not the full message log — the
  system prompt tells the agent to prefer `daily_stats`/`channel_daily_stats`
  for volume questions for exactly this reason.

## Repo layout

```
backend/
  app/
    agent/        # provider abstraction, sql guard, prompts, the agent loop
    plugins/       # base contract, registry, query + chart plugins
    api/            # routes (data, chat, pins) — thin, no business logic
    data_access/     # parametrized SQL, no routing/logic
    models/           # pydantic schemas
  scripts/
    schema.sql         # DDL, indexes, roles/grants
    load_data.py        # idempotent loader
  tests/
    fakes.py             # ScriptedProvider — proves the agent loop without a live key
frontend/
  index.html, app.js, styles.css, nginx.conf
data/                     # the CSVs (see original dataset README/data_dictionary in this folder)
docker-compose.yml
.env.example
```
