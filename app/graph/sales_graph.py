"""START -> agent -> (tools -> agent)* -> END. Deliberately minimal (CLAUDE.md §14)."""
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy.orm import Session

from app.agents.sales_agent import SalesAgent
from app.graph.state import SalesState
from app.tools import build_tools

MAX_GRAPH_STEPS = 12  # ~5 tool round-trips; guards against tool-call loops


def build_sales_graph(
    llm: BaseChatModel, session: Session, customer_id: int, conversation_id: int, currency: str
):
    tools = build_tools(session, customer_id, conversation_id, currency)
    agent = SalesAgent(llm, tools)

    graph = StateGraph(SalesState)
    graph.add_node("agent", agent.run)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()
