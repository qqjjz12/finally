"""Pydantic models for the LLM structured output."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TradeAction(BaseModel):
    type: Literal["trade"] = "trade"
    ticker: str
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0)


class WatchlistAction(BaseModel):
    type: Literal["watchlist"] = "watchlist"
    ticker: str
    action: Literal["add", "remove"]
    confirmed: bool = False


Action = Annotated[Union[TradeAction, WatchlistAction], Field(discriminator="type")]


class LLMResponse(BaseModel):
    message: str
    actions: list[Action] = Field(default_factory=list)
