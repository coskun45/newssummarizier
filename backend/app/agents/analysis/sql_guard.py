"""
Static check of the SQL the Asistan writes, before it reaches the database: exactly one read-only
query, reading only the chat_* views, calling only allow-listed functions, with a row limit.

This is the first of two guards — on PostgreSQL the query also runs in a READ ONLY transaction as a
role that can read the views only (crud.run_readonly_query). The function allow-list matters for
that second guard: `set_config('role', ...)` or `pg_read_file(...)` are SELECT-able, so a query is
refused unless every function it calls is a known harmless one.
"""
from typing import Optional

import sqlglot
from sqlglot import exp

from app.db.database import CHAT_VIEWS


class SqlRejected(ValueError):
    """The query is not allowed; the message (Turkish) is shown to the model so it can fix it."""


ALLOWED_RELATIONS = frozenset(CHAT_VIEWS)

# Functions sqlglot parses into its own expression types are harmless (aggregates, date, string,
# math, window functions). Anything it doesn't know becomes exp.Anonymous — those must be listed.
ALLOWED_ANONYMOUS_FUNCTIONS = frozenset({
    "date_part", "to_char", "to_date", "to_timestamp", "age", "justify_days", "make_date",
    "make_interval", "date_bin", "now", "current_date", "localtimestamp", "timezone",
    "initcap", "btrim", "ltrim", "rtrim", "split_part", "strpos", "replace", "translate",
    "regexp_replace", "regexp_matches", "unaccent", "left", "right", "concat_ws", "format",
    "width_bucket", "trunc", "sign", "div", "mod", "power", "sqrt", "ln", "log", "exp",
    "ceiling", "floor", "random", "greatest", "least", "nullif", "row_number", "rank",
    "dense_rank", "ntile", "lag", "lead", "first_value", "last_value", "percent_rank",
    "cume_dist", "string_agg", "array_agg", "bool_and", "bool_or", "every", "mode",
    "percentile_disc", "percentile_cont", "corr", "regr_slope", "regr_intercept",
    "covar_pop", "covar_samp", "var_pop", "var_samp", "stddev_pop", "stddev_samp",
    "array_length", "cardinality", "unnest", "generate_series",
})

# Never executable inside the query, wherever they appear (also inside a CTE).
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.Command, exp.Into, exp.Lock, exp.Set, exp.Transaction, exp.Commit, exp.Rollback,
)


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def validate_sql(sql: str, max_rows: int, dialect: str = "postgres") -> str:
    """Return the query to run (in `dialect`, with LIMIT ≤ max_rows + 1) or raise SqlRejected."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise SqlRejected("Boş sorgu.")
    try:
        statements = [s for s in sqlglot.parse(text, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise SqlRejected(f"SQL ayrıştırılamadı: {str(e).splitlines()[0]}") from e
    if len(statements) != 1:
        raise SqlRejected("Tek bir sorgu gönderilmeli (noktalı virgülle birden çok ifade yok).")
    root = statements[0]
    if not isinstance(root, exp.Query):
        raise SqlRejected("Yalnızca SELECT sorgusu çalıştırılabilir.")

    for node in root.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlRejected("Yalnızca okuma yapılabilir; veri/şema değiştiren ifade içeremez.")

    for table in root.find_all(exp.Table):
        name = table.name.lower()
        if table.args.get("db") or table.args.get("catalog"):
            raise SqlRejected(f"Şema/katalog belirtilemez: {table.sql()}")
        if name not in ALLOWED_RELATIONS and not _names_visible_cte(table):
            allowed = ", ".join(sorted(ALLOWED_RELATIONS))
            raise SqlRejected(f"'{name}' okunamaz. Yalnızca şu view'lar kullanılabilir: {allowed}.")

    for func in root.find_all(exp.Func):
        if isinstance(func, exp.Anonymous) and _function_name(func) not in ALLOWED_ANONYMOUS_FUNCTIONS:
            raise SqlRejected(f"'{_function_name(func)}' fonksiyonu kullanılamaz.")

    root = _limited(root, max_rows)
    return root.sql(dialect=dialect)


def _names_visible_cte(table: exp.Table) -> bool:
    """Whether `table` refers to a CTE in scope rather than to a real relation. A query body sees
    all CTEs of its WITH; a CTE's own body sees only the CTEs defined before it (itself too under
    RECURSIVE) — so `WITH users AS (SELECT * FROM users)` reads the real `users` table inside."""
    name = table.name.lower()
    child, node = table, table.parent
    while node is not None:
        if isinstance(node, exp.With) and isinstance(child, exp.CTE):
            ctes = list(node.expressions)
            index = ctes.index(child)
            visible = ctes[:index + 1] if node.args.get("recursive") else ctes[:index]
            if name in {cte.alias_or_name.lower() for cte in visible}:
                return True
        elif isinstance(node, exp.Query) and child is not node.args.get("with"):
            with_ = node.args.get("with")
            if with_ is not None and name in {cte.alias_or_name.lower() for cte in with_.expressions}:
                return True
        child, node = node, node.parent
    return False


def _limited(root: exp.Query, max_rows: int) -> exp.Query:
    limit = root.args.get("limit")
    current: Optional[int] = None
    if limit is not None:
        value = limit.expression
        if isinstance(value, exp.Literal) and value.is_int:
            current = int(value.name)
    if current is not None and current <= max_rows:
        return root
    # One row over the cap: crud.run_readonly_query keeps max_rows and reports the cut.
    return root.limit(max_rows + 1)
