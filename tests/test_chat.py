from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from app.agents.sales_agent import FALLBACK_REPLY
from app.database.models import Conversation, Customer, Message
from app.services.chat_service import HANDOFF_REPLY
from tests.conftest import ScriptedLLM, tool_call

PHONE = "+92 300 1234567"


def counts(session_factory):
    with session_factory() as s:
        return (
            s.scalar(select(func.count(Customer.id))),
            s.scalar(select(func.count(Conversation.id))),
            s.scalar(select(func.count(Message.id))),
        )


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
