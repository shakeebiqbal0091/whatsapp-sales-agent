"""WhatsApp-enabled entry point: reuses the existing FastAPI app and adds the /webhook routes.

Run with: uvicorn app.main_whatsapp:app --reload --port 8000
(To make this permanent later, move the two lines below into app/main.py and delete this file.)
"""
from app.database import event_models  # noqa: F401  (registers processed_events on Base.metadata)
from app.main import app
from app.whatsapp.webhook import router as webhook_router

app.include_router(webhook_router)
