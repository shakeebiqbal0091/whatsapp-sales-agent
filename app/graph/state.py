from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class SalesState(TypedDict):
    messages: Annotated[list, add_messages]
    customer_id: int | None
    phone_number: str | None
    conversation_id: int | None
