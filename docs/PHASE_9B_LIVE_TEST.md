# Phase 9b — live WhatsApp test runbook

CLAUDE.md §31: never debug LLM, DB, FastAPI, ngrok and Meta at the same time. Pass each stage before the next.

## Stage 0 — environment (once)

```env
# .env  (explicit driver: with SQLAlchemy 2.1, plain postgresql:// means psycopg v3, but requirements.txt installs psycopg2)
DATABASE_URL=postgresql+psycopg2://postgres:<password>@localhost:5432/whatsapp_sales_agent
WHATSAPP_ACCESS_TOKEN=            # System User token (permanent). Temporary dashboard tokens expire in ~24 h.
WHATSAPP_PHONE_NUMBER_ID=         # numeric "Phone number ID" in API Setup, NOT the phone number
WHATSAPP_VERIFY_TOKEN=            # any string you choose
WHATSAPP_APP_SECRET=              # App settings > Basic > App secret
```
```powershell
python -m scripts.create_tables      # all 6 tables incl. processed_events
python -m scripts.seed_database      # products
```

## Stage 1 — real model, no WhatsApp (needs GROQ_API_KEY)

```powershell
python -m scripts.eval_conversations          # 17 conversations from CLAUDE.md §33/§34, isolated in-memory DB
```
Read the printed replies, not just PASS/FAIL. Fix prompts/tools until all pass on 2-3 consecutive runs.

## Stage 2 — preflight

```powershell
python -m scripts.check_whatsapp_setup
```
All PASS = config set, DB reachable with all tables, token valid for the phone number id.

## Stage 3 — public URL + handshake

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
ngrok http 8000
python -m scripts.check_whatsapp_setup --webhook-url https://<ngrok-domain>/webhook
```
In Meta: WhatsApp > Configuration > Webhook: callback URL, verify token, then subscribe to the `messages` field.
The app must also be subscribed to your WhatsApp Business Account (Webhooks page, `whatsapp_business_account`).

## Stage 4 — signed inbound without a phone

```powershell
python -m scripts.simulate_whatsapp_webhook --from +92XXXXXXXXXX --text "Do you have a wireless keyboard?"
python -m scripts.simulate_whatsapp_webhook --from +92XXXXXXXXXX --text "hi" --twice
```
Use your own WhatsApp number: the reply is really sent. `--twice` must produce ONE reply and a
"duplicate webhook event ignored" log line.

## Stage 5 — real phone

Message the business number from a DIFFERENT WhatsApp account (a number cannot message itself).

## Acceptance (CLAUDE.md §68, WhatsApp + API blocks)

- [ ] GET /webhook verification accepted by Meta
- [ ] Incoming message appears in logs (`webhook received messages=1`)
- [ ] Customer + conversation + messages rows created (check `customers`, `messages`)
- [ ] Reply arrives on the phone; price and stock match the database
- [ ] "I want to talk to a human" -> escalation, later messages get the fixed handoff reply
- [ ] Duplicate delivery produces one reply
- [ ] Bad signature -> 403 (curl without the header)

## Troubleshooting

| Symptom | Cause |
|---|---|
| Every customer gets the generic "trouble processing" reply | `processed_events` table missing -> `python -m scripts.create_tables` |
| `ModuleNotFoundError: psycopg` | URL must be `postgresql+psycopg2://...` |
| Meta "callback URL or verify token couldn't be validated" | uvicorn/ngrok down, token mismatch, or .env edited without restarting uvicorn |
| Browser shows ngrok "Visit Site" and inspector has no requests | Free ngrok interstitial (not an app failure). Click **Visit Site** once, or send header `ngrok-skip-browser-warning: 1`. Meta webhook clients skip this. Callback URL must be `https://<ngrok-domain>/webhook`. |
| Simulator works, real messages never arrive | not subscribed to `messages`, app not subscribed to the WABA, or app still in Development mode |
| Logs: `whatsapp send rejected status=401` | token expired/invalid (code 190) |
| Logs: `status=400` on send | wrong phone number id, or recipient outside the 24 h window (free-form replies only work within 24 h of the customer's last message) |
| 403 on every POST | `WHATSAPP_APP_SECRET` is not the App secret of the app that owns the number |
