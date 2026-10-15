import json
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import select

from app.database.models import Conversation, Customer, Lead
from app.graph.sales_graph import MAX_GRAPH_STEPS, build_sales_graph
from app.tools.product_tools import build_product_tools
from tests.conftest import ScriptedLLM, tool_call


def _run(llm, session, text="hi"):
    customer = Customer(phone="+923001234567")
    session.add(customer)
    session.flush()
    conversation = Conversation(customer_id=customer.id)
    session.add(conversation)
    session.flush()
    graph = build_sales_graph(
        llm,
        session,
        customer.id,
        conversation.id,
        "USD",
        use_inventory_api=False,
    )
    state = {"messages": [HumanMessage(content=text)], "customer_id": customer.id,
             "phone_number": customer.phone, "conversation_id": conversation.id}
    return graph.invoke(state, config={"recursion_limit": MAX_GRAPH_STEPS}), customer, conversation


def test_tool_loop_returns_real_db_data_to_llm(session):
    llm = ScriptedLLM([
        tool_call("search_products", {"query": "wireless keyboard"}),
        AIMessage(content="Yes! The Logitech K380 is $35."),
    ])
    result, _, _ = _run(llm, session, "Do you have a wireless keyboard?")
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert "Logitech K380 Wireless Keyboard" in tool_msgs[0].content and "35.00" in tool_msgs[0].content
    assert result["messages"][-1].content == "Yes! The Logitech K380 is $35."
    # the second LLM call saw the tool result
    assert any(isinstance(m, ToolMessage) for m in llm.calls[1])


def test_no_tool_call_goes_straight_to_end(session):
    llm = ScriptedLLM([AIMessage(content="Hello!")])
    result, _, _ = _run(llm, session)
    assert len(llm.calls) == 1 and result["messages"][-1].content == "Hello!"


def test_unknown_product_tool_result_is_empty(session):
    llm = ScriptedLLM([tool_call("search_products", {"query": "spaceship"}), AIMessage(content="Not found.")])
    result, _, _ = _run(llm, session)
    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert '"count": 0' in tool_msg.content


def test_inventory_name_search_then_id_lookup_keeps_zero_stock_product(session):
    product = {
        "id": "inv-notebook-a4",
        "name": "Notebook A4",
        "price": 4.99,
        "quantity": 0,
    }
    inventory_client = Mock()
    inventory_client.list_products.return_value = [product]
    inventory_client.get_product.return_value = product
    llm = ScriptedLLM([
        tool_call("search_products", {"query": "Notebook A4"}, "search"),
        tool_call("get_product", {"product_id": product["id"]}, "details"),
        AIMessage(content="Notebook A4 exists, but is currently out of stock."),
    ])
    tools = build_product_tools(session, "USD", inventory_client)

    with patch("app.graph.sales_graph.build_tools", return_value=tools):
        result, _, _ = _run(llm, session, "Do you have Notebook A4?")

    tool_messages = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    search_result = json.loads(tool_messages[0].content)
    detail_result = json.loads(tool_messages[1].content)
    tool_call_names = []
    for messages in llm.calls:
        assistant_tool_calls = [
            message.tool_calls
            for message in messages
            if isinstance(message, AIMessage) and message.tool_calls
        ]
        if assistant_tool_calls:
            tool_call_names.append(assistant_tool_calls[-1][0]["name"])

    assert search_result == {"count": 1, "products": [product]}
    assert search_result["products"][0]["quantity"] == 0
    assert detail_result == {"found": True, "product": product}
    inventory_client.get_product.assert_called_once_with("inv-notebook-a4")
    assert tool_call_names == [
        "search_products",
        "get_product",
    ]
    assert result["messages"][-1].content == (
        "Notebook A4 exists, but is currently out of stock."
    )


def test_create_lead_and_escalate_write_to_db(session):
    llm = ScriptedLLM([
        tool_call("create_lead", {"interest": "2x Logitech K380"}, "c1"),
        tool_call("escalate_to_human", {"reason": "order request"}, "c2"),
        AIMessage(content="A team member will help you finish."),
    ])
    _, customer, conversation = _run(llm, session)
    lead = session.scalar(select(Lead))
    assert lead.customer_id == customer.id and lead.conversation_id == conversation.id
    session.refresh(conversation)
    assert conversation.status == "escalated" and conversation.escalation_reason == "order request"


def test_tool_loop_is_bounded(session):
    import pytest
    from langgraph.errors import GraphRecursionError

    llm = ScriptedLLM([tool_call("search_products", {"query": "x"}, f"c{i}") for i in range(50)])
    with pytest.raises(GraphRecursionError):
        _run(llm, session)
