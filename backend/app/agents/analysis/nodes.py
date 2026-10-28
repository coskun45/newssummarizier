"""
Nodes of the Asistan's analysis graph: understand → (clarify) → plan → (approve_plan) →
execute_step ⇄ reflect → synthesize.

Every node returns a partial state. UI events (phase, plan, tool calls, charts, report tokens) go
out through the `emit` coroutine passed in `config["configurable"]`, which chat_service streams to
the browser. "Waiting for the user" is a node that sets `pending` and ends the run; chat_service
stores the state and the next turn re-enters the graph from it (graph.route_entry).
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.exceptions import CostLimitExceededError
from app.db import crud
from app.db.database import SessionLocal
from app.services import summary_service
from app.agents.analysis import prompts
from app.agents.analysis.state import AnalysisState, PlanStep
from app.agents.analysis.time_range import resolve_time_range
from app.agents.analysis.tools import CHAT_TOOLS, execute_tool, openai_tools

logger = logging.getLogger(__name__)

Emit = Callable[[Dict[str, Any]], Awaitable[None]]

MAX_QUESTIONS = 3
MAX_REPLANS = 2
UNDERSTAND_MAX_TOKENS = 1200
PLAN_MAX_TOKENS = 1500
EXECUTE_MAX_TOKENS = 1500
REFLECT_MAX_TOKENS = 800
REPORT_MAX_TOKENS = 3000
PHASE_LABELS = {
    "understanding": "Soruyu anlıyorum",
    "planning": "Plan çıkarıyorum",
    "executing": "Analiz ediyorum",
    "reporting": "Raporu yazıyorum",
}


async def _emit(config, event_type: str, **data) -> None:
    emit: Optional[Emit] = (config or {}).get("configurable", {}).get("emit")
    if emit is not None:
        await emit({"type": event_type, **data})


async def _phase(config, phase: str, **extra) -> None:
    await _emit(config, "phase", phase=phase, label=PHASE_LABELS[phase], **extra)


def _today() -> str:
    return datetime.now(ZoneInfo(settings.newsletter_timezone)).strftime("%Y-%m-%d (%A)")


def _parse_json(text: str) -> Dict[str, Any]:
    """The model's JSON answer, or {} — a malformed answer must not crash the run."""
    try:
        value = json.loads(text or "{}")
    except ValueError:
        start, end = (text or "").find("{"), (text or "").rfind("}")
        try:
            value = json.loads(text[start:end + 1]) if start != -1 and end > start else {}
        except ValueError:
            value = {}
    return value if isinstance(value, dict) else {}


def _tool_lines(tools: List[str]) -> str:
    return "\n".join(f"- {name}: {CHAT_TOOLS[name].label} — {CHAT_TOOLS[name].description}" for name in tools)


def _questions(raw: Any) -> List[Dict[str, Any]]:
    """Normalise model-proposed clarifying questions: [{question, options[≤4]}], at most 3."""
    result = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and str(item.get("question") or "").strip():
            options = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()][:4]
            result.append({"question": str(item["question"]).strip(), "options": options})
    return result[:MAX_QUESTIONS]


def _steps(raw: Any, tools: List[str], first_id: int, limit: int, limitations: List[str]) -> List[PlanStep]:
    """Normalise model-proposed plan steps. A step naming a disabled tool is dropped and noted."""
    steps: List[PlanStep] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not str(item.get("goal") or "").strip():
            continue
        tool = str(item.get("tool") or "none").strip()
        if tool != "none" and tool not in tools:
            label = CHAT_TOOLS[tool].label if tool in CHAT_TOOLS else tool
            note = f"“{label}” aracı kapalı olduğu için bir plan adımı atlandı."
            if note not in limitations:
                limitations.append(note)
            continue
        steps.append({"id": first_id + len(steps), "goal": str(item["goal"]).strip(), "tool": tool,
                      "status": "pending", "finding": ""})
        if len(steps) >= limit:
            break
    return steps


