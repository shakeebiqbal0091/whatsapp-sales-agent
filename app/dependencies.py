"""Shared FastAPI dependencies.

Keeping shared dependency providers outside app.main prevents circular
imports when feature routers import the same dependencies.
"""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.agents.sales_agent import build_llm
from app.config import get_settings


@lru_cache
def get_llm() -> BaseChatModel:
    """Return the cached application LLM instance."""
    return build_llm(get_settings())