from __future__ import annotations

from dataclasses import dataclass


TICK_SIZE = 0.01


@dataclass(slots=True)
class MarketSnapshot:
    bid: float
    ask: float
    spread_u: float
    spread_ticks: float
    event_time_ms: int
    recv_monotonic: float



def build_snapshot(bid: float, ask: float, event_time_ms: int, recv_monotonic: float) -> MarketSnapshot:
    spread_u = ask - bid
    spread_ticks = spread_u / TICK_SIZE
    return MarketSnapshot(
        bid=bid,
        ask=ask,
        spread_u=spread_u,
        spread_ticks=spread_ticks,
        event_time_ms=event_time_ms,
        recv_monotonic=recv_monotonic,
    )