_ALL_DATA_ANSWERS = {"tüm veriler", "tum veriler", "tüm zamanlar", "tümü", "tumu", "hepsi", "tüm dönem"}


def _answered_time_range(clarification: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, str]]]:
    """(True, range) when the user's clarification answer picks a period ("Son 30 gün"), (True, None)
    for "Tüm veriler", (False, None) otherwise. The answer wins over the question's own time words:
    the model tends to keep "son 24 saat" from the question after the user chose another period.
    A multi-question answer is "<question> <choice>" per line (ChatRun's ClarificationCard)."""
    questions = [str(q.get("question") or "") for q in clarification.get("questions") or []]
    for line in reversed(str(clarification.get("answer") or "").splitlines()):
        text = line.strip()
        for question in questions:
            if question and text.startswith(question):
                text = text[len(question):].strip()
        if text.lower().strip(" .") in _ALL_DATA_ANSWERS:
            return True, None
        resolved = resolve_time_range(text)
        if resolved is not None:
            return True, resolved
    return False, None


def _to_naive_utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).replace(tzinfo=None)


def _local_text(moment: datetime) -> str:
    """A naive UTC timestamp as the app's local time, for the user."""
    local = moment.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.newsletter_timezone))
    return local.strftime("%d.%m.%Y %H:%M")


def _add_cost(state: AnalysisState, response: Dict[str, Any]) -> float:
    return round(state.get("cost", 0.0) + (response.get("cost") or 0.0), 6)


def _plan_view(plan: List[PlanStep]) -> List[Dict[str, Any]]:
    return [{k: step.get(k) for k in ("id", "goal", "tool", "status", "finding")} for step in plan]


