# """Application entry point: app creation, routers, health. No business logic here."""
# import logging
# from collections.abc import AsyncIterator
# from contextlib import asynccontextmanager
# from functools import lru_cache

# from fastapi import Depends, FastAPI
# from langchain_core.language_models import BaseChatModel
# from sqlalchemy.orm import Session

# from app.agents.sales_agent import build_llm
# from app.config import Settings, get_settings
# from app.database.connection import get_session
# from app.schemas.chat import ChatRequest, ChatResponse
# from app.services.chat_service import ChatService

# logger = logging.getLogger(__name__)


# @lru_cache
# def get_llm() -> BaseChatModel:
#     return build_llm(get_settings())


# @asynccontextmanager
# async def lifespan(app: FastAPI) -> AsyncIterator[None]:
#     settings = get_settings()
#     logging.basicConfig(
#         level=settings.log_level.upper(),
#         format="%(asctime)s %(levelname)s %(name)s %(message)s",
#     )
#     logger.info("startup app=%s env=%s", settings.app_name, settings.app_env)
#     yield


# app = FastAPI(title=get_settings().app_name, lifespan=lifespan)


# @app.get("/health")
# def health() -> dict[str, str]:
#     return {"status": "ok"}


# # Sync endpoint on purpose: SQLAlchemy + LangGraph invoke are blocking, FastAPI runs this in a threadpool.
# @app.post("/chat", response_model=ChatResponse)
# def chat(
#     request: ChatRequest,
#     session: Session = Depends(get_session),
#     llm: BaseChatModel = Depends(get_llm),
#     settings: Settings = Depends(get_settings),
# ) -> ChatResponse:
#     reply = ChatService(session, llm, settings).handle_message(request.phone, request.message)
#     return ChatResponse(response=reply)


"""Application entry point: app creation, routers, and health checks."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.connection import get_session
from app.dependencies import get_llm
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.whatsapp.webhook import router as whatsapp_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    logger.info(
        "startup app=%s env=%s",
        settings.app_name,
        settings.app_env,
    )

    yield


app = FastAPI(
    title=get_settings().app_name,
    lifespan=lifespan,
)

# WhatsApp Cloud API webhook.
app.include_router(whatsapp_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Sync endpoint on purpose:
# SQLAlchemy + LangGraph invoke are blocking operations, so FastAPI
# executes this endpoint in its threadpool.
@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    session: Session = Depends(get_session),
    llm=Depends(get_llm),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    reply = ChatService(
        session,
        llm,
        settings,
    ).handle_message(
        request.phone,
        request.message,
    )

    return ChatResponse(response=reply)