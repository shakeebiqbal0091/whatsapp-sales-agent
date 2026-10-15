from unittest.mock import Mock, call

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.agents.sales_agent import FALLBACK_REPLY
from app.database.models import Conversation, Customer, Message
from app.database.repositories.conversation_repository import ConversationRepository
from app.graph import sales_graph
from app.services.chat_service import (
    HANDOFF_REPLY,
    NEW_QUESTION_CLARIFICATION,
)
from app.services.conversation_service import ConversationService
from app.services.customer_service import CustomerService
from app.schemas.customer import normalize_phone
from app.tools.product_tools import build_product_tools
from tests.conftest import ScriptedLLM, tool_call

PHONE = "+92 300 1234567"


def counts(session_factory):
    with session_factory() as s:
        return (
            s.scalar(select(func.count(Customer.id))),
            s.scalar(select(func.count(Conversation.id))),
            s.scalar(select(func.count(Message.id))),
        )


def create_escalated_conversation(session_factory):
    with session_factory() as session:
        customer = CustomerService(session).identify(normalize_phone(PHONE))
        conversation = ConversationService(session).get_or_open(customer.id)
        ConversationService(session).add_message(
            conversation.id, "user", "Pending human request"
        )
        ConversationService(session).escalate(conversation.id, "human review")
        session.commit()
        return customer.id, conversation.id


def messages_for_conversation(session_factory, conversation_id):
    with session_factory() as session:
        conversation = session.get(Conversation, conversation_id)
        messages = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        )
        return conversation.status, [
            (message.role, message.content) for message in messages
        ]


def test_chat_roundtrip_persists_everything(make_client, session_factory):
    llm = ScriptedLLM([
        tool_call("search_products", {"query": "K380"}),
        AIMessage(content="Yes! K380 is $35, 12 in stock."),
    ])
    r = make_client(llm).post("/chat", json={"phone": PHONE, "message": "Do you have a K380?"})
    assert r.status_code == 200 and r.json() == {"response": "Yes! K380 is $35, 12 in stock."}
    with session_factory() as s:
        assert [m.role for m in s.scalars(select(Message).order_by(Message.id))] == ["user", "tool", "assistant"]
        assert s.scalar(select(Customer.phone)) == "+923001234567"


def test_same_phone_reuses_customer_and_replays_history(make_client, session_factory):
    llm = ScriptedLLM([AIMessage(content="Hello!"), AIMessage(content="Sure.")])
    client = make_client(llm)
    client.post("/chat", json={"phone": "+923001234567", "message": "Hi"})
    client.post("/chat", json={"phone": "923001234567", "message": "Keyboards?"})  # WhatsApp-style, no '+'
    assert counts(session_factory) == (1, 1, 4)
    second_call = llm.calls[1]
    assert [type(m).__name__ for m in second_call] == ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"]


def test_escalation_then_handoff_without_calling_llm(make_client, session_factory):
    llm = ScriptedLLM([
        tool_call("escalate_to_human", {"reason": "customer asked for a human"}),
        AIMessage(content="I'll connect you with our team."),
    ])
    client = make_client(llm)
    first = client.post("/chat", json={"phone": PHONE, "message": "I want to talk to a human."})
    assert first.json()["response"] == "I'll connect you with our team."
    second = client.post("/chat", json={"phone": PHONE, "message": "hello?"})
    assert second.json()["response"] == HANDOFF_REPLY
    assert len(llm.calls) == 2  # no LLM call on the second message


def test_escalated_new_question_uses_separate_inventory_backed_conversation(
    make_client, session_factory, monkeypatch
):
    customer_id, escalated_id = create_escalated_conversation(session_factory)
    original_history = messages_for_conversation(session_factory, escalated_id)
    product = {
        "id": "inv-notebook-a4",
        "name": "Notebook A4",
        "price": 4.99,
        "quantity": 0,
    }
    inventory_client = Mock()
    inventory_client.list_products.return_value = [product]
    graph_context = []

    def build_inventory_tools(session, customer_id, conversation_id, currency, **kwargs):
        graph_context.append((customer_id, conversation_id))
        return build_product_tools(session, currency, inventory_client)

    monkeypatch.setattr(sales_graph, "build_tools", build_inventory_tools)
    llm = ScriptedLLM(
        [
            tool_call("search_products", {"query": "Notebook A4"}),
            AIMessage(content="Notebook A4 is $4.99 and out of stock (0 available)."),
            AIMessage(content="What else can I help you find?"),
        ]
    )
    client = make_client(llm)

    first = client.post(
        "/chat",
        json={
            "phone": PHONE,
            "message": "  nEw QuEsTiOn: What is the price and stock of Notebook A4?  ",
        },
    )
    assert first.json()["response"] == (
        "Notebook A4 is $4.99 and out of stock (0 available)."
    )

    new_conversation_id = graph_context[0][1]
    assert new_conversation_id != escalated_id
    assert graph_context[0][0] == customer_id
    assert inventory_client.list_products.call_count == 1
    tool_message = next(
        message
        for message in llm.calls[1]
        if isinstance(message, ToolMessage)
    )
    assert '"quantity": 0' in tool_message.content
    assert any(
        isinstance(message, HumanMessage)
        and message.content == "What is the price and stock of Notebook A4?"
        for message in llm.calls[0]
    )

    with session_factory() as session:
        assert session.get(Conversation, escalated_id).status == "escalated"
        new_conversation = session.get(Conversation, new_conversation_id)
        assert new_conversation.customer_id == customer_id
        assert new_conversation.status == "open"
        new_messages = session.scalars(
            select(Message)
            .where(Message.conversation_id == new_conversation_id)
            .order_by(Message.id)
        )
        assert [(m.role, m.content) for m in new_messages] == [
            ("user", "What is the price and stock of Notebook A4?"),
            ("tool", tool_message.content),
            ("assistant", "Notebook A4 is $4.99 and out of stock (0 available)."),
        ]

    assert messages_for_conversation(session_factory, escalated_id) == original_history

    follow_up = client.post(
        "/chat",
        json={"phone": PHONE, "message": "Can you suggest another item?"},
    )
    assert follow_up.json()["response"] == "What else can I help you find?"
    assert graph_context == [
        (customer_id, new_conversation_id),
        (customer_id, new_conversation_id),
    ]
    assert messages_for_conversation(session_factory, escalated_id) == original_history
    assert messages_for_conversation(session_factory, new_conversation_id)[0] == "open"


