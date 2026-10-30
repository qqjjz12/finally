"""Data models for market data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds
    # Baseline for daily change %: simulator seed price or Massive previous close
    reference_price: float | None = None

    @property
    def daily_change_percent(self) -> float | None:
        """Percentage change vs. reference_price, or None if no reference is known."""
        if not self.reference_price:
            return None
        return round((self.price - self.reference_price) / self.reference_price * 100, 4)

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat'."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "reference_price": self.reference_price,
            "timestamp": self.timestamp,
            "daily_change_percent": self.daily_change_percent,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
        }
