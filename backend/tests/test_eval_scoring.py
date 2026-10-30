"""Scoring of the Asistan eval (evals/assistant/scoring.py) — pure functions, no DB or LLM."""
import re

from evals.assistant import scoring
from evals.assistant.run_eval import load_dataset
from evals.assistant.scoring import ToolRecord, TurnTrace, score_turn


def sql_record(columns, rows, ok=True, sql="SELECT 1 FROM chat_articles WHERE is_analyzable"):
    return ToolRecord(tool="sql", ok=ok, sql=sql, summary="" if ok else "Sorgu hatası: x",
                      artifact={"kind": "table", "columns": columns, "rows": rows} if ok else None)


def search_record(ids):
    return ToolRecord(tool="semantic_search", ok=True,
                      artifact={"kind": "table", "columns": ["id", "title"], "rows": [[i, "t"] for i in ids]})


def chart_record(values_by_series):
    return ToolRecord(tool="chart", ok=True, artifact={
        "kind": "chart", "x": [str(i) for i in range(len(values_by_series[0]))],
        "series": [{"name": f"s{i}", "values": v} for i, v in enumerate(values_by_series)]})


def trace(tools=(), report="", time_range=None, clarifications=()):
    return TurnTrace(question="q", tools=list(tools), clarifications=list(clarifications),
                     time_range=time_range, report=report)


RANGE = {"from": "2026-09-01T00:00:00+02:00", "to": "2026-09-30T23:59:59+02:00"}


def test_norm_maps_numbers_and_priority_words():
    assert scoring.norm(12.0) == "12"
    assert scoring.norm("12") == "12"
    assert scoring.norm("Yüksek") == "high"
    assert scoring.norm(" Orta ") == "med"


def test_cited_ids_and_report_numbers_keep_ids_apart():
    report = "Eylül'de 12 haber var [#403], ayrıca #357 ve oran %37,5."
    assert scoring.cited_ids(report) == [403, 357]
    numbers = scoring.report_numbers(report)
    assert {"12", "37.5"} <= numbers
    assert "403" not in numbers


def test_perfect_count_answer_passes():
    t = trace([sql_record(["count"], [[12]])], "Geçen ay 12 yüksek önemli haber vardı.", RANGE)
    expect = {"clarification": "forbidden", "time_range": "t", "tools_required": ["sql"],
              "tools_forbidden": ["semantic_search"],
              "gold": [{"name": "n", "match": "scalar", "sql": "... is_analyzable ..."}]}
    result = score_turn(t, expect, {"n": [[12]]}, RANGE)
    assert result["passed"], result
    assert result["tags"] == []


def test_wrong_tool_wrong_count_and_wrong_period_are_tagged():
    t = trace([search_record([1, 2]), sql_record(["count"], [[9]])], "9 haber var.",
              {"from": "2026-10-01T00:00:00+02:00", "to": "2026-10-30T10:00:00+01:00"},
              clarifications=[{"questions": [], "answer": "x"}])
    expect = {"clarification": "forbidden", "time_range": "t", "tools_required": ["sql"],
              "tools_forbidden": ["semantic_search"],
              "gold": [{"name": "n", "match": "scalar", "sql": "..."}]}
    result = score_turn(t, expect, {"n": [[12]]}, RANGE)
    assert not result["passed"]
    assert {"forbidden_tool:semantic_search", "unnecessary_clarification", "time_range_mismatch",
            "value_not_in_tools:n", "value_not_in_report:n"} <= set(result["tags"])


def test_zero_count_accepts_a_spelled_out_none():
    t = trace([sql_record(["count"], [[0]])], "Son 7 günde hiç yüksek önemli haber yok.")
    tool, answer = scoring.gold_scalar(t, "n", [[0]])
    assert tool.score == answer.score == 1.0


def test_scalar_accepts_a_row_count_and_can_skip_the_tool_check():
    t = trace([sql_record(["id", "title"], [[334, "a"], [305, "b"]])], "Favorilerde 2 yüksek önemli haber var.")
    tool, answer = scoring.gold_scalar(t, "n", [[2]])
    assert tool.score == answer.score == 1.0
    tool, answer = scoring.gold_scalar(trace([], "2019'da hiç haber yok."), "n", [[0]], in_tools_required=False)
    assert tool is None and answer.score == 1.0


