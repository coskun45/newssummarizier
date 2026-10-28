"""
State of the Asistan's analysis graph. It is JSON-serialisable on purpose: between HTTP turns
(a clarifying question, a plan waiting for approval) it is stored on the conversation
(`ChatConversation.agent_state`) and the next turn resumes from it.
"""
from typing import Any, Dict, List, Optional, TypedDict


class PlanStep(TypedDict, total=False):
    id: int
    goal: str
    tool: str  # a tool name, or "none"
    status: str  # pending | running | done | failed | skipped
    finding: str


class AnalysisState(TypedDict, total=False):
    question: str  # the analysis question of the current run
    history: List[Dict[str, str]]  # earlier turns ({role, content}) for context
    tools: List[str]  # tools enabled when the run started; fixed for the whole run
    require_plan_approval: bool

    clarifications: List[Dict[str, Any]]  # [{questions, answer}]
    clarification_rounds: int
    ask_questions: List[Dict[str, Any]]  # questions the reflect stage wants to ask
    pending: Optional[Dict[str, Any]]  # {"kind": "clarification" | "plan_approval", ...} = waiting for the user
    resume: Optional[Dict[str, Any]]  # the user's answer to `pending`, set by chat_service

    intent: Dict[str, Any]
    time_range: Optional[Dict[str, str]]
    coverage: Dict[str, Any]  # articles in time_range + the newest article's date (understand)
    plan: List[PlanStep]
    plan_note: Optional[str]  # the user's note when revising a plan
    current_step: int
    replans: int
    artifacts: Dict[str, Dict[str, Any]]  # SQL result tables and charts, by id
    limitations: List[str]

    cost: float  # USD spent by this run
    stop_reason: Optional[str]  # set when the run must wrap up (budget, cost limit)
    report: str
