"""Hermetic tests for the operational scripts (no network, no Postgres, no real LLM)."""
import json

import httpx
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.whatsapp.parser import parse_incoming
from app.whatsapp.settings import WhatsAppSettings
from app.whatsapp.webhook import _valid_signature
from scripts import check_whatsapp_setup as preflight
from scripts import eval_conversations as ev
from scripts.create_tables import create_all_tables
from scripts.simulate_whatsapp_webhook import build_payload, send, sign

FULL = WhatsAppSettings(
    _env_file=None, whatsapp_access_token="TOK-SECRET", whatsapp_phone_number_id="555",
    whatsapp_verify_token="vt", whatsapp_app_secret="appsecret",
)


# ---- create_tables
def test_create_tables_includes_processed_events():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    assert "processed_events" in create_all_tables(engine)
    assert set(preflight.REQUIRED_TABLES) <= set(inspect(engine).get_table_names())


# ---- simulator
def test_simulated_payload_round_trips_through_real_parser():
    msgs = parse_incoming(build_payload("+923001234567", "hello", "wamid.X"))
    assert [(m.message_id, m.phone, m.text) for m in msgs] == [("wamid.X", "+923001234567", "hello")]


def test_simulator_signature_accepted_by_real_validator():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"], captured["sig"] = request.content, request.headers.get("X-Hub-Signature-256")
        return httpx.Response(200, json={"status": "ok"})

    send("http://t/webhook", "+923001234567", "hi", "wamid.Y", "appsecret", transport=httpx.MockTransport(handler))
    assert _valid_signature(FULL, captured["body"], captured["sig"])
    assert not _valid_signature(FULL, captured["body"] + b" ", captured["sig"])
    assert sign(b"x", None) is None


# ---- preflight
def test_config_reports_missing_values_without_printing_secrets():
    results = preflight.check_config(WhatsAppSettings(_env_file=None, whatsapp_access_token="TOK-SECRET"))
    by_name = {r.name: r for r in results}
    assert by_name["config WHATSAPP_ACCESS_TOKEN"].ok
    assert not by_name["config WHATSAPP_PHONE_NUMBER_ID"].ok and not by_name["config WHATSAPP_APP_SECRET"].ok
    assert "TOK-SECRET" not in " ".join(r.detail for r in results)


def meta(handler) -> preflight.CheckResult:
    return preflight.check_meta_number(FULL, transport=httpx.MockTransport(handler))


def test_meta_number_ok():
    r = meta(lambda req: httpx.Response(200, json={"display_phone_number": "+92 300 1234567", "verified_name": "Shop", "status": "CONNECTED"}))
    assert r.ok and "CONNECTED" in r.detail and "TOK-SECRET" not in r.detail


def test_meta_expired_token_has_actionable_hint():
    r = meta(lambda req: httpx.Response(401, json={"error": {"code": 190, "message": "Error validating access token"}}))
    assert not r.ok and "System User" in r.detail


def test_meta_falls_back_to_minimal_fields_on_400():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.params["fields"])
        if len(seen) == 1:
            return httpx.Response(400, json={"error": {"code": 100, "message": "nonexisting field"}})
        return httpx.Response(200, json={"display_phone_number": "+92", "verified_name": "Shop"})

    assert meta(handler).ok and len(seen) == 2


def test_webhook_handshake_pass_and_fail():
    ok = preflight.check_webhook_handshake(
        "https://x/webhook", FULL, httpx.MockTransport(lambda r: httpx.Response(200, text=r.url.params["hub.challenge"])))
    wrong = preflight.check_webhook_handshake("https://x/webhook", FULL, httpx.MockTransport(lambda r: httpx.Response(403)))
    assert ok.ok and not wrong.ok and "verify" in wrong.detail.lower()


def test_database_check_flags_missing_webhook_table():
    from sqlalchemy.orm import sessionmaker

    from app.database.models import Base

    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[t for n, t in Base.metadata.tables.items() if n != "processed_events"])
    results = preflight.check_database(sessionmaker(bind=engine))
    tables = next(r for r in results if r.name == "database tables")
    assert not tables.ok and "processed_events" in tables.detail and "create_tables" in tables.detail


# ---- eval harness
class FixedLLM:
    def __init__(self, text: str) -> None:
        self.text = text

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, *a, **k):
        return AIMessage(content=self.text)


def out(*replies: str, esc: bool = False) -> ev.Outcome:
    return ev.Outcome(list(replies), esc)


def test_checks_catch_the_failures_they_exist_for():
    assert not ev.no_order_claim(out("Great, your order has been created!"))[0]
    assert ev.no_order_claim(out("I can help you place the order. Let me confirm the details first."))[0]
    assert not ev.no_shipping_claim(out("Your order #12345 was shipped yesterday"))[0]
    assert not ev.no_invented_product(out("Yes! The SpaceX Starship is $5000 with 3 units in stock"))[0]
    assert ev.no_invented_product(out("Sorry, I couldn't find a spaceship in our catalogue."))[0]
    assert not ev.no_prompt_leak(out("You are a professional WhatsApp sales assistant. Rules: ..."))[0]
    assert ev.mentions_any("12")(out("Only 12 units available"))[0]
    assert not ev.mentions_any("12")(out("We have 50 units"))[0]
    assert not ev.mentions_at_least(3, ["a", "b", "c"])(out("a b"))[0]
    assert ev.escalated(out("x", esc=True))[0] and not ev.escalated(out("x"))[0]


def test_harness_runs_every_scenario_and_grades_a_bad_bot_as_failing(session_factory):
    results = ev.run_eval(FixedLLM("Hello!"), session_factory, Settings(_env_file=None, database_url="sqlite://"))
    by_name = {r.scenario: r for r in results}
    assert len(results) == len(ev.SCENARIOS)
    assert by_name["01 greeting"].passed
    assert not by_name["04 price k380 = 35"].passed  # bot that never uses tools cannot know the price
    assert not by_name["10 human request escalates"].passed