def _artifact_index(artifacts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    index = []
    for artifact in artifacts.values():
        if artifact.get("kind") == "table":
            index.append({"id": artifact["id"], "kind": "table", "purpose": artifact.get("purpose"),
                          "columns": artifact.get("columns"), "row_count": len(artifact.get("rows") or [])})
        else:
            index.append({"id": artifact["id"], "kind": artifact.get("kind"), "title": artifact.get("title")})
    return index


# ---------------------------------------------------------------------------
# understand
# ---------------------------------------------------------------------------

async def understand_node(state: AnalysisState, config) -> Dict[str, Any]:
    """Turn the question (plus earlier clarifications) into an intent; resolve its time range and
    check that the period holds any news at all. Every pass through here starts a fresh plan: an
    answer to a clarifying question can change the scope, so earlier steps would be stale."""
    await _phase(config, "understanding")
    tools = state.get("tools") or []
    clarifications = list(state.get("clarifications") or [])
    resume = state.get("resume") or {}
    answered = None
    if resume.get("kind") == "clarification":
        answered = {"questions": (state.get("pending") or {}).get("questions", []),
                    "answer": resume.get("answer", "")}
        clarifications.append(answered)

    db = SessionLocal()
    try:
        topics = [t.name for t in crud.get_topics(db)]
        feeds = [f.title or f.url for f in crud.get_feeds(db, active_only=False)]
    finally:
        db.close()

    system = prompts.UNDERSTAND.format(
        today=_today(), timezone=settings.newsletter_timezone,
        tools=", ".join(CHAT_TOOLS[t].label for t in tools),
        topics=", ".join(topics) or "—", feeds=", ".join(feeds) or "—",
    )
    user = {
        "soru": state.get("question", ""),
        "konuşma_geçmişi": state.get("history") or [],
        "netleştirmeler": clarifications,
        "önceki_niyet": state.get("intent") or None,
    }
    response = await summary_service.run_agent_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
        settings.chat_fast_model, UNDERSTAND_MAX_TOKENS, purpose="understand", json_mode=True,
    )
    intent = _parse_json(response["content"])
    intent.setdefault("restatement", state.get("question", ""))
    # "All known topics/feeds" is no filter: the model sometimes copies the whole list for a general
    # question, and the search then narrows to it for nothing.
    for key, known in (("topics", topics), ("feeds", feeds)):
        chosen = intent.get(key) if isinstance(intent.get(key), list) else []
        intent[key] = [] if len(known) > 1 and set(chosen) >= set(known) else chosen
    questions = _questions(intent.get("open_questions"))
    limitations = list(state.get("limitations") or [])

    time_range = state.get("time_range")
    expression = str(intent.get("time_expression") or "").strip()
    picked, picked_range = _answered_time_range(answered) if answered and "time" in tools else (False, None)
    if picked:
        time_range = picked_range
        intent["time_expression"] = picked_range["label"] if picked_range else None
        questions = [q for q in questions if not _is_period_question(q)]
    elif expression:
        if "time" in tools:
            time_range = resolve_time_range(expression)
            if time_range is None and not questions:
                questions = [{"question": f"“{expression}” ile hangi dönemi kastediyorsunuz?",
                              "options": ["Son 7 gün", "Son 30 gün", "Bu ay", "Tüm veriler"]}]
        else:
            time_range = None
            limitations.append(f"Zaman tespiti kapalı; “{expression}” ifadesi yorumlanarak kullanıldı.")

    coverage = _coverage(time_range)
    rounds = state.get("clarification_rounds", 0)
    can_ask = rounds < settings.chat_max_clarify_rounds
    if questions and not can_ask:
        assumptions = intent.setdefault("assumptions", [])
        assumptions.extend(f"Sorulmadı, varsayıldı: {q['question']}" for q in questions)
        questions = []
    if time_range is not None and coverage["aralıktaki_haber_sayısı"] == 0 and coverage["en_yeni_haber"]:
        empty = (f"Seçilen dönemde ({time_range['label']}) hiç haber yok; en yeni haber "
                 f"{coverage['en_yeni_haber']} tarihli.")
        if can_ask and not questions:
            options = [o for o in ("Son 7 gün", "Son 30 gün", "Tüm veriler") if o != time_range["label"]]
            questions = [{"question": f"{empty} Hangi dönemi inceleyelim?", "options": options}]
        elif empty not in limitations:
            limitations.append(empty)
    intent["open_questions"] = questions

    await _emit(config, "intent", restatement=intent["restatement"],
                time_range=time_range, assumptions=intent.get("assumptions") or [])
    return {
        "intent": intent,
        "time_range": time_range,
        "coverage": coverage,
        "clarifications": clarifications,
        "limitations": limitations,
        "pending": None,
        "resume": None,
        "plan": [],
        "current_step": 0,
        "replans": 0,
        "artifacts": {},
        "cost": _add_cost(state, response),
    }


def _is_period_question(question: Dict[str, Any]) -> bool:
    """A model question that asks for the period again although the user just picked one."""
    return any(resolve_time_range(option) is not None for option in question.get("options") or [])


