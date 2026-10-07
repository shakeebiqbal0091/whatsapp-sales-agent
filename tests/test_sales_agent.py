from app.agents.sales_agent import SYSTEM_PROMPT, SalesAgent
from app.tools import build_tools
from tests.conftest import ScriptedLLM, tool_call
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def test_agent_prepends_system_prompt_and_returns_llm_message(session):
    llm = ScriptedLLM([AIMessage(content="Hi! How can I help?")])
    agent = SalesAgent(llm, build_tools(session, 1, 1, "USD"))
    out = agent.run({"messages": [HumanMessage(content="Hello")]})
    sent = llm.calls[0]
    assert isinstance(sent[0], SystemMessage) and sent[0].content == SYSTEM_PROMPT
    assert out["messages"][0].content == "Hi! How can I help?"


def test_toolset_matches_claude_md(session):
    names = {t.name for t in build_tools(session, 1, 1, "USD")}
    assert names == {
        "search_products", "get_product", "check_stock", "create_lead", "escalate_to_human",
    }


def test_llm_cannot_supply_customer_or_conversation_ids(session):
    for t in build_tools(session, 1, 1, "USD"):
        assert "customer_id" not in t.args and "conversation_id" not in t.args


def test_tool_schema_rejects_bad_quantity(session):
    tools = {t.name: t for t in build_tools(session, 1, 1, "USD")}
    try:
        tools["check_stock"].invoke({"product_id": 1, "quantity": -3})
    except Exception as exc:
        assert "quantity" in str(exc)
    else:
        raise AssertionError("negative quantity should be rejected")


def test_prompt_contains_grounding_rules():
    for phrase in ("Never invent", "Always use the tools", "Never claim an order"):
        assert phrase in SYSTEM_PROMPT
