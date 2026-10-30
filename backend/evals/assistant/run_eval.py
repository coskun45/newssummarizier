"""
Asks the Asistan the questions of dataset.yaml against the configured database (repo-root .env),
records what it did (clarifications, tool calls + results, final state, report), computes the gold
answers with the dataset's reference queries, scores every turn (scoring.py) and optionally lets an
LLM judge the report. Writes results/run-<ts>.json (full traces) and results/run-<ts>.md (summary).

    cd backend
    python -m evals.assistant.run_eval                       # whole dataset
    python -m evals.assistant.run_eval --ids cnt-01,sem-01   # some questions
    python -m evals.assistant.run_eval --category semantik --no-judge
    python -m evals.assistant.run_eval --gold-only           # only print the gold answers

Costs real OpenAI money (the agent + the judge) and books it in llm_usage like the app does.
"""
import argparse
import asyncio
import contextvars
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.agents.analysis import nodes
from app.agents.analysis import tools as chat_tools
from app.agents.analysis.graph import build_analysis_graph
from app.agents.analysis.time_range import resolve_time_range
from app.core.config import settings
from app.db import crud
from app.db.database import SessionLocal, init_db
from app.services import chat_service, summary_service
from evals.assistant.scoring import DIMENSIONS, ToolRecord, TurnTrace, artifact_ids, cited_ids, score_turn

HERE = Path(__file__).parent
DATASET = HERE / "dataset.yaml"
RESULTS = HERE / "results"
MAX_CLARIFY_ANSWERS = 3

# The tool calls of the run in progress: execute_tool is wrapped once, and each run (an asyncio
# task with its own context) collects into its own list.
_records: contextvars.ContextVar[Optional[List[ToolRecord]]] = contextvars.ContextVar("eval_records", default=None)
_original_execute_tool = nodes.execute_tool


async def _recording_execute_tool(*args, **kwargs):
    result = await _original_execute_tool(*args, **kwargs)
    records = _records.get()
    if records is not None:
        records.append(ToolRecord(tool=result["tool"], ok=result["ok"], input=result.get("input") or {},
                                  sql=result.get("sql"), artifact=result.get("artifact"), data=result.get("data"),
                                  summary=result.get("summary", "")))
    return result


nodes.execute_tool = _recording_execute_tool


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def load_dataset(path: Path = DATASET) -> List[Dict[str, Any]]:
    items = yaml.safe_load(path.read_text(encoding="utf-8"))
    for item in items:
        if "turns" not in item:
            item["turns"] = [{key: item[key] for key in ("question", "ranges", "clarification_answers", "expect")
                              if key in item}]
    return items


