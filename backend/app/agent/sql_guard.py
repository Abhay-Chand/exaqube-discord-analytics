"""
Validates LLM-generated SQL before it ever reaches the database.

This is deliberately AST-based (sqlglot), not regex/string-matching on
keywords — the brief calls out "string-matching for DROP is not validation
and we will get past it", and it's right: `/*DROP*/SELECT`, a DROP hidden in
a string literal, or a DROP inside a CTE all defeat naive filtering. Parsing
the statement and walking the tree does not.

What this blocks:
  - more than one statement (no `SELECT 1; DROP TABLE x`)
  - anything whose top-level node is not a SELECT (INSERT/UPDATE/DELETE/
    DROP/ALTER/CREATE/TRUNCATE/GRANT/COPY/VACUUM/...)
  - any DML/DDL node ANYWHERE in the tree, including inside subqueries or
    CTEs (defends against e.g. a data-modifying CTE)
  - SELECT ... INTO (creates a table as a side effect)
  - calls to a small deny-list of functions that can exfiltrate data or
    burn resources (pg_sleep, pg_read_file, lo_*, dblink, etc.)

What this does NOT try to catch (documented, not silently ignored):
  - expensive-but-legal queries (a cross join across every table) — that's
    what the statement_timeout and row cap are for, enforced independently
    at both the DB role level and here
  - semantically wrong SQL that is syntactically fine (e.g. joining on the
    wrong column) — the agent is expected to look at the result and its own
    plausibility, not this guard
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

DEFAULT_ROW_CAP = 5_000
ABSOLUTE_ROW_CAP = 5_000  # a requested LIMIT above this is clamped, never honoured

_DISALLOWED_NODE_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Grant, exp.Copy, exp.Command, exp.Merge,
)

_DENYLISTED_FUNCTIONS = {
    "pg_sleep", "pg_read_file", "pg_read_binary_file", "pg_ls_dir",
    "lo_import", "lo_export", "dblink", "dblink_connect", "pg_terminate_backend",
    "pg_reload_conf", "pg_cancel_backend", "set_config", "current_setting",
}


class SQLGuardError(Exception):
    """Structured so the agent loop can decide whether to retry."""

    def __init__(self, code: str, message: str, retryable: bool = True):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


@dataclass
class GuardedQuery:
    sql: str
    row_cap: int


def validate_select(raw_sql: str, row_cap: int = DEFAULT_ROW_CAP) -> GuardedQuery:
    row_cap = min(row_cap, ABSOLUTE_ROW_CAP)

    try:
        statements = sqlglot.parse(raw_sql, read="postgres")
    except Exception as e:  # noqa: BLE001 - genuinely any parse error is the same to us
        raise SQLGuardError("PARSE_ERROR", f"Could not parse SQL: {e}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SQLGuardError(
            "MULTIPLE_STATEMENTS",
            f"Expected exactly one statement, got {len(statements)}. "
            "Only a single SELECT is allowed.",
        )

    tree = statements[0]

    if not isinstance(tree, exp.Select):
        raise SQLGuardError(
            "NOT_A_SELECT",
            f"Only SELECT statements are allowed; got {type(tree).__name__}.",
            retryable=False,
        )

    if tree.args.get("into") is not None:
        raise SQLGuardError(
            "SELECT_INTO_FORBIDDEN",
            "SELECT ... INTO is forbidden (it creates a table as a side effect).",
            retryable=False,
        )

    for node in tree.walk():
        n = node[0] if isinstance(node, tuple) else node
        if isinstance(n, _DISALLOWED_NODE_TYPES):
            raise SQLGuardError(
                "FORBIDDEN_STATEMENT_TYPE",
                f"Found a {type(n).__name__} node inside the query — only pure reads are allowed.",
                retryable=False,
            )
        if isinstance(n, exp.Func):
            # .sql_name() returns the literal string "ANONYMOUS" for any
            # function sqlglot doesn't recognise as a builtin (which is
            # exactly the case for pg_sleep/pg_read_file/etc — the ones we
            # actually care about denying). `.name` gives the real token.
            fname = (n.name or "").lower()
            if fname in _DENYLISTED_FUNCTIONS:
                raise SQLGuardError(
                    "DENYLISTED_FUNCTION",
                    f"Function '{fname}' is not allowed.",
                    retryable=False,
                )

    existing_limit = tree.args.get("limit")
    if existing_limit is not None:
        try:
            requested = int(existing_limit.expression.this)
        except Exception:  # noqa: BLE001
            requested = row_cap
        tree.set("limit", exp.Limit(expression=exp.Literal.number(min(requested, row_cap))))
    else:
        tree.set("limit", exp.Limit(expression=exp.Literal.number(row_cap)))

    return GuardedQuery(sql=tree.sql(dialect="postgres"), row_cap=row_cap)
