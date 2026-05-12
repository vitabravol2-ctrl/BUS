from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.core.market_state import MarketSnapshot, TICK_SIZE


class ShooterStatus(str, Enum):
    IDLE = "IDLE"
    WAIT_FILL = "WAIT_FILL"
    FILLED = "FILLED"
    WIN = "WIN"
    LOSS = "LOSS"
    TIMEOUT = "TIMEOUT"


@dataclass(slots=True)
class ShooterView:
    status: ShooterStatus
    entry_price: Optional[float]
    live_bid: Optional[float]
    live_ask: Optional[float]
    exit_bid: Optional[float]
    pnl_ticks: float
    hold_ms: int
    trades: int
    wins: int
    losses: int
    winrate: float
    avg_pnl_ticks: float


class ShooterEngine:
    def __init__(
        self,
        min_spread_ticks: float = 500.0,
        entry_spread_ratio: float = 0.30,
        fill_timeout_ms: int = 2000,
    ) -> None:
        self._min_spread_ticks = min_spread_ticks
        self._entry_spread_ratio = entry_spread_ratio
        self._fill_timeout_ms = fill_timeout_ms

        self._status = ShooterStatus.IDLE
        self._entry_price: Optional[float] = None
        self._entry_mono: float = 0.0
        self._exit_bid: Optional[float] = None
        self._pnl_ticks = 0.0
        self._hold_ms = 0

        self._trades = 0
        self._wins = 0
        self._losses = 0
        self._sum_pnl_ticks = 0.0

    def on_snapshot(self, snapshot: MarketSnapshot) -> ShooterView:
        if self._status == ShooterStatus.WAIT_FILL:
            self._update_wait_fill(snapshot)
        elif self._status in {ShooterStatus.FILLED, ShooterStatus.WIN, ShooterStatus.LOSS, ShooterStatus.TIMEOUT}:
            self._reset_to_idle()
            self._try_place_maker(snapshot)
        else:
            self._try_place_maker(snapshot)

        return self.view(snapshot.bid, snapshot.ask)

    def view(self, live_bid: Optional[float], live_ask: Optional[float]) -> ShooterView:
        winrate = (self._wins / self._trades * 100.0) if self._trades else 0.0
        avg_pnl = (self._sum_pnl_ticks / self._trades) if self._trades else 0.0
        return ShooterView(
            status=self._status,
            entry_price=self._entry_price,
            live_bid=live_bid,
            live_ask=live_ask,
            exit_bid=self._exit_bid,
            pnl_ticks=self._pnl_ticks,
            hold_ms=self._hold_ms,
            trades=self._trades,
            wins=self._wins,
            losses=self._losses,
            winrate=winrate,
            avg_pnl_ticks=avg_pnl,
        )

    def _try_place_maker(self, snapshot: MarketSnapshot) -> None:
        if snapshot.spread_ticks < self._min_spread_ticks:
            self._status = ShooterStatus.IDLE
            self._entry_price = None
            self._exit_bid = None
            self._pnl_ticks = 0.0
            self._hold_ms = 0
            return

        spread_u = snapshot.ask - snapshot.bid
        raw_entry_price = snapshot.bid + spread_u * self._entry_spread_ratio
        self._entry_price = round(raw_entry_price / TICK_SIZE) * TICK_SIZE
        self._entry_mono = snapshot.recv_monotonic
        self._exit_bid = None
        self._pnl_ticks = 0.0
        self._hold_ms = 0
        self._status = ShooterStatus.WAIT_FILL

    def _update_wait_fill(self, snapshot: MarketSnapshot) -> None:
        if self._entry_price is None:
            self._status = ShooterStatus.IDLE
            return

        self._hold_ms = int((snapshot.recv_monotonic - self._entry_mono) * 1000.0)

        if snapshot.bid >= self._entry_price:
            self._status = ShooterStatus.FILLED
            self._exit_bid = snapshot.bid
            self._pnl_ticks = (snapshot.bid - self._entry_price) / TICK_SIZE
            if self._pnl_ticks > 0.0:
                self._finish_trade(ShooterStatus.WIN)
            else:
                self._finish_trade(ShooterStatus.LOSS)
            return

        if self._hold_ms > self._fill_timeout_ms:
            self._status = ShooterStatus.TIMEOUT
            self._entry_price = None
            self._exit_bid = None
            self._pnl_ticks = 0.0

    def _finish_trade(self, result: ShooterStatus) -> None:
        self._status = result
        self._trades += 1
        if result == ShooterStatus.WIN:
            self._wins += 1
        else:
            self._losses += 1
        self._sum_pnl_ticks += self._pnl_ticks
        self._entry_price = None
        self._entry_mono = 0.0

    def _reset_to_idle(self) -> None:
        self._status = ShooterStatus.IDLE
        self._entry_price = None
        self._entry_mono = 0.0
        self._exit_bid = None
        self._pnl_ticks = 0.0
        self._hold_ms = 0
