from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.core.market_state import MarketSnapshot, TICK_SIZE


class ShooterStatus(str, Enum):
    IDLE = "IDLE"
    TRACKING = "TRACKING"
    WIN = "WIN"
    LOSS = "LOSS"


@dataclass(slots=True)
class ShooterView:
    status: ShooterStatus
    entry_price: Optional[float]
    live_bid: Optional[float]
    pnl_ticks: float
    hold_ms: int
    trades: int
    wins: int
    losses: int
    winrate: float
    avg_hold_ms: float
    avg_pnl_ticks: float


class ShooterEngine:
    def __init__(
        self,
        min_spread_ticks: float = 500.0,
        min_bid_impulse_ticks: float = 150.0,
        impulse_window_ms: int = 100,
        timeout_ms: int = 300,
    ) -> None:
        self._min_spread_ticks = min_spread_ticks
        self._min_bid_impulse_ticks = min_bid_impulse_ticks
        self._impulse_window_ms = impulse_window_ms
        self._timeout_ms = timeout_ms

        self._status = ShooterStatus.IDLE
        self._entry_price: Optional[float] = None
        self._entry_mono: float = 0.0
        self._pnl_ticks = 0.0
        self._hold_ms = 0

        self._prev_bid: Optional[float] = None
        self._prev_mono = 0.0

        self._trades = 0
        self._wins = 0
        self._losses = 0
        self._sum_hold_ms = 0
        self._sum_pnl_ticks = 0.0

    def on_snapshot(self, snapshot: MarketSnapshot) -> ShooterView:
        if self._status == ShooterStatus.TRACKING:
            self._update_tracking(snapshot)
        else:
            self._try_enter(snapshot)

        self._prev_bid = snapshot.bid
        self._prev_mono = snapshot.recv_monotonic
        return self.view(snapshot.bid)

    def view(self, live_bid: Optional[float]) -> ShooterView:
        winrate = (self._wins / self._trades * 100.0) if self._trades else 0.0
        avg_hold = (self._sum_hold_ms / self._trades) if self._trades else 0.0
        avg_pnl = (self._sum_pnl_ticks / self._trades) if self._trades else 0.0
        return ShooterView(
            status=self._status,
            entry_price=self._entry_price,
            live_bid=live_bid,
            pnl_ticks=self._pnl_ticks,
            hold_ms=self._hold_ms,
            trades=self._trades,
            wins=self._wins,
            losses=self._losses,
            winrate=winrate,
            avg_hold_ms=avg_hold,
            avg_pnl_ticks=avg_pnl,
        )

    def _try_enter(self, snapshot: MarketSnapshot) -> None:
        if self._prev_bid is None or self._prev_mono <= 0.0:
            return
        dt_ms = (snapshot.recv_monotonic - self._prev_mono) * 1000.0
        if dt_ms <= 0.0 or dt_ms > self._impulse_window_ms:
            return
        bid_delta_ticks = (snapshot.bid - self._prev_bid) / TICK_SIZE
        if snapshot.spread_ticks < self._min_spread_ticks:
            return
        if bid_delta_ticks < self._min_bid_impulse_ticks:
            return
        self._status = ShooterStatus.TRACKING
        self._entry_price = snapshot.ask
        self._entry_mono = snapshot.recv_monotonic
        self._pnl_ticks = (snapshot.bid - snapshot.ask) / TICK_SIZE
        self._hold_ms = 0

    def _update_tracking(self, snapshot: MarketSnapshot) -> None:
        if self._entry_price is None:
            self._status = ShooterStatus.IDLE
            return
        self._hold_ms = int((snapshot.recv_monotonic - self._entry_mono) * 1000.0)
        self._pnl_ticks = (snapshot.bid - self._entry_price) / TICK_SIZE

        if self._pnl_ticks >= 1.0:
            self._finish_trade(ShooterStatus.WIN)
            return
        if self._hold_ms > self._timeout_ms:
            self._finish_trade(ShooterStatus.LOSS)

    def _finish_trade(self, result: ShooterStatus) -> None:
        self._status = result
        self._trades += 1
        if result == ShooterStatus.WIN:
            self._wins += 1
        else:
            self._losses += 1
        self._sum_hold_ms += self._hold_ms
        self._sum_pnl_ticks += self._pnl_ticks
        self._entry_price = None
        self._entry_mono = 0.0