def resolve_ranges(ranges: Optional[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """{name: resolved range + from_utc/to_utc}, via the same resolver the agent uses."""
    resolved = {}
    for name, expression in (ranges or {}).items():
        found = resolve_time_range(expression)
        if found is None:
            raise ValueError(f"dataset range '{expression}' does not resolve")
        resolved[name] = {**found, "from_utc": chat_tools._utc_text(found["from"]),
                          "to_utc": chat_tools._utc_text(found["to"])}
    return resolved


def gold_answers(expect: Dict[str, Any], ranges: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    params = {}
    for name, found in ranges.items():
        params[f"{name}_from"], params[f"{name}_to"] = found["from_utc"], found["to_utc"]
    answers = {}
    db = SessionLocal()
    try:
        for gold in expect.get("gold") or []:
            sql = gold["sql"].format(**params)
            result = crud.run_readonly_query(db, sql, 10_000, 1000)
            answers[gold["name"]] = {"sql": sql, "columns": result["columns"],
                                     "rows": [[chat_tools._json_value(v) for v in row] for row in result["rows"]]}
    finally:
        db.close()
    return answers


def existing_article_ids() -> set:
    db = SessionLocal()
    try:
        result = crud.run_readonly_query(db, "SELECT id FROM chat_articles", 10_000, 100_000)
        return {row[0] for row in result["rows"]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Running the agent
# ---------------------------------------------------------------------------

async def _run_graph(state: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    async def emit(event: Dict[str, Any]) -> None:
        if event["type"] != "token":
            events.append(event)

    final = state
    async for value in build_analysis_graph().astream(
        state, config={"configurable": {"emit": emit}, "recursion_limit": 4 * settings.chat_max_steps + 20},
        stream_mode="values",
    ):
        final = value
    return final


async def run_turn(question: str, history: List[Dict[str, str]], answers: List[str],
                   timeout: float) -> Dict[str, Any]:
    """One user turn, answering clarifying questions from `answers` like the user would."""
    records: List[ToolRecord] = []
    _records.set(records)
    events: List[Dict[str, Any]] = []
    clarifications: List[Dict[str, Any]] = []
    db = SessionLocal()
    try:
        state = {**chat_service._new_run_state(db, question, history), "require_plan_approval": False}
    finally:
        db.close()
    started = time.monotonic()
    error = None
    final: Dict[str, Any] = state
    remaining = list(answers)
    try:
        while True:
            final = await asyncio.wait_for(_run_graph(state, events), timeout)
            pending = final.get("pending") or {}
            if pending.get("kind") != "clarification":
                break
            # No scripted answer (the question wasn't expected): pick the first option like a
            # hurried user would, so the rest of the turn can still be scored.
            questions = pending.get("questions") or []
            options = (questions[0].get("options") or []) if questions else []
            answer = remaining.pop(0) if remaining else (options[0] if options else None)
            clarifications.append({"questions": questions, "answer": answer})
            if answer is None or len(clarifications) > MAX_CLARIFY_ANSWERS:
                break
            records.clear()  # a resumed run starts a fresh plan; only its tool calls count
            db = SessionLocal()
            try:
                state = chat_service.build_turn_state(db, final, "awaiting_clarification", answer, "send")
            finally:
                db.close()
    except Exception as e:  # noqa: BLE001 — a crash is a result to report, not a reason to stop the eval
        error = f"{type(e).__name__}: {e}"
    outcome = chat_service._outcome(final)
    idle = outcome["status"] == "idle"
    return {
        "records": records,
        "events": events,
        "clarifications": clarifications,
        "final": final,
        "report": (final.get("report") or "") if idle else "",
        "history": outcome["state"].get("history", history) if idle else history,
        "cost": round(final.get("cost") or 0.0, 6),
        "seconds": round(time.monotonic() - started, 1),
        "error": error,
    }


JUDGE_PROMPT = """Sen bir haber analizi asistanının cevaplarını değerlendiren titiz bir hakemsin.
Verilenler: kullanıcının sorusu, beklenen analiz (rubrik), veritabanından hesaplanmış DOĞRU sonuçlar (altın),
asistanın kullandığı araçların özeti ve asistanın nihai raporu.

Puanla (0-5):
5 = soruyu tam ve doğru cevaplıyor, sayılar altınla uyumlu, rubrikteki tüm noktalar var
4 = doğru, küçük eksik/fazlalık
3 = kısmen doğru; önemli bir eksik veya küçük bir yanlış
2 = belirgin yanlış sayı/haber veya sorunun önemli kısmı cevapsız
1 = büyük ölçüde yanlış veya uydurma
0 = cevap yok / tamamen alakasız

Altın sonuçlar ham veritabanı değerleridir (priority: high=Yüksek, med=Orta, low=Düşük).
Yalnızca şu JSON'u döndür:
{"score": 0, "errors": ["kısa Türkçe hata", "..."], "comment": "tek cümle"}"""


async def judge_turn(question: str, rubric: str, gold: Dict[str, Any], records: List[ToolRecord],
                     report: str) -> Dict[str, Any]:
    tool_summary = [{"tool": r.tool, "ok": r.ok, "summary": r.summary, "sql": r.sql} for r in records]
    payload = {"soru": question, "rubrik": rubric,
               "altın": {name: {"columns": g["columns"], "rows": g["rows"][:30]} for name, g in gold.items()},
               "araçlar": tool_summary, "rapor": report or "(rapor yok)"}
    try:
        response = await summary_service.run_agent_llm(
            [{"role": "system", "content": JUDGE_PROMPT},
             {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
            settings.chat_model, 800, purpose="eval_judge", json_mode=True, temperature=0.0,
        )
        verdict = json.loads(response["content"])
        verdict["cost"] = response["cost"]
        return verdict
    except Exception as e:  # noqa: BLE001
        return {"score": None, "errors": [f"hakem çalışmadı: {e}"], "comment": ""}


async def run_item(item: Dict[str, Any], use_judge: bool, timeout: float, existing: set) -> Dict[str, Any]:
    history: List[Dict[str, str]] = []
    known_ids: set = set()
    turns = []
    for turn in item["turns"]:
        expect = turn.get("expect") or {}
        ranges = resolve_ranges(turn.get("ranges"))
        gold = gold_answers(expect, ranges)
        run = await run_turn(turn["question"], history, list(turn.get("clarification_answers") or []), timeout)
        trace = TurnTrace(question=turn["question"], tools=run["records"], clarifications=run["clarifications"],
                          time_range=run["final"].get("time_range"), report=run["report"], known_ids=set(known_ids))
        judge = None
        if use_judge and expect.get("rubric"):
            judge = await judge_turn(turn["question"], expect["rubric"], gold, run["records"], run["report"])
        expected_range = ranges.get(expect["time_range"]) if expect.get("time_range") else None
        score = score_turn(trace, expect, {name: g["rows"] for name, g in gold.items()}, expected_range,
                           existing, judge)
        if run["error"]:
            score["tags"].append("run_error")
            score["passed"] = False
        known_ids |= {i for r in run["records"] if r.artifact and r.artifact.get("kind") == "table"
                      for i in artifact_ids(r.artifact)} | set(cited_ids(run["report"]))
        history = run["history"]
        turns.append({
            "question": turn["question"],
            "expected_range": expected_range,
            "gold": gold,
            "clarifications": run["clarifications"],
            "time_range": run["final"].get("time_range"),
            "intent": run["final"].get("intent"),
            "plan": run["final"].get("plan"),
            "limitations": run["final"].get("limitations"),
            "tools": [{"tool": r.tool, "ok": r.ok, "input": r.input, "summary": r.summary, "sql": r.sql,
                       "artifact": r.artifact} for r in run["records"]],
            "events": run["events"],
            "report": run["report"],
            "judge": judge,
            "score": score,
            "cost": run["cost"],
            "seconds": run["seconds"],
            "error": run["error"],
        })
    return {"id": item["id"], "category": item["category"], "turns": turns,
            "passed": all(t["score"]["passed"] for t in turns)}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


def _avg(values: List[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _quote(text: str, limit: int = 700) -> str:
    text = (text or "").strip()
    text = text if len(text) <= limit else text[:limit] + " …"
    return "\n".join("> " + line for line in text.splitlines()) or "> (rapor yok)"


def markdown_report(results: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
    turns = [(r, t) for r in results for t in r["turns"]]
    lines = [f"# Asistan değerlendirme — {meta['started']}", "",
             f"Model: `{meta['model']}` / hızlı: `{meta['fast_model']}` · Araçlar: {', '.join(meta['tools'])} · "
             f"Soru: {len(results)} · Geçen: {sum(r['passed'] for r in results)} · "
             f"Maliyet: ${meta['cost']:.3f} (+ hakem ${meta['judge_cost']:.3f}) · Süre: {meta['seconds']} sn", ""]

    lines += ["## Kategori × boyut", "", "| Kategori | Soru | Geçen | " + " | ".join(DIMENSIONS) + " |",
              "|---|---|---|" + "---|" * len(DIMENSIONS)]
    categories = sorted({r["category"] for r in results})
    for category in categories + ["TOPLAM"]:
        group = [(r, t) for r, t in turns if category in ("TOPLAM", r["category"])]
        items = {r["id"]: r for r, _ in group}
        cells = [_pct(_avg([t["score"]["dimensions"][d] for _, t in group])) for d in DIMENSIONS]
        lines.append(f"| {category} | {len(items)} | {sum(r['passed'] for r in items.values())} | "
                     + " | ".join(cells) + " |")

    tag_counts = Counter(re.sub(r":.*", "", tag) for _, t in turns for tag in t["score"]["tags"])
    lines += ["", "## En sık hata etiketleri", "", "| Etiket | Adet | Sorular |", "|---|---|---|"]
    for tag, count in tag_counts.most_common():
        ids = sorted({r["id"] for r, t in turns if any(re.sub(r":.*", "", x) == tag for x in t["score"]["tags"])})
        lines.append(f"| `{tag}` | {count} | {', '.join(ids)} |")

    lines += ["", "## Başarısız sorular", ""]
    for result in results:
        if result["passed"]:
            continue
        for number, turn in enumerate(result["turns"], 1):
            if turn["score"]["passed"]:
                continue
            title = f"### {result['id']}" + (f" (tur {number})" if len(result["turns"]) > 1 else "")
            dims = ", ".join(f"{k} {_pct(v)}" for k, v in turn["score"]["dimensions"].items() if v is not None)
            lines += [title, f"**Soru:** {turn['question']}", f"**Puanlar:** {dims}",
                      f"**Etiketler:** {', '.join(f'`{t}`' for t in turn['score']['tags']) or '—'}"]
            if turn["error"]:
                lines.append(f"**Hata:** {turn['error']}")
            if turn["clarifications"]:
                asked = "; ".join(" / ".join(q.get("question", "") for q in c["questions"] or [])
                                  + f" → {c['answer']!r}" for c in turn["clarifications"])
                lines.append(f"**Netleştirme:** {asked}")
            if turn["expected_range"] or turn["time_range"]:
                exp = turn["expected_range"] or {}
                got = turn["time_range"] or {}
                lines.append(f"**Dönem:** beklenen {exp.get('from', '')[:10]} → {exp.get('to', '')[:10]} · "
                             f"ajan {got.get('from', '')[:10]} → {got.get('to', '')[:10]}")
            lines.append("**Araçlar:** " + (" → ".join(f"{t['tool']}{'' if t['ok'] else '✗'}" for t in turn["tools"])
                                           or "—"))
            for tool in turn["tools"]:
                if tool["sql"]:
                    lines += [f"- ajan SQL ({tool['summary']}):", "  ```sql", "  " + tool["sql"].strip()[:600], "  ```"]
                elif tool["tool"] == "semantic_search":
                    lines.append(f"- arama `{tool['input'].get('query')}` → {tool['summary']}")
            for name, gold in turn["gold"].items():
                rows = gold["rows"][:12]
                lines.append(f"- altın `{name}`: {json.dumps(rows, ensure_ascii=False)}"
                             + (" …" if len(gold["rows"]) > 12 else ""))
            failed = [c for c in turn["score"]["checks"] if c["tag"]]
            for check in failed:
                lines.append(f"- ✗ `{check['tag']}`: {json.dumps(check['detail'], ensure_ascii=False, default=str)[:300]}")
            if turn["judge"]:
                lines.append(f"- hakem {turn['judge'].get('score')}/5: {turn['judge'].get('comment', '')} "
                             f"{'; '.join(turn['judge'].get('errors') or [])}")
            lines += ["", "**Rapor:**", _quote(turn["report"]), ""]

    lines += ["## Tüm sorular", "", "| Soru | Geçti | Genel | Araçlar | Maliyet | Süre |", "|---|---|---|---|---|---|"]
    for result in results:
        for turn in result["turns"]:
            lines.append(f"| {result['id']} | {'✓' if turn['score']['passed'] else '✗'} | "
                         f"{_pct(turn['score']['overall'])} | {' → '.join(t['tool'] for t in turn['tools']) or '—'} | "
                         f"${turn['cost']:.3f} | {turn['seconds']} sn |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def select(items: List[Dict[str, Any]], ids: Optional[str], category: Optional[str]) -> List[Dict[str, Any]]:
    if ids:
        wanted = {i.strip() for i in ids.split(",")}
        unknown = wanted - {item["id"] for item in items}
        if unknown:
            sys.exit(f"Bilinmeyen soru: {', '.join(sorted(unknown))}")
        items = [item for item in items if item["id"] in wanted]
    if category:
        items = [item for item in items if item["category"] == category]
    return items


async def main_async(args) -> None:
    init_db()
    items = select(load_dataset(), args.ids, args.category)
    if args.gold_only:
        for item in items:
            for turn in item["turns"]:
                gold = gold_answers(turn.get("expect") or {}, resolve_ranges(turn.get("ranges")))
                print(f"{item['id']}: {turn['question']}")
                for name, g in gold.items():
                    print(f"   {name}: {json.dumps(g['rows'][:15], ensure_ascii=False)}")
        return

    db = SessionLocal()
    try:
        enabled = chat_tools.get_enabled_chat_tools(db)
    finally:
        db.close()
    existing = existing_article_ids()
    started = datetime.now()
    semaphore = asyncio.Semaphore(args.concurrency)

    async def one(item):
        async with semaphore:
            print(f"… {item['id']}", flush=True)
            result = await run_item(item, not args.no_judge, args.timeout, existing)
            mark = "✓" if result["passed"] else "✗ " + ", ".join(t for turn in result["turns"]
                                                               for t in turn["score"]["tags"])
            print(f"{item['id']}: {mark}", flush=True)
            return result

    results = await asyncio.gather(*(one(item) for item in items))
    meta = {
        "started": started.strftime("%Y-%m-%d %H:%M"),
        "model": settings.chat_model, "fast_model": settings.chat_fast_model, "tools": enabled,
        "cost": sum(t["cost"] for r in results for t in r["turns"]),
        "judge_cost": sum((t["judge"] or {}).get("cost") or 0 for r in results for t in r["turns"]),
        "seconds": round((datetime.now() - started).total_seconds()),
    }
    RESULTS.mkdir(exist_ok=True)
    stem = RESULTS / f"run-{started.strftime('%Y%m%d-%H%M%S')}"
    stem.with_suffix(".json").write_text(
        json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    stem.with_suffix(".md").write_text(markdown_report(results, meta), encoding="utf-8")
    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} geçti · ${meta['cost']:.3f} · {stem}.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="Asistan değerlendirmesi")
    parser.add_argument("--ids", help="virgülle ayrılmış soru kimlikleri")
    parser.add_argument("--category")
    parser.add_argument("--no-judge", action="store_true", help="LLM hakemi çalıştırma")
    parser.add_argument("--gold-only", action="store_true", help="yalnızca altın cevapları yazdır")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=300, help="soru başına saniye")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