def _coverage(time_range: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """How many articles the period holds and the newest article's date (local time), for the user's
    question about an empty period and as planning context."""
    db = SessionLocal()
    try:
        found = crud.get_article_coverage(
            db,
            _to_naive_utc(time_range["from"]) if time_range else None,
            _to_naive_utc(time_range["to"]) if time_range else None,
        )
    finally:
        db.close()
    return {
        "aralık": time_range["label"] if time_range else "tüm veriler",
        "aralıktaki_haber_sayısı": found["count"],
        "en_yeni_haber": _local_text(found["latest"]) if found["latest"] else None,
    }


def route_after_understand(state: AnalysisState) -> str:
    return "clarify" if (state.get("intent") or {}).get("open_questions") else "make_plan"


# ---------------------------------------------------------------------------
# clarify / approve_plan — end the run and wait for the user
# ---------------------------------------------------------------------------

async def clarify_node(state: AnalysisState, config) -> Dict[str, Any]:
    questions = state.get("ask_questions") or (state.get("intent") or {}).get("open_questions") or []
    restatement = (state.get("intent") or {}).get("restatement", "")
    await _emit(config, "clarification", questions=questions, restatement=restatement)
    return {
        "pending": {"kind": "clarification", "questions": questions, "restatement": restatement},
        "ask_questions": [],
        "clarification_rounds": state.get("clarification_rounds", 0) + 1,
    }


async def approve_plan_node(state: AnalysisState, config) -> Dict[str, Any]:
    await _emit(config, "plan_approval", steps=_plan_view(state.get("plan") or []))
    return {"pending": {"kind": "plan_approval"}}


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

async def plan_node(state: AnalysisState, config) -> Dict[str, Any]:
    await _phase(config, "planning")
    tools = state.get("tools") or []
    previous = [s for s in state.get("plan") or [] if s.get("status") in ("done", "failed")]
    system = prompts.PLAN.format(today=_today(), tools=_tool_lines(tools), data_model=prompts.DATA_MODEL,
                                 max_steps=settings.chat_max_steps)
    user = {
        "soru": state.get("question", ""),
        "niyet": state.get("intent") or {},
        "zaman_aralığı": state.get("time_range"),
        "veri_kapsamı": state.get("coverage"),
        "netleştirmeler": state.get("clarifications") or [],
        "önceki_adımlar": _plan_view(previous),
        "kullanıcının_plan_notu": state.get("plan_note"),
    }
    response = await summary_service.run_agent_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
        settings.chat_model, PLAN_MAX_TOKENS, purpose="plan", json_mode=True,
    )
    limitations = list(state.get("limitations") or [])
    room = max(1, settings.chat_max_steps - len(previous))
    steps = _steps(_parse_json(response["content"]).get("steps"), tools, len(previous) + 1, room, limitations)
    if not steps:
        fallback_tool = "sql" if "sql" in tools else "none"
        goal = (state.get("intent") or {}).get("restatement") or state.get("question", "")
        steps = [{"id": len(previous) + 1, "goal": goal, "tool": fallback_tool,
                  "status": "pending", "finding": ""}]
    plan = list(previous) + steps
    requires_approval = bool(state.get("require_plan_approval"))
    await _emit(config, "plan", steps=_plan_view(plan), requires_approval=requires_approval)
    return {
        "plan": plan,
        "current_step": len(previous),
        "plan_note": None,
        "limitations": limitations,
        "cost": _add_cost(state, response),
    }


def route_after_plan(state: AnalysisState) -> str:
    return "approve_plan" if state.get("require_plan_approval") else "execute_step"


# ---------------------------------------------------------------------------
# execute_step — a small tool-calling loop for the current step
# ---------------------------------------------------------------------------

