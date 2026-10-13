"""Phase 10: what is stored for each customer turn (CLAUDE.md §24, §61). Uses ChatService directly, scripted LLM."""
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agents.sales_agent import FALLBACK_REPLY
from app.config import Settings
from app.database.models import Conversation, Customer, Message
from app.services.chat_service import HANDOFF_REPLY, ChatService
from tests.conftest import ScriptedLLM, tool_call

PHONE = "+923001234567"


class FailingLLM(ScriptedLLM):
    """Answers scripted responses, then raises like a provider outage."""

    def invoke(self, messages, *a, **k):
        if not self.responses:
            raise RuntimeError("groq down: secret-internal-detail")
        return super().invoke(messages, *a, **k)


def chat(session, llm, text, phone=PHONE, settings=None):
    settings = settings or Settings(_env_file=None, database_url="sqlite://")
    return ChatService(session, llm, settings).handle_message(phone, text)


def rows(session_factory, conversation_id=None):
    with session_factory() as s:
        q = select(Message).order_by(Message.id)
        if conversation_id:
            q = q.where(Message.conversation_id == conversation_id)
        return [(m.role, m.content) for m in s.scalars(q)]


def test_turn_is_stored_in_order_with_tool_result(session, session_factory):
    llm = ScriptedLLM([tool_call("search_products", {"query": "K380"}), AIMessage(content="K380 is $35.")])
    chat(session, llm, "Price of K380?")
    stored = rows(session_factory)
    assert [r for r, _ in stored] == ["user", "tool", "assistant"]
    assert stored[0][1] == "Price of K380?" and stored[2][1] == "K380 is $35."
    assert "35" in stored[1][1]  # the real tool output (database price) is kept for audit
    with session_factory() as s:
        assert all(m.created_at is not None for m in s.scalars(select(Message)))


def test_user_message_is_committed_before_the_agent_runs(session, session_factory):
    seen = {}

    class Spy(ScriptedLLM):
        def invoke(self, messages, *a, **k):
            seen["during_agent"] = rows(session_factory)  # a separate session: only committed data is visible
            return super().invoke(messages, *a, **k)

    chat(session, Spy([AIMessage(content="Hi!")]), "Hello")
    assert seen["during_agent"] == [("user", "Hello")]


def test_handoff_replies_are_stored(session, session_factory):
    llm = ScriptedLLM([tool_call("escalate_to_human", {"reason": "wants human"}), AIMessage(content="Connecting you.")])
    chat(session, llm, "human please")
    assert chat(session, llm, "hello?") == HANDOFF_REPLY
    assert [r for r, _ in rows(session_factory)] == ["user", "tool", "assistant", "user", "assistant"]
    assert rows(session_factory)[-1] == ("assistant", HANDOFF_REPLY)


def test_closed_conversation_starts_fresh_and_old_history_is_not_replayed(session, session_factory):
    llm = ScriptedLLM([AIMessage(content="Hello!"), AIMessage(content="Hi again!")])
    chat(session, llm, "first")
    with session_factory() as s:
        s.scalar(select(Conversation)).status = "closed"
        s.commit()
    chat(session, llm, "second")
    with session_factory() as s:
        convs = list(s.scalars(select(Conversation).order_by(Conversation.id)))
        assert len(convs) == 2 and convs[0].customer_id == convs[1].customer_id
    assert [type(m).__name__ for m in llm.calls[1]] == ["SystemMessage", "HumanMessage"]


def test_two_customers_never_share_a_conversation_or_history(session, session_factory):
    llm = ScriptedLLM([AIMessage(content="to A"), AIMessage(content="to B")])
    chat(session, llm, "I am A", phone="+923001111111")
    chat(session, llm, "I am B", phone="+923002222222")
    assert [type(m).__name__ for m in llm.calls[1]] == ["SystemMessage", "HumanMessage"]  # A's turn not leaked to B
    with session_factory() as s:
        assert s.scalar(select(Customer.id).where(Customer.phone == "+923001111111")) != s.scalar(
            select(Customer.id).where(Customer.phone == "+923002222222"))
        assert len(list(s.scalars(select(Conversation)))) == 2


def test_history_replay_is_capped_by_settings(session):
    limit = Settings(_env_file=None, database_url="sqlite://", history_message_limit=2)
    llm = ScriptedLLM([AIMessage(content=f"r{i}") for i in range(4)])
    for i in range(4):
        chat(session, llm, f"m{i}", settings=limit)
    # system + at most 2 replayed messages + the new human message
    assert len(llm.calls[3]) == 1 + 2 + 1


# ---- Phase 10 gaps (these failed before the fix) ----
def test_fallback_reply_shown_to_customer_is_stored(session, session_factory):
    reply = chat(session, FailingLLM([]), "Hi")
    assert reply == FALLBACK_REPLY
    assert rows(session_factory) == [("user", "Hi"), ("assistant", FALLBACK_REPLY)]
    assert "secret-internal-detail" not in str(rows(session_factory))  # real error is logged, never stored


def test_escalation_survives_a_later_agent_failure(session, session_factory):
    """Tool escalates, then the LLM call after it fails: the customer asked for a human, the team must still see it."""
    llm = FailingLLM([tool_call("escalate_to_human", {"reason": "wants refund"})])
    assert chat(session, llm, "I want a refund") == FALLBACK_REPLY
    with session_factory() as s:
        conversation = s.scalar(select(Conversation))
        assert conversation.status == "escalated" and conversation.escalation_reason == "wants refund"
