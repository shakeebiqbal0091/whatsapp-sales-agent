"""GET/POST /webhook. Verify, validate, acknowledge quickly, then process messages."""
import hashlib
import hmac
import json
import logging
from functools import lru_cache

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from langchain_core.language_models import BaseChatModel
from sqlalchemy.orm import Session, sessionmaker

from app.agents.sales_agent import FALLBACK_REPLY
from app.config import Settings, get_settings
from app.database.connection import get_session_factory
from app.database.repositories.event_repository import EventRepository
from app.dependencies import get_llm
from app.services.chat_service import ChatService
from app.whatsapp.client import WhatsAppClient
from app.whatsapp.parser import IncomingMessage, parse_incoming
from app.whatsapp.rate_limit import RATE_LIMIT_REPLY, Decision, get_rate_limiter
from app.whatsapp.settings import WhatsAppSettings, get_whatsapp_settings
from app.whatsapp.speech import SpeechError, synthesize_speech, transcribe_audio

logger = logging.getLogger(__name__)
router = APIRouter()
AUDIO_FAILURE_REPLY = "Sorry, I couldn't understand that voice note. Please try again or send a text message."


@lru_cache
def get_whatsapp_client() -> WhatsAppClient:
    return WhatsAppClient(get_whatsapp_settings())


def _valid_signature(wa: WhatsAppSettings, body: bytes, header: str | None) -> bool:
    secret = wa.whatsapp_app_secret
    if secret is None:
        logger.warning("WHATSAPP_APP_SECRET is not configured; signature validation is disabled for this request")
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.get("/webhook")
def verify_webhook(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
    wa: WhatsAppSettings = Depends(get_whatsapp_settings),
) -> PlainTextResponse:
    expected = wa.whatsapp_verify_token
    if (
        mode == "subscribe" and challenge is not None and token is not None and expected is not None
        and hmac.compare_digest(token.encode(), expected.get_secret_value().encode())
    ):
        logger.info("webhook verified")
        return PlainTextResponse(challenge)
    logger.warning("webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background: BackgroundTasks,
    wa: WhatsAppSettings = Depends(get_whatsapp_settings),
    settings: Settings = Depends(get_settings),
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    llm: BaseChatModel = Depends(get_llm),
    client: WhatsAppClient = Depends(get_whatsapp_client),
) -> dict[str, str]:
    body = await request.body()
    if not _valid_signature(wa, body, request.headers.get("X-Hub-Signature-256")):
        logger.warning("webhook rejected: bad signature")
        raise HTTPException(status_code=403, detail="Invalid signature")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    messages = parse_incoming(payload)
    logger.info("webhook received messages=%d", len(messages))
    for message in messages:
        background.add_task(process_message, message, session_factory, llm, settings, client)
    return {"status": "ok"}


def _handle_sync(
    message: IncomingMessage,
    session_factory: sessionmaker[Session],
    llm: BaseChatModel,
    settings: Settings,
    *,
    already_claimed: bool = False,
) -> str | None:
    """Blocking part: dedupe + agent turn."""
    if not message.text:
        return None

    with session_factory() as session:
        if not already_claimed and not EventRepository(session).claim(message.message_id):
            logger.info("duplicate webhook event ignored id=%s", message.message_id)
            return None

        return ChatService(session, llm, settings).handle_message(
            message.phone, message.text
        )

def _claim_event(
    message_id: str,
    session_factory: sessionmaker[Session],
) -> bool:
    """Claim a message ID before expensive audio processing."""
    with session_factory() as session:
        return EventRepository(session).claim(message_id)


async def process_message(
    message: IncomingMessage,
    session_factory: sessionmaker[Session],
    llm: BaseChatModel,
    settings: Settings,
    client: WhatsAppClient,
) -> None:
    decision = get_rate_limiter().check(message.phone)
    if decision is not Decision.ALLOW:
        logger.warning("rate limited decision=%s", decision.value)
        if decision is Decision.NOTIFY:
            await client.send_text(message.phone, RATE_LIMIT_REPLY)
        return

    is_audio = message.message_type == "audio"
    if is_audio:
        claimed = await run_in_threadpool(
            _claim_event,
            message.message_id,
            session_factory,
        )
        if not claimed:
            logger.info(
                "duplicate audio webhook event ignored id=%s",
                message.message_id,
            )
            return
            
    effective_message = message
    if is_audio:
        if not message.media_id:
            await client.send_text(message.phone, AUDIO_FAILURE_REPLY)
            return
        downloaded = await client.download_media(message.media_id)
        if downloaded is None:
            await client.send_text(message.phone, AUDIO_FAILURE_REPLY)
            return
        audio_bytes, mime_type = downloaded
        suffix = ".ogg" if "ogg" in mime_type.lower() else ".audio"
        try:
            transcript = await transcribe_audio(audio_bytes, f"voice-note{suffix}", mime_type, settings)
        except SpeechError:
            logger.warning("voice-note transcription unavailable id=%s", message.message_id)
            await client.send_text(message.phone, AUDIO_FAILURE_REPLY)
            return
        except Exception:
            logger.exception("unexpected voice-note transcription error id=%s", message.message_id)
            await client.send_text(message.phone, AUDIO_FAILURE_REPLY)
            return
        effective_message = message.model_copy(update={"text": transcript})

    try:
        reply = await run_in_threadpool(
    _handle_sync,
    effective_message,
    session_factory,
    llm,
    settings,
    already_claimed=is_audio,
)
    except Exception:
        logger.exception("webhook processing failure id=%s", message.message_id)
        reply = FALLBACK_REPLY

    if reply is None:
        return

    if is_audio:
        try:
            reply_audio = await synthesize_speech(reply, settings)
            if await client.send_audio(message.phone, reply_audio):
                return
            logger.warning("voice reply delivery failed; falling back to text id=%s", message.message_id)
        except Exception:
            logger.exception("voice reply generation failed; falling back to text id=%s", message.message_id)

    await client.send_text(message.phone, reply)
