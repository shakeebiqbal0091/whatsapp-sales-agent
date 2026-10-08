"""Send a correctly signed, Meta-shaped inbound message to your webhook (no phone needed).

    python -m scripts.simulate_whatsapp_webhook --from +923001234567 --text "Do you have a K380?"
    python -m scripts.simulate_whatsapp_webhook --from +923001234567 --text "hi" --twice   # duplicate-delivery test

The agent's reply is REALLY sent through Meta to --from, so use your own WhatsApp number. Unreachable /
unregistered numbers just produce a logged send failure server-side (the webhook still returns 200)."""
import argparse
import hashlib
import hmac
import json
import sys
import time
import uuid

import httpx


def build_payload(from_phone: str, text: str, message_id: str) -> dict:
    digits = from_phone.lstrip("+")
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "SIMULATED",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "0", "phone_number_id": "0"},
                    "contacts": [{"profile": {"name": "Simulator"}, "wa_id": digits}],
                    "messages": [{"from": digits, "id": message_id, "timestamp": str(int(time.time())),
                                  "type": "text", "text": {"body": text}}],
                },
            }],
        }],
    }


def sign(body: bytes, app_secret: str | None) -> str | None:
    if not app_secret:
        return None
    return "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()


def send(url: str, from_phone: str, text: str, message_id: str, app_secret: str | None,
         transport: httpx.BaseTransport | None = None) -> httpx.Response:
    body = json.dumps(build_payload(from_phone, text, message_id), separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "ngrok-skip-browser-warning": "1"}
    signature = sign(body, app_secret)
    if signature:
        headers["X-Hub-Signature-256"] = signature
    with httpx.Client(timeout=15, transport=transport) as http:
        return http.post(url, content=body, headers=headers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="from_phone", required=True, help="sender, e.g. +923001234567")
    parser.add_argument("--text", default="Do you have a wireless keyboard?")
    parser.add_argument("--url", default="http://localhost:8000/webhook")
    parser.add_argument("--twice", action="store_true", help="deliver the same message id twice (dedupe test)")
    args = parser.parse_args(argv)

    from app.whatsapp.settings import get_whatsapp_settings

    secret = get_whatsapp_settings().whatsapp_app_secret
    app_secret = secret.get_secret_value() if secret else None
    if app_secret is None:
        print("note: WHATSAPP_APP_SECRET not set; sending unsigned")

    message_id = f"wamid.SIM.{uuid.uuid4().hex}"
    deliveries = 2 if args.twice else 1
    for n in range(1, deliveries + 1):
        response = send(args.url, args.from_phone, args.text, message_id, app_secret)
        print(f"delivery {n}: HTTP {response.status_code} {response.text[:120]}")
        if response.status_code != 200:
            return 1
    print(f"message id {message_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