def test_rowset_matches_translated_priorities_in_any_table():
    t = trace([sql_record(["önem", "adet"], [["Yüksek", 3], ["Orta", 5]])], "Yüksek: 3, Orta: 5.")
    tool, answer = scoring.gold_rowset(t, "p", [["high", 3], ["med", 5]])
    assert tool.score == 1.0 and answer.score == 1.0
    tool, _ = scoring.gold_rowset(t, "p", [["high", 3], ["low", 2]])
    assert tool.score == 0.5 and tool.tag == "rows_mismatch:p"


def test_top_ids_need_tool_rows_and_citations():
    t = trace([sql_record(["id", "title"], [[579, "a"], [580, "b"]])], "En önemlisi [#579].")
    tool, answer = scoring.gold_top_ids(t, "top", [[579], [580]])
    assert tool.score == 1.0
    assert answer.score == 0.5 and answer.detail["missing"] == [580]


def test_id_recall_uses_search_results_and_min_cited():
    t = trace([search_record([211, 290, 999])], "Gazze: [#211] ve [#290].")
    tool, answer = scoring.gold_id_recall(t, "rel", [[211], [290], [509]], min_cited=2)
    assert round(tool.score, 2) == 0.67 and tool.tag is None
    assert answer.score == 1.0
    _, answer = scoring.gold_id_recall(t, "rel", [[211], [290], [509]], min_cited=3)
    assert answer.tag == "relevant_not_cited:rel"


def test_chart_matches_values_regardless_of_labels_and_half_credit_for_total():
    gold = [["2026-10-20", 2], ["2026-10-21", 0], ["2026-10-22", 5]]
    tool, _ = scoring.gold_chart(trace([chart_record([[5, 0, 2]])]), "c", gold)
    assert tool.score == 1.0
    tool, _ = scoring.gold_chart(trace([chart_record([[3, 4]])]), "c", gold)
    assert tool.score == 0.5 and tool.tag == "chart_values_mismatch:c"
    tool, _ = scoring.gold_chart(trace([]), "c", gold)
    assert tool.tag == "chart_missing:c"


def test_hallucinated_ids_are_ids_no_tool_returned():
    t = trace([sql_record(["id"], [[1]])], "Bkz. [#1] ve [#777].")
    check = scoring.check_hallucinated_ids(t, existing_ids={1, 2})
    assert check.tag == "hallucinated_id" and check.detail == [777]


def test_time_tool_result_counts_when_state_has_no_range():
    record = ToolRecord(tool="time", ok=True, data=RANGE)
    assert scoring.check_time_range(trace([record]), RANGE).score == 1.0
    assert scoring.check_time_range(trace([]), RANGE).tag == "time_range_missing"


def test_sql_hygiene_flags_errors_and_missing_analyzable_rule():
    t = trace([sql_record(None, None, ok=False), sql_record(["n"], [[1]], sql="SELECT count(*) FROM chat_articles")])
    tags = {c.tag for c in scoring.check_sql_hygiene(t, ["... is_analyzable ..."])}
    assert tags == {"sql_error", "sql_missing_is_analyzable"}


def test_report_patterns():
    expect = {"report_must_match": ["2019"], "report_must_not_match": [r"[\w.]+@[\w.]+"]}
    checks = scoring.check_report_patterns("2019'da haber yok; admin@x.com", expect)
    assert [c.score for c in checks] == [1.0, 0.0]


def test_dataset_is_well_formed():
    items = load_dataset()
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids)) >= 30
    matches = {"scalar", "rowset", "top_ids", "id_recall", "must_cite", "chart"}
    for item in items:
        for turn in item["turns"]:
            expect = turn["expect"]
            assert turn["question"] and expect.get("rubric"), item["id"]
            assert expect.get("clarification", "optional") in ("required", "forbidden", "optional")
            assert not expect.get("time_range") or expect["time_range"] in (turn.get("ranges") or {}), item["id"]
            for gold in expect.get("gold") or []:
                assert gold["match"] in matches, item["id"]
                assert set(gold) <= {"name", "match", "sql", "min_cited", "in_tools"}, item["id"]
                placeholders = {p.split("_")[0] for p in re.findall(r"\{(\w+)\}", gold["sql"])}
                assert placeholders <= set(turn.get("ranges") or {}), item["id"]
