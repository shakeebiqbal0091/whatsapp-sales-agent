# WhatsApp Sales Agent

AI-powered WhatsApp sales agent (Version 0.1) built with FastAPI, LangGraph, SQLAlchemy/PostgreSQL and Groq.
The LLM interprets and communicates; the database is the source of truth for products, prices and stock.
See `CLAUDE.md` for architecture rules and the roadmap.

## Status

| Phase | Status |
|---|---|
| 1-8: setup, config, DB, tools, agent, LangGraph, FastAPI, local `/chat` | done, 27 tests |
| 9: WhatsApp webhook + outbound client (`app/whatsapp/`) | next |
| 10-12: dedupe/idempotency, evals, hardening | later |

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # set GROQ_API_KEY and DATABASE_URL
python -m scripts.seed_database
uvicorn app.main:app --reload --port 8000
```

## Try it

```powershell
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" `
  -d '{"phone":"+923001234567","message":"Do you have a wireless keyboard?"}'
```

## Endpoints

- `GET /health`
- `POST /chat` `{phone, message}` -> `{response}`
- `GET|POST /webhook` (Phase 9)

## Tests

```powershell
pytest
```

Tests use SQLite in memory and a scripted fake LLM, so they verify wiring, grounding data flow,
persistence and failure handling, not the real model's judgement. Run the conversations in
CLAUDE.md section 33 against a real Groq key before connecting WhatsApp.

## Behaviour notes

- Customer = WhatsApp phone number, normalised to `+<digits>`; one active conversation per customer.
- `customer_id` / `conversation_id` are bound server-side into tools; the LLM cannot pass them.
- Order intent: `create_lead` then `escalate_to_human` (no order tool until v0.4).
- Once escalated, the bot sends a fixed handoff reply and stops calling the LLM. Nothing resets
  this status yet; a human-reply/close mechanism is needed (see Next).
- Agent/LLM failure: customer gets a generic fallback; the real error is logged; the user message is still saved.
