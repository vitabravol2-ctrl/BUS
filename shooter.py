from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ws_client import BookTicker


class Impulse(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class Position(str, Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Config:
    order_size_u: float = 20.0
    target_ticks: float = 1.0
    stop_ticks: float = 2.0
    max_hold_ms: int = 700
    min_spread_ticks: float = 2.0
    tick_size: float = 0.01


@dataclass
class Shot:
    entry: float = 0.0
    hold_ms: int = 0
    pnl: float = 0.0


class Shooter:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.position = Position.FLAT
        self.last_mid: Optional[float] = None
        self.last_mid_ts_ms: Optional[int] = None
        self.velocity = 0.0
        self.shot = Shot()
        self.shots = 0
        self.wins = 0
        self.losses = 0
        self.running = False
        self.last_tick: Optional[BookTicker] = None

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def panic_exit(self) -> str:
        if self.position == Position.LONG and self.last_tick:
            return self._close(self.last_tick.bid, "panic")
        self.position = Position.FLAT
        return "panic: flat"

    def on_ticker(self, tick: BookTicker) -> Optional[str]:
        self.last_tick = tick
        mid = (tick.bid + tick.ask) / 2.0
        if self.last_mid is not None and self.last_mid_ts_ms is not None:
            dt = max(1, tick.event_time_ms - self.last_mid_ts_ms)
            self.velocity = (mid - self.last_mid) / dt
        self.last_mid = mid
        self.last_mid_ts_ms = tick.event_time_ms

        if not self.running:
            return None

        if self.position == Position.FLAT:
            spread_ticks = (tick.ask - tick.bid) / self.cfg.tick_size
            if spread_ticks >= self.cfg.min_spread_ticks and self.velocity > 0:
                self.position = Position.LONG
                self.shot = Shot(entry=tick.ask)
                self.shots += 1
                return f"ENTRY BUY @{tick.ask:.2f}"
            return None

        self.shot.hold_ms = int(time.time() * 1000) - tick.event_time_ms
        self.shot.pnl = tick.bid - self.shot.entry

        if tick.bid >= self.shot.entry + self.cfg.target_ticks * self.cfg.tick_size:
            return self._close(tick.bid, "target")

        if self.shot.hold_ms > self.cfg.max_hold_ms or tick.bid <= self.shot.entry - self.cfg.stop_ticks * self.cfg.tick_size:
            return self._close(tick.bid, "stop")

        return None

    def _close(self, exit_price: float, reason: str) -> str:
        pnl = exit_price - self.shot.entry
        self.position = Position.FLAT
        if pnl >= 0:
            self.wins += 1
        else:
            self.losses += 1
        self.shot.pnl = pnl
        return f"EXIT SELL @{exit_price:.2f} pnl={pnl:.4f} reason={reason}"

    def impulse(self) -> Impulse:
        if self.velocity > 0:
            return Impulse.UP
        if self.velocity < 0:
            return Impulse.DOWN
        return Impulse.FLAT

    def stats(self) -> dict:
        wr = (self.wins / self.shots * 100.0) if self.shots else 0.0
        return {
            "shots": self.shots,
            "wins": self.wins,
            "losses": self.losses,
            "winrate": wr,
            "avg_pnl": self.shot.pnl,
        }