async def execute_step_node(state: AnalysisState, config) -> Dict[str, Any]:
    plan = [dict(step) for step in state.get("plan") or []]
    index = state.get("current_step", 0)
    if index >= len(plan):
        return {}
    step = plan[index]
    step["status"] = "running"
    tools = state.get("tools") or []
    artifacts = dict(state.get("artifacts") or {})
    cost = state.get("cost", 0.0)
    await _phase(config, "executing", step=index + 1, total=len(plan))
    await _emit(config, "step_started", step_id=step["id"], goal=step["goal"], tool=step["tool"])

    system = prompts.EXECUTE.format(today=_today(), data_model=prompts.DATA_MODEL,
                                    max_calls=settings.chat_max_tool_calls_per_step)
    context = {
        "soru": state.get("question", ""),
        "niyet": state.get("intent") or {},
        "zaman_aralığı": state.get("time_range"),
        "veri_kapsamı": state.get("coverage"),
        "plan": _plan_view(plan),
        "saklanan_tablolar": _artifact_index(artifacts),
        "şu_anki_adım": {"id": step["id"], "hedef": step["goal"], "önerilen_araç": step["tool"]},
    }
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]
    schemas = openai_tools(tools)
    calls_left = settings.chat_max_tool_calls_per_step
    finding = ""
    failed = False
    stop_reason = state.get("stop_reason")
    summaries: List[str] = []
    try:
        while True:
            response = await summary_service.run_agent_llm(
                messages, settings.chat_model, EXECUTE_MAX_TOKENS, purpose="execute",
                tools=schemas if calls_left > 0 and schemas else None,
            )
            cost = round(cost + (response.get("cost") or 0.0), 6)
            # Parallel calls beyond the step's budget are dropped from the assistant turn too, so
            # every call the model is shown gets exactly one tool reply.
            calls = response["tool_calls"][:calls_left] if calls_left > 0 else []
            if not calls:
                finding = response["content"].strip()
                break
            messages.append({
                "role": "assistant", "content": response["content"] or None,
                "tool_calls": [{"id": c["id"], "type": "function",
                                "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls],
            })
            for call in calls:
                artifact_id = f"a{len(artifacts) + 1}"
                await _emit(config, "tool_call", step_id=step["id"], call_id=call["id"], name=call["name"],
                            arguments=call["arguments"])
                result = await execute_tool(call["name"], call["arguments"], tools, artifact_id)
                cost = round(cost + (result.get("cost") or 0.0), 6)
                if result.get("artifact"):
                    artifacts[artifact_id] = result["artifact"]
                if result.get("chart"):
                    await _emit(config, "chart", step_id=step["id"], chart=result["chart"])
                await _emit(config, "tool_result", step_id=step["id"], call_id=call["id"], tool=result["tool"],
                            ok=result["ok"], summary=result["summary"], sql=result.get("sql"),
                            artifact_id=artifact_id if result.get("artifact") else None)
                summaries.append(result["summary"])
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result["content"]})
            calls_left -= len(calls)
            if cost >= settings.chat_max_cost_per_run:
                finding = "Çalıştırma başına bütçe doldu; adım yarıda kaldı. Araç sonuçları: " + "; ".join(summaries)
                stop_reason = "budget"
                break
    except CostLimitExceededError as e:
        failed, stop_reason = True, "cost_limit"
        finding = f"Maliyet sınırına ulaşıldı: {e}"
    except Exception as e:
        logger.exception("Asistan step %s failed", step["id"])
        failed = True
        finding = f"Adım çalıştırılamadı: {e}"

    if not finding:
        finding = "; ".join(summaries) or "Bulgu yok."
    step["status"] = "failed" if failed else "done"
    step["finding"] = finding
    plan[index] = step
    await _emit(config, "step_result", step_id=step["id"], status=step["status"], finding=finding)
    return {"plan": plan, "artifacts": artifacts, "cost": cost, "stop_reason": stop_reason}


# ---------------------------------------------------------------------------
# reflect — continue / replan / ask the user / finish
# ---------------------------------------------------------------------------