def test_prefixed_request_is_stripped_when_open_conversation_already_exists(
    make_client, session_factory, monkeypatch
):
    customer_id, escalated_id = create_escalated_conversation(session_factory)
    with session_factory() as session:
        conversation = ConversationService(session).get_or_open_ai_conversation(
            customer_id
        )
        session.commit()
        open_conversation_id = conversation.id

    graph_context = []

    def build_tools(_session, graph_customer_id, conversation_id, *_args, **_kwargs):
        graph_context.append((graph_customer_id, conversation_id))
        return []

    monkeypatch.setattr(sales_graph, "build_tools", build_tools)
    llm = ScriptedLLM([AIMessage(content="Inventory question answered.")])

    response = make_client(llm).post(
        "/chat",
        json={
            "phone": PHONE,
            "message": "  NEW QUESTION:  What is in stock?  ",
        },
    )

    assert response.json()["response"] == "Inventory question answered."
    assert graph_context == [(customer_id, open_conversation_id)]
    assert any(
        isinstance(message, HumanMessage)
        and message.content == "What is in stock?"
        for message in llm.calls[0]
    )
    assert messages_for_conversation(session_factory, escalated_id) == (
        "escalated",
        [("user", "Pending human request")],
    )
    assert messages_for_conversation(session_factory, open_conversation_id) == (
        "open",
        [
            ("user", "What is in stock?"),
            ("assistant", "Inventory question answered."),
        ],
    )


def test_empty_new_question_does_not_change_any_conversation(
    make_client, session_factory
):
    _, escalated_id = create_escalated_conversation(session_factory)
    original_history = messages_for_conversation(session_factory, escalated_id)
    llm = ScriptedLLM([])

    response = make_client(llm).post(
        "/chat",
        json={"phone": PHONE, "message": " \nNEW QUESTION:   "},
    )

    assert response.json()["response"] == NEW_QUESTION_CLARIFICATION
    assert llm.calls == []
    assert counts(session_factory)[1] == 1
    assert messages_for_conversation(session_factory, escalated_id) == original_history


def test_customer_conversation_lock_compiles_to_postgresql_for_update():
    session = Mock()
    session.scalar.return_value = 6

    ConversationRepository(session).lock_customer(6)

    statement = session.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql


def test_conversation_selection_locks_customer_before_read_or_create():
    service = ConversationService(Mock())
    repo = Mock()
    repo.get_latest_active.return_value = None
    repo.add.return_value = Mock(id=11)
    service.repo = repo

    service.get_or_open(6)

    assert repo.method_calls == [
        call.lock_customer(6),
        call.get_latest_active(6),
        call.add(6),
    ]


def test_llm_failure_returns_safe_fallback_and_keeps_user_message(make_client, session_factory):
    class Boom(ScriptedLLM):
        def invoke(self, messages, *a, **k):
            raise RuntimeError("groq down: secret-internal-detail")

    r = make_client(Boom([])).post("/chat", json={"phone": PHONE, "message": "Hi"})
    assert r.status_code == 200 and r.json()["response"] == FALLBACK_REPLY
    assert "secret" not in r.text
    with session_factory() as s:
        assert [m.role for m in s.scalars(select(Message))] == ["user"]


def test_tool_loop_overflow_returns_fallback(make_client):
    llm = ScriptedLLM([tool_call("search_products", {"query": "x"}, f"c{i}") for i in range(50)])
    r = make_client(llm).post("/chat", json={"phone": PHONE, "message": "loop"})
    assert r.json()["response"] == FALLBACK_REPLY


def test_validation(make_client):
    client = make_client(ScriptedLLM([]))
    assert client.post("/chat", json={"phone": "abc", "message": "hi"}).status_code == 422
    assert client.post("/chat", json={"phone": PHONE, "message": "   "}).status_code == 422
    assert client.post("/chat", json={"phone": PHONE, "message": "x" * 2001}).status_code == 422
