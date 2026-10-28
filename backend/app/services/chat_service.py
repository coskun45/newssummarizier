"""
Runs one Asistan turn: builds the analysis graph's input from the conversation's stored state and
the user's message, runs the graph, streams its events to the browser as Server-Sent Events, and
stores the outcome (assistant message + the state to resume from).

Runs after the request handler has returned (inside the StreamingResponse), so it opens its own
sessions like the agent code does.
"""
import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core.config import settings
from app.db import crud
from app.db.database import SessionLocal
from app.agents.analysis.graph import build_analysis_graph
from app.agents.analysis.tools import get_chat_require_plan_approval, get_enabled_chat_tools

logger = logging.getLogger(__name__)

HISTORY_TURNS = 6  # earlier question/report pairs given to the agent as context
HISTORY_CHARS = 1500
KEEPALIVE_SECONDS = 15  # an SSE comment while a slow step runs, so proxies don't cut the stream
_DONE = object()


def sse(event: Dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def load_state(raw: Optional[str]) -> Dict[str, Any]:
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    return state if isinstance(state, dict) else {}


def pending_of(conversation) -> Optional[Dict[str, Any]]:
    """What a conversation waits for (clarifying questions / plan approval), for the UI on reload."""
    if conversation.status not in ("awaiting_clarification", "awaiting_plan_approval"):
        return None
    state = load_state(conversation.agent_state)
    pending = state.get("pending")
    if not pending:
        return None
    if pending.get("kind") == "plan_approval":
        return {**pending, "steps": state.get("plan") or []}
    return pending


def _new_run_state(db, question: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "question": question,
        "history": history,
        "tools": get_enabled_chat_tools(db),
        "require_plan_approval": get_chat_require_plan_approval(db),
        "clarifications": [],
        "clarification_rounds": 0,
        "ask_questions": [],
        "pending": None,
        "resume": None,
        "intent": {},
        "time_range": None,
        "plan": [],
        "plan_note": None,
        "current_step": 0,
        "replans": 0,
        "artifacts": {},
        "limitations": [],
        "cost": 0.0,
        "stop_reason": None,
        "report": "",
    }


def build_turn_state(db, stored: Dict[str, Any], previous_status: str, content: str, action: str) -> Dict[str, Any]:
    """The graph input for this turn: an answer resumes the waiting run, anything else starts a new one."""
    if previous_status == "awaiting_clarification" and stored.get("pending"):
        return {**stored, "resume": {"kind": "clarification", "answer": content}}
    if previous_status == "awaiting_plan_approval" and stored.get("pending"):
        if action == "approve_plan" and not content.strip():
            return {**stored, "pending": None, "resume": {"kind": "plan_approval", "action": "start"}}
        return {**stored, "pending": None, "plan_note": content,
                "resume": {"kind": "plan_approval", "action": "revise"}}
    return _new_run_state(db, content, stored.get("history") or [])


def _outcome(final: Dict[str, Any]) -> Dict[str, Any]:
    """Conversation status, assistant message text and the state to store, from a finished run."""
    pending = final.get("pending")
    if pending and pending.get("kind") == "clarification":
        lines = [pending.get("restatement") or "Sorunuzu netleştirmek istiyorum:"]
        for question in pending.get("questions") or []:
            options = " / ".join(question.get("options") or [])
            lines.append(f"- {question['question']}" + (f" ({options})" if options else ""))
        return {"status": "awaiting_clarification", "content": "\n".join(lines), "state": final}
    if pending and pending.get("kind") == "plan_approval":
        return {"status": "awaiting_plan_approval", "content": "Analiz planı onayınızı bekliyor.", "state": final}
    report = final.get("report") or ""
    history = list(final.get("history") or []) + [
        {"role": "user", "content": final.get("question", "")},
        {"role": "assistant", "content": report[:HISTORY_CHARS]},
    ]
    return {"status": "idle", "content": report, "state": {"history": history[-2 * HISTORY_TURNS:]}}


def _store(conversation_id: int, status: str, state: Optional[Dict[str, Any]], content: str,
           events: List[Dict[str, Any]], cost: float) -> Optional[int]:
    db = SessionLocal()
    try:
        message = crud.add_chat_message(
            db, conversation_id, "assistant", content,
            events=json.dumps(events, ensure_ascii=False, default=str), cost=round(cost, 6),
        )
        crud.update_chat_conversation(
            db, conversation_id, status=status,
            agent_state=json.dumps(state, ensure_ascii=False, default=str) if state is not None else None,
        )
        return message.id
    except Exception:
        logger.exception("Could not store Asistan turn of conversation %s", conversation_id)
        _free(conversation_id)
        return None
    finally:
        db.close()


def _free(conversation_id: int) -> None:
    """Last resort after a failed store: a conversation left `running` would refuse every send and
    delete (409) until the next restart, so at least set it back to idle — in a fresh session."""
    db = SessionLocal()
    try:
        crud.update_chat_conversation(db, conversation_id, status="idle")
    except Exception:
        logger.exception("Could not free Asistan conversation %s", conversation_id)
    finally:
        db.close()


async def stream_turn(conversation_id: int, previous_status: str, content: str, action: str) -> AsyncIterator[str]:
    """SSE stream of one turn. The conversation is already claimed (`running`) by the route."""
    db = SessionLocal()
    try:
        conversation = crud.get_chat_conversation(db, conversation_id)
        stored = load_state(conversation.agent_state if conversation else None)
        state = build_turn_state(db, stored, previous_status, content, action)
    finally:
        db.close()

    queue: asyncio.Queue = asyncio.Queue()
    events: List[Dict[str, Any]] = []
    start_cost = state.get("cost", 0.0)
    # The state after the last finished node: a failed or stopped run still stores what it spent.
    latest: Dict[str, Any] = {"state": state}

    def spent() -> float:
        return round(max(0.0, (latest["state"].get("cost") or 0.0) - start_cost), 6)

    async def emit(event: Dict[str, Any]) -> None:
        if event["type"] != "token":
            events.append(event)
        await queue.put(event)

    async def run() -> Dict[str, Any]:
        try:
            async for value in build_analysis_graph().astream(
                state,
                config={"configurable": {"emit": emit}, "recursion_limit": 4 * settings.chat_max_steps + 20},
                stream_mode="values",
            ):
                latest["state"] = value
            return latest["state"]
        finally:
            await queue.put(_DONE)

    task = asyncio.create_task(run())
    stored_turn = False
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if item is _DONE:
                break
            yield sse(item)

        try:
            final = task.result()
        except Exception as e:
            logger.exception("Asistan run failed in conversation %s", conversation_id)
            text = f"Analiz tamamlanamadı: {e}"
            events.append({"type": "error", "message": text})
            yield sse(events[-1])
            message_id = _store(conversation_id, "idle", {"history": stored.get("history") or []}, text, events,
                                spent())
            stored_turn = True
            yield sse({"type": "done", "message_id": message_id, "status": "idle", "cost": spent()})
            return

        outcome = _outcome(final)
        cost = final.get("cost", 0.0) - start_cost
        message_id = _store(conversation_id, outcome["status"], outcome["state"], outcome["content"], events, cost)
        stored_turn = True
        yield sse({"type": "done", "message_id": message_id, "status": outcome["status"], "cost": round(cost, 6)})
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except BaseException:
                pass
        if not stored_turn:
            # The client went away (Durdur / closed tab): keep what was streamed, free the conversation.
            events.append({"type": "stopped"})
            _store(conversation_id, "idle", {"history": stored.get("history") or []}, "Analiz durduruldu.",
                   events, spent())
