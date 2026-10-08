"""Preflight for the live WhatsApp test: `python -m scripts.check_whatsapp_setup [--webhook-url https://<ngrok>/webhook]`.

Checks config presence, database + tables, the Meta access token / phone number id, and (optionally) the public
webhook verification handshake. Secrets are never printed. Exit code 1 if any check fails."""
import argparse
import secrets
import sys
from dataclasses import dataclass

import httpx

from app.whatsapp.settings import WhatsAppSettings

REQUIRED_TABLES = {"customers", "products", "conversations", "messages", "leads", "processed_events"}
PHONE_FIELDS = "display_phone_number,verified_name,quality_rating,name_status,status"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def check_config(wa: WhatsAppSettings) -> list[CheckResult]:
    checks = [
        ("WHATSAPP_ACCESS_TOKEN", wa.whatsapp_access_token is not None, "set WHATSAPP_ACCESS_TOKEN"),
        ("WHATSAPP_PHONE_NUMBER_ID", bool(wa.whatsapp_phone_number_id), "set the Phone number ID (not the phone number)"),
        ("WHATSAPP_VERIFY_TOKEN", wa.whatsapp_verify_token is not None, "any string you choose; same value goes in Meta"),
        ("WHATSAPP_APP_SECRET", wa.whatsapp_app_secret is not None, "empty = unsigned requests accepted (CLAUDE.md §69)"),
    ]
    return [CheckResult(f"config {name}", ok, "set" if ok else hint) for name, ok, hint in checks]


def check_database(session_factory) -> list[CheckResult]:
    from sqlalchemy import func, inspect, select, text

    from app.database.models import Product

    results: list[CheckResult] = []
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
            results.append(CheckResult("database connection", True))
            tables = set(inspect(session.get_bind()).get_table_names())
            missing = sorted(REQUIRED_TABLES - tables)
            results.append(CheckResult(
                "database tables", not missing,
                "all present" if not missing else f"missing {missing} -> python -m scripts.create_tables",
            ))
            if "products" in tables:
                count = session.scalar(select(func.count()).select_from(Product).where(Product.active.is_(True)))
                results.append(CheckResult("active products", bool(count), f"{count} active" if count else "none -> python -m scripts.seed_database"))
    except Exception as exc:  # never print the exception text: it can contain connection details
        hint = ""
        if isinstance(exc, ModuleNotFoundError):
            hint = " (driver missing: use DATABASE_URL=postgresql+psycopg2://... with psycopg2-binary installed)"
        results.append(CheckResult("database connection", False, f"{type(exc).__name__}{hint}"))
    return results


def _meta_error(response: httpx.Response) -> tuple[int | None, str]:
    try:
        err = response.json().get("error", {})
        return err.get("code"), str(err.get("message", ""))[:160]
    except (ValueError, AttributeError):
        return None, ""


def check_meta_number(wa: WhatsAppSettings, transport: httpx.BaseTransport | None = None) -> CheckResult:
    if wa.whatsapp_access_token is None or not wa.whatsapp_phone_number_id:
        return CheckResult("meta phone number", False, "skipped: token / phone number id missing")
    url = f"https://graph.facebook.com/{wa.whatsapp_api_version}/{wa.whatsapp_phone_number_id}"
    headers = {"Authorization": f"Bearer {wa.whatsapp_access_token.get_secret_value()}"}
    try:
        with httpx.Client(timeout=wa.whatsapp_timeout_seconds, transport=transport) as http:
            response = http.get(url, params={"fields": PHONE_FIELDS}, headers=headers)
            if response.status_code == 400:  # a field may be unavailable for this number type: retry minimal
                response = http.get(url, params={"fields": "display_phone_number,verified_name"}, headers=headers)
    except httpx.TransportError as exc:
        return CheckResult("meta phone number", False, f"network error: {type(exc).__name__}")
    if response.is_success:
        data = response.json()
        shown = ", ".join(f"{k}={data[k]}" for k in ("display_phone_number", "verified_name", "status", "name_status", "quality_rating") if k in data)
        return CheckResult("meta phone number", True, shown)
    code, message = _meta_error(response)
    hint = {
        190: "access token invalid or expired (temporary tokens last ~24h: use a System User token)",
        100: "phone number id wrong, or the token lacks whatsapp_business_management/messaging permission",
        10: "token lacks permission for this WhatsApp Business Account",
    }.get(code, "")
    return CheckResult("meta phone number", False, f"HTTP {response.status_code} code={code} {hint or message}")


def check_webhook_handshake(url: str, wa: WhatsAppSettings, transport: httpx.BaseTransport | None = None) -> CheckResult:
    if wa.whatsapp_verify_token is None:
        return CheckResult("webhook handshake", False, "skipped: WHATSAPP_VERIFY_TOKEN missing")
    challenge = secrets.token_hex(8)
    params = {"hub.mode": "subscribe", "hub.verify_token": wa.whatsapp_verify_token.get_secret_value(), "hub.challenge": challenge}
    try:
        with httpx.Client(timeout=10, transport=transport, follow_redirects=False) as http:
            response = http.get(url, params=params, headers={"ngrok-skip-browser-warning": "1"})
    except httpx.TransportError as exc:
        return CheckResult("webhook handshake", False, f"unreachable: {type(exc).__name__} (is uvicorn + ngrok running?)")
    if response.status_code == 200 and response.text == challenge:
        return CheckResult("webhook handshake", True, "challenge echoed")
    if response.status_code == 403:
        return CheckResult("webhook handshake", False, "403: server's WHATSAPP_VERIFY_TOKEN differs from .env (restart uvicorn after editing .env)")
    return CheckResult("webhook handshake", False, f"HTTP {response.status_code}, body did not echo the challenge")


def run_checks(wa: WhatsAppSettings, session_factory=None, webhook_url: str | None = None) -> list[CheckResult]:
    results = check_config(wa)
    if session_factory is not None:
        results += check_database(session_factory)
    results.append(check_meta_number(wa))
    if webhook_url:
        results.append(check_webhook_handshake(webhook_url, wa))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--webhook-url", help="public URL, e.g. https://abc.ngrok-free.app/webhook")
    parser.add_argument("--skip-db", action="store_true")
    args = parser.parse_args(argv)

    from app.database.connection import get_session_factory
    from app.whatsapp.settings import get_whatsapp_settings

    results = run_checks(get_whatsapp_settings(), None if args.skip_db else get_session_factory(), args.webhook_url)
    for r in results:
        print(f"[{'PASS' if r.ok else 'FAIL'}] {r.name}" + (f" - {r.detail}" if r.detail else ""))
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