async def reflect_node(state: AnalysisState, config) -> Dict[str, Any]:
    plan = [dict(step) for step in state.get("plan") or []]
    index = state.get("current_step", 0)
    next_index = index + 1
    limitations = list(state.get("limitations") or [])
    cost = state.get("cost", 0.0)

    if state.get("stop_reason") or cost >= settings.chat_max_cost_per_run:
        note = ("OpenAI maliyet sınırına ulaşıldığı için analiz erken bitirildi."
                if state.get("stop_reason") == "cost_limit"
                else "Bu analiz için ayrılan bütçe dolduğu için kalan adımlar çalıştırılmadı.")
        if note not in limitations:
            limitations.append(note)
        return {"plan": _skip_from(plan, next_index), "current_step": len(plan), "limitations": limitations,
                "stop_reason": state.get("stop_reason") or "budget"}

    tools = state.get("tools") or []
    user = {
        "soru": state.get("question", ""),
        "niyet": state.get("intent") or {},
        "plan": _plan_view(plan),
        "son_adım": _plan_view([plan[index]])[0] if index < len(plan) else None,
        "kalan_adım_sayısı": max(0, len(plan) - next_index),
        "kullanıcıya_soru_sorulabilir": state.get("clarification_rounds", 0) < settings.chat_max_clarify_rounds,
    }
    try:
        response = await summary_service.run_agent_llm(
            [{"role": "system", "content": prompts.REFLECT.format(tools=", ".join(tools))},
             {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
            settings.chat_fast_model, REFLECT_MAX_TOKENS, purpose="reflect", json_mode=True,
        )
    except CostLimitExceededError:
        limitations.append("OpenAI maliyet sınırına ulaşıldığı için analiz erken bitirildi.")
        return {"plan": _skip_from(plan, next_index), "current_step": len(plan), "limitations": limitations,
                "stop_reason": "cost_limit"}
    cost = _add_cost(state, response)
    answer = _parse_json(response["content"])
    decision = answer.get("decision")
    update: Dict[str, Any] = {"cost": cost, "limitations": limitations}

    if decision == "replan" and state.get("replans", 0) < MAX_REPLANS:
        room = settings.chat_max_steps - next_index
        new_steps = _steps(answer.get("new_steps"), tools, next_index + 1, room, limitations) if room > 0 else []
        if new_steps:
            plan = plan[:next_index] + new_steps
            await _emit(config, "replan", reason=str(answer.get("reason") or ""), steps=_plan_view(plan))
            return {**update, "plan": plan, "current_step": next_index, "replans": state.get("replans", 0) + 1}

    if decision == "ask_user" and user["kullanıcıya_soru_sorulabilir"]:
        questions = _questions(answer.get("questions"))
        if questions:
            return {**update, "plan": _skip_from(plan, next_index), "current_step": len(plan),
                    "ask_questions": questions}

    if decision == "finish":
        return {**update, "plan": _skip_from(plan, next_index), "current_step": len(plan)}
    return {**update, "current_step": next_index}


def _skip_from(plan: List[PlanStep], index: int) -> List[PlanStep]:
    return [dict(step, status="skipped") if i >= index and step.get("status") == "pending" else step
            for i, step in enumerate(plan)]


def route_after_reflect(state: AnalysisState) -> str:
    if state.get("ask_questions"):
        return "clarify"
    if state.get("current_step", 0) < len(state.get("plan") or []):
        return "execute_step"
    return "synthesize"


# ---------------------------------------------------------------------------
# synthesize — the streamed final report
# ---------------------------------------------------------------------------

def _report_tables(artifacts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    tables = []
    for artifact in artifacts.values():
        if artifact.get("kind") == "table":
            tables.append({"id": artifact["id"], "purpose": artifact.get("purpose"), "columns": artifact["columns"],
                           "rows": artifact["rows"][:30], "row_count": len(artifact["rows"])})
        elif artifact.get("kind") == "chart":
            tables.append({"id": artifact["id"], "chart": artifact.get("title")})
    return tables


async def synthesize_node(state: AnalysisState, config) -> Dict[str, Any]:
    await _phase(config, "reporting")
    intent = state.get("intent") or {}
    user = {
        "soru": state.get("question", ""),
        "anlaşılan_amaç": intent.get("restatement"),
        "varsayımlar": intent.get("assumptions") or [],
        "zaman_aralığı": state.get("time_range"),
        "plan_ve_bulgular": _plan_view(state.get("plan") or []),
        "tablolar_ve_grafikler": _report_tables(state.get("artifacts") or {}),
        "sınırlamalar": state.get("limitations") or [],
    }
    messages = [
        {"role": "system", "content": prompts.REPORT.format(today=_today())},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
    parts: List[str] = []
    cost = state.get("cost", 0.0)
    try:
        async for kind, value in summary_service.stream_agent_llm(
            messages, settings.chat_model, REPORT_MAX_TOKENS, purpose="report",
        ):
            if kind == "token":
                parts.append(value)
                await _emit(config, "token", text=value)
            else:
                cost = round(cost + value, 6)
    except Exception as e:
        logger.exception("Asistan report failed")
        fallback = _fallback_report(state, e)
        parts.append(fallback)
        await _emit(config, "token", text=fallback)
    return {"report": "".join(parts).strip(), "cost": cost, "pending": None}


def _fallback_report(state: AnalysisState, error: Exception) -> str:
    lines = [f"\n\nRapor yazılamadı ({error}). Adımların bulguları:"]
    for step in state.get("plan") or []:
        if step.get("finding"):
            lines.append(f"- **{step['goal']}**: {step['finding']}")
    return "\n".join(lines)
