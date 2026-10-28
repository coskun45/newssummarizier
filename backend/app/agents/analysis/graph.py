"""
The Asistan's analysis graph (LangGraph):

    understand ─(belirsiz)→ clarify → END            (waits for the user's answer)
        │
        └→ make_plan ─(onay ayarı açık)→ approve_plan → END (waits for "Başlat" / a revision note)
             │
             └→ execute_step → reflect ─→ execute_step (next step / replanned steps)
                                     ├─→ clarify → END
                                     └─→ synthesize → END

(The planning node is "make_plan": "plan" is a state key, and LangGraph forbids the clash.)
The graph has no checkpointer: a run that waits for the user ends, chat_service stores the state on
the conversation, and the next turn enters again through `route_entry`, which picks the node that
continues from the stored `pending` + the user's `resume` answer.
"""
from functools import lru_cache

from langgraph.graph import END, StateGraph

from app.agents.analysis import nodes
from app.agents.analysis.state import AnalysisState


def route_entry(state: AnalysisState) -> str:
    resume = state.get("resume") or {}
    if resume.get("kind") == "plan_approval":
        return "execute_step" if resume.get("action") == "start" else "make_plan"
    return "understand"  # a new question, or the answer to a clarifying question


@lru_cache(maxsize=1)
def build_analysis_graph():
    workflow = StateGraph(AnalysisState)
    workflow.add_node("understand", nodes.understand_node)
    workflow.add_node("clarify", nodes.clarify_node)
    workflow.add_node("make_plan", nodes.plan_node)
    workflow.add_node("approve_plan", nodes.approve_plan_node)
    workflow.add_node("execute_step", nodes.execute_step_node)
    workflow.add_node("reflect", nodes.reflect_node)
    workflow.add_node("synthesize", nodes.synthesize_node)

    workflow.set_conditional_entry_point(
        route_entry, {"understand": "understand", "make_plan": "make_plan", "execute_step": "execute_step"}
    )
    workflow.add_conditional_edges("understand", nodes.route_after_understand,
                                   {"clarify": "clarify", "make_plan": "make_plan"})
    workflow.add_edge("clarify", END)
    workflow.add_conditional_edges("make_plan", nodes.route_after_plan,
                                   {"approve_plan": "approve_plan", "execute_step": "execute_step"})
    workflow.add_edge("approve_plan", END)
    workflow.add_edge("execute_step", "reflect")
    workflow.add_conditional_edges("reflect", nodes.route_after_reflect,
                                   {"execute_step": "execute_step", "clarify": "clarify", "synthesize": "synthesize"})
    workflow.add_edge("synthesize", END)
    return workflow.compile()
