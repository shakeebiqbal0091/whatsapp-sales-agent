import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database.models import Base
from app.main import app, get_llm
from app.database.connection import get_session
from scripts.seed_products import seed_products


class ScriptedLLM:
    """Stands in for ChatGroq: replays a fixed list of AIMessages and records what it was sent."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.calls: list[list] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, *args, **kwargs) -> AIMessage:
        self.calls.append(list(messages))
        return self.responses.pop(0)


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, database_url="sqlite://")


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        seed_products(s)
    yield factory
    engine.dispose()


@pytest.fixture
def session(session_factory) -> Session:
    with session_factory() as s:
        yield s


@pytest.fixture
def make_client(session_factory):
    """Factory: make_client(ScriptedLLM) -> TestClient wired to the in-memory DB."""

    def _make(llm: ScriptedLLM) -> TestClient:
        def _session():
            with session_factory() as s:
                yield s

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_llm] = lambda: llm
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()
