"""
Scoring of one Asistan eval turn. Pure functions over plain data (no DB, no LLM) so they can be
unit-tested: the runner (run_eval.py) collects the trace — tool calls with their results, the
final state's artifacts, clarifications, the report — and the gold query results, and passes
them here.

Every check yields a score in [0, 1] and, when it fails, a short failure tag
(`missing_tool:sql`, `count_mismatch:<gold>`, ...) the report groups by.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

# Priority values the agent may print translated (SQL CASE ... THEN 'Yüksek').
_SYNONYMS = {"yüksek": "high", "orta": "med", "düşük": "low", "medium": "med"}
_CITE = re.compile(r"\[?#(\d+)\]?")
_NUMBER = re.compile(r"(?<![\w#])\d+(?:[.,]\d+)?")
_ZERO_WORDS = re.compile(r"\bhiç\b|\byok\b|bulunm|\bsıfır\b", re.IGNORECASE)
_ID_COLUMNS = ("id", "article_id")


@dataclass
class ToolRecord:
    """One tool call the agent made and its outcome (tools.execute_tool's result)."""
    tool: str
    ok: bool
    input: Dict[str, Any] = field(default_factory=dict)
    sql: Optional[str] = None
    artifact: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None  # the time tool's resolved range
    summary: str = ""


@dataclass
class TurnTrace:
    question: str
    tools: List[ToolRecord]
    clarifications: List[Dict[str, Any]]  # the agent's clarifying questions, one entry per round
    time_range: Optional[Dict[str, str]]  # state["time_range"] of the final run
    report: str
    known_ids: Set[int] = field(default_factory=set)  # ids the earlier turns showed (follow-ups)


@dataclass
class Check:
    name: str
    score: float
    tag: Optional[str] = None
    detail: Any = None


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def norm(value: Any) -> str:
    """A comparable text form: numbers without trailing .0, text lower-cased with priority words
    mapped to their stored values."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        number = float(value)
        return str(int(number)) if number.is_integer() else f"{number:.4f}".rstrip("0")
    text = str(value).strip().lower()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return norm(float(text))
    return _SYNONYMS.get(text, text)


def cited_ids(report: str) -> List[int]:
    """Article ids the report cites as [#123] / #123, in order, unique."""
    seen: List[int] = []
    for match in _CITE.finditer(report or ""):
        article_id = int(match.group(1))
        if article_id not in seen:
            seen.append(article_id)
    return seen


def report_numbers(report: str) -> Set[str]:
    """Numbers in the report (cited ids excluded), normalised."""
    text = _CITE.sub(" ", report or "")
    return {norm(n.replace(",", ".")) for n in _NUMBER.findall(text)}


def artifact_ids(artifact: Dict[str, Any]) -> List[int]:
    """Article ids in a table artifact: its id/article_id column."""
    columns = [str(c).lower() for c in artifact.get("columns") or []]
    index = next((columns.index(c) for c in _ID_COLUMNS if c in columns), None)
    if index is None:
        return []
    ids = []
    for row in artifact.get("rows") or []:
        try:
            ids.append(int(row[index]))
        except (TypeError, ValueError, IndexError):
            continue
    return ids


def _tables(trace: TurnTrace, tool: Optional[str] = None) -> List[Dict[str, Any]]:
    return [r.artifact for r in trace.tools
            if r.ok and r.artifact and r.artifact.get("kind") == "table" and (tool is None or r.tool == tool)]


def _charts(trace: TurnTrace) -> List[Dict[str, Any]]:
    return [r.artifact for r in trace.tools if r.ok and r.artifact and r.artifact.get("kind") == "chart"]


def seen_ids(trace: TurnTrace) -> Set[int]:
    ids = set(trace.known_ids)
    for table in _tables(trace):
        ids.update(artifact_ids(table))
    return ids


# ---------------------------------------------------------------------------
# Behaviour checks
# ---------------------------------------------------------------------------

def check_tools(trace: TurnTrace, expect: Dict[str, Any]) -> Check:
    called = {r.tool for r in trace.tools}
    failures = [f"missing_tool:{t}" for t in expect.get("tools_required") or [] if t not in called]
    failures += [f"forbidden_tool:{t}" for t in expect.get("tools_forbidden") or [] if t in called]
    for group in expect.get("tools_any_of") or []:
        if not called & set(group):
            failures.append(f"missing_tool:{'|'.join(group)}")
    total = (len(expect.get("tools_required") or []) + len(expect.get("tools_forbidden") or [])
             + len(expect.get("tools_any_of") or []))
    score = 1.0 if not total else 1 - len(failures) / total
    return Check("tool_selection", score, ", ".join(failures) or None, sorted(called))


def check_clarification(trace: TurnTrace, expect: Dict[str, Any]) -> Optional[Check]:
    mode = expect.get("clarification", "optional")
    asked = len(trace.clarifications)
    if mode == "required" and not asked:
        return Check("clarification", 0.0, "missed_clarification", asked)
    if mode == "forbidden" and asked:
        return Check("clarification", 0.0, "unnecessary_clarification", trace.clarifications)
    if mode == "optional":
        return None
    return Check("clarification", 1.0, None, asked)


def check_time_range(trace: TurnTrace, expected: Optional[Dict[str, str]]) -> Optional[Check]:
    """The period the agent worked with (resolved in `understand`, or by the time tool) must match
    the expected range by day."""
    if not expected:
        return None
    want = (expected["from"][:10], expected["to"][:10])
    got = []
    if trace.time_range:
        got.append((trace.time_range["from"][:10], trace.time_range["to"][:10]))
    for record in trace.tools:
        if record.tool == "time" and record.ok and record.data:
            got.append((record.data["from"][:10], record.data["to"][:10]))
    if want in got:
        return Check("time_range", 1.0, None, got)
    return Check("time_range", 0.0, "time_range_mismatch" if got else "time_range_missing",
                 {"expected": want, "got": got})


def check_sql_hygiene(trace: TurnTrace, gold_sqls: Sequence[str]) -> List[Check]:
    """Warnings, not scored: failed/rejected queries and the data-model rules from the prompt."""
    checks = []
    sql_calls = [r for r in trace.tools if r.tool == "sql"]
    failed = [r for r in sql_calls if not r.ok]
    if failed:
        tag = "sql_rejected" if any("reddedildi" in r.summary for r in failed) else "sql_error"
        checks.append(Check("sql_errors", 1 - len(failed) / len(sql_calls), tag, [r.summary for r in failed]))
    wants_analyzable = any("is_analyzable" in sql for sql in gold_sqls)
    ok_sqls = [(r.sql or "").lower() for r in sql_calls if r.ok]
    if wants_analyzable and ok_sqls and not any("is_analyzable" in sql for sql in ok_sqls):
        checks.append(Check("sql_rules", 0.0, "sql_missing_is_analyzable", None))
    if any("published_at" in sql and "article_date" not in sql for sql in ok_sqls):
        checks.append(Check("sql_rules", 0.0, "sql_not_article_date", None))
    return checks


def check_report_patterns(report: str, expect: Dict[str, Any]) -> List[Check]:
    checks = []
    for pattern in expect.get("report_must_match") or []:
        hit = re.search(pattern, report or "", re.IGNORECASE) is not None
        checks.append(Check("report_pattern", 1.0 if hit else 0.0, None if hit else f"report_missing:{pattern}"))
    for pattern in expect.get("report_must_not_match") or []:
        hit = re.search(pattern, report or "", re.IGNORECASE) is not None
        checks.append(Check("report_pattern", 0.0 if hit else 1.0, f"report_forbidden:{pattern}" if hit else None))
    return checks


def check_hallucinated_ids(trace: TurnTrace, existing_ids: Optional[Set[int]] = None) -> Optional[Check]:
    """Cited ids no tool returned in this run (nor an earlier turn), or that don't exist at all."""
    cited = cited_ids(trace.report)
    if not cited:
        return None
    seen = seen_ids(trace)
    unknown = [i for i in cited if i not in seen or (existing_ids is not None and i not in existing_ids)]
    if unknown:
        return Check("cited_ids", 1 - len(unknown) / len(cited), "hallucinated_id", unknown)
    return Check("cited_ids", 1.0, None, cited)


# ---------------------------------------------------------------------------
# Gold checks — each returns (tool_results check, answer check)
# ---------------------------------------------------------------------------

def _cells(rows: Iterable[Sequence[Any]]) -> Set[str]:
    return {norm(v) for row in rows for v in row if v is not None}


def gold_scalar(trace: TurnTrace, name: str, gold_rows: List[List[Any]], in_tools_required: bool = True):
    """The value must be a cell of an SQL result, or the row count of one (a count answered by
    listing the rows); `in_tools_required: false` for answers that need no query (an empty period
    is known from the coverage check before planning)."""
    value = norm(gold_rows[0][0]) if gold_rows and gold_rows[0] else "0"
    tables = _tables(trace, "sql")
    in_tools = any(value in _cells(t.get("rows") or []) or value == norm(len(t.get("rows") or []))
                   for t in tables)
    in_report = value in report_numbers(trace.report) or (value == "0" and bool(_ZERO_WORDS.search(trace.report)))
    tool_check = (Check(f"{name}:tool", float(in_tools), None if in_tools else f"value_not_in_tools:{name}", value)
                  if in_tools_required else None)
    return (tool_check,
            Check(f"{name}:answer", float(in_report), None if in_report else f"value_not_in_report:{name}", value))


def _row_matched(gold_row: Sequence[Any], tables: List[Dict[str, Any]]) -> bool:
    want = {norm(v) for v in gold_row if v is not None}
    return any(want <= {norm(v) for v in row if v is not None}
               for table in tables for row in table.get("rows") or [])


def gold_rowset(trace: TurnTrace, name: str, gold_rows: List[List[Any]]):
    if not gold_rows:
        return (Check(f"{name}:tool", 1.0), Check(f"{name}:answer", 1.0))
    tables = _tables(trace, "sql")
    matched = sum(_row_matched(row, tables) for row in gold_rows) / len(gold_rows)
    numbers = report_numbers(trace.report)
    values = [norm(v) for row in gold_rows for v in row if isinstance(v, (int, float)) and not isinstance(v, bool)]
    in_report = sum(v in numbers for v in values) / len(values) if values else 1.0
    return (Check(f"{name}:tool", matched, None if matched == 1 else f"rows_mismatch:{name}", gold_rows),
            Check(f"{name}:answer", in_report, None if in_report == 1 else f"numbers_not_in_report:{name}", values))


def gold_top_ids(trace: TurnTrace, name: str, gold_rows: List[List[Any]]):
    gold = [int(row[0]) for row in gold_rows]
    if not gold:
        return (Check(f"{name}:tool", 1.0), Check(f"{name}:answer", 1.0))
    found = seen_ids(trace)
    in_tools = sum(i in found for i in gold) / len(gold)
    cited = set(cited_ids(trace.report))
    in_report = sum(i in cited for i in gold) / len(gold)
    return (Check(f"{name}:tool", in_tools, None if in_tools == 1 else f"ids_not_in_tools:{name}",
                  {"gold": gold, "missing": [i for i in gold if i not in found]}),
            Check(f"{name}:answer", in_report, None if in_report == 1 else f"ids_not_cited:{name}",
                  {"gold": gold, "missing": [i for i in gold if i not in cited]}))


def gold_id_recall(trace: TurnTrace, name: str, gold_rows: List[List[Any]], min_cited: int = 1):
    gold = {int(row[0]) for row in gold_rows}
    found: Set[int] = set()
    for table in _tables(trace, "semantic_search"):
        found.update(artifact_ids(table))
    if not found:  # an SQL-only route (e.g. by topic) may still find them
        found = seen_ids(trace)
    recall = len(gold & found) / len(gold) if gold else 1.0
    cited = set(cited_ids(trace.report))
    enough = len(gold & cited) >= min(min_cited, len(gold))
    return (Check(f"{name}:tool", recall, None if recall >= 0.66 else f"low_recall:{name}",
                  {"gold": sorted(gold), "found": sorted(gold & found)}),
            Check(f"{name}:answer", float(enough), None if enough else f"relevant_not_cited:{name}",
                  {"cited_relevant": sorted(gold & cited), "min": min_cited}))


def gold_must_cite(trace: TurnTrace, name: str, gold_rows: List[List[Any]]):
    gold = [int(row[0]) for row in gold_rows]
    cited = set(cited_ids(trace.report))
    ok = all(i in cited for i in gold)
    return (None, Check(f"{name}:answer", float(ok), None if ok else f"ids_not_cited:{name}", gold))


def _values(numbers: Iterable[Any]) -> List[str]:
    return sorted(norm(v) for v in numbers if v not in (None, 0, 0.0))


def gold_chart(trace: TurnTrace, name: str, gold_rows: List[List[Any]]):
    """A chart matches when its non-zero values are the gold's (labels are free-form: dates may
    be printed in any format); the same total counts half."""
    want = _values(row[-1] for row in gold_rows)
    total = sum(float(row[-1] or 0) for row in gold_rows)
    charts = _charts(trace)
    best = 0.0
    for chart in charts:
        values = [v for series in chart.get("series") or [] for v in series.get("values") or []]
        if _values(values) == want:
            best = 1.0
        elif abs(sum(float(v or 0) for v in values) - total) < 1e-6:
            best = max(best, 0.5)
    tag = None if best == 1 else (f"chart_missing:{name}" if not charts else f"chart_values_mismatch:{name}")
    numbers = report_numbers(trace.report)
    in_report = norm(total) in numbers or any(v in numbers for v in want)
    return (Check(f"{name}:tool", best, tag, {"gold": gold_rows, "charts": len(charts)}),
            Check(f"{name}:answer", float(in_report), None if in_report else f"numbers_not_in_report:{name}", want))


def score_gold(trace: TurnTrace, gold: Dict[str, Any], gold_rows: List[List[Any]]):
    match = gold["match"]
    name = gold["name"]
    if match == "scalar":
        return gold_scalar(trace, name, gold_rows, gold.get("in_tools", True))
    if match == "rowset":
        return gold_rowset(trace, name, gold_rows)
    if match == "top_ids":
        return gold_top_ids(trace, name, gold_rows)
    if match == "id_recall":
        return gold_id_recall(trace, name, gold_rows, gold.get("min_cited", 1))
    if match == "must_cite":
        return gold_must_cite(trace, name, gold_rows)
    if match == "chart":
        return gold_chart(trace, name, gold_rows)
    raise ValueError(f"unknown match type: {match}")


# ---------------------------------------------------------------------------
# One turn
# ---------------------------------------------------------------------------

DIMENSIONS = ("tool_selection", "time_range", "tool_results", "answer_facts", "judge")


def _mean(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 3) if values else None


def score_turn(trace: TurnTrace, expect: Dict[str, Any], gold_results: Dict[str, List[List[Any]]],
               expected_range: Optional[Dict[str, str]], existing_ids: Optional[Set[int]] = None,
               judge: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """All checks of one turn → {dimensions: {name: 0..1|None}, checks: [...], tags: [...], passed}."""
    behaviour = [check_tools(trace, expect)]
    clarification = check_clarification(trace, expect)
    if clarification:
        behaviour.append(clarification)
    time_check = check_time_range(trace, expected_range) if expect.get("time_range") else None
    tool_checks: List[Check] = []
    answer_checks: List[Check] = []
    for gold in expect.get("gold") or []:
        tool_check, answer_check = score_gold(trace, gold, gold_results.get(gold["name"], []))
        if tool_check:
            tool_checks.append(tool_check)
        answer_checks.append(answer_check)
    answer_checks += check_report_patterns(trace.report, expect)
    hallucination = check_hallucinated_ids(trace, existing_ids)
    if hallucination:
        answer_checks.append(hallucination)
    warnings = check_sql_hygiene(trace, [g["sql"] for g in expect.get("gold") or []])

    dimensions = {
        "tool_selection": _mean([c.score for c in behaviour]),
        "time_range": time_check.score if time_check else None,
        "tool_results": _mean([c.score for c in tool_checks]),
        "answer_facts": _mean([c.score for c in answer_checks]),
        "judge": round(judge["score"] / 5, 3) if judge and isinstance(judge.get("score"), (int, float)) else None,
    }
    checks = behaviour + ([time_check] if time_check else []) + tool_checks + answer_checks + warnings
    tags = [c.tag for c in checks if c.tag]
    if not trace.report.strip():
        tags.append("no_report")
    scored = [v for v in dimensions.values() if v is not None]
    passed = bool(trace.report.strip()) and all(v >= (0.6 if k == "judge" else 1.0)
                                                for k, v in dimensions.items() if v is not None)
    return {
        "dimensions": dimensions,
        "overall": _mean(scored),
        "passed": passed,
        "tags": tags,
        "checks": [{"name": c.name, "score": round(c.score, 3), "tag": c.tag, "detail": c.detail} for c in checks],
    }
