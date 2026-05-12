from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.core.binance_client import BinanceClient
from app.core.market_state import MarketSnapshot, TICK_SIZE


class LiveStatus(str, Enum):
    IDLE = "IDLE"
    WAIT_FILL = "WAIT_FILL"
    FILLED = "FILLED"
    SELLING = "SELLING"
    WIN = "WIN"
    LOSS = "LOSS"


@dataclass(slots=True)
class LiveConfig:
    api_key: str = ""
    api_secret: str = ""
    order_size_u: float = 10.0
    live_enabled: bool = False


@dataclass(slots=True)
class LiveView:
    live_mode: str
    status: LiveStatus
    entry_price: Optional[float]
    exit_price: Optional[float]
    pnl_ticks: float
    pnl_u: float
    real_trades: int
    real_wins: int
    real_losses: int
    real_winrate: float
    real_total_pnl_u: float
    real_avg_pnl_u: float


class LiveTrader:
    def __init__(self, min_spread_ticks: float = 500.0, entry_spread_ratio: float = 0.30) -> None:
        self._min_spread_ticks = min_spread_ticks
        self._entry_spread_ratio = entry_spread_ratio

        self._config = LiveConfig()
        self._client: Optional[BinanceClient] = None
        self._status = LiveStatus.IDLE
        self._order_id: Optional[int] = None
        self._entry_price: Optional[float] = None
        self._entry_qty: float = 0.0
        self._pnl_ticks: float = 0.0
        self._pnl_u: float = 0.0
        self._exit_price: Optional[float] = None

        self._real_trades = 0
        self._real_wins = 0
        self._real_losses = 0
        self._real_total_pnl_u = 0.0

    def apply_config(self, config: LiveConfig) -> None:
        self._config = config
        if not config.live_enabled:
            self._status = LiveStatus.IDLE
            self._order_id = None
            return
        if not self._client and config.api_key and config.api_secret:
            self._client = BinanceClient(config.api_key, config.api_secret)

    def on_snapshot(self, snapshot: MarketSnapshot, log_fn) -> LiveView:
        if not self._config.live_enabled:
            return self.view()

        if not self._client:
            if self._config.api_key and self._config.api_secret:
                self._client = BinanceClient(self._config.api_key, self._config.api_secret)
            else:
                return self.view()

        if self._status == LiveStatus.IDLE and snapshot.spread_ticks >= self._min_spread_ticks:
            self._place_limit_buy(snapshot, log_fn)
        elif self._status == LiveStatus.WAIT_FILL:
            self._check_fill_and_sell(log_fn)

        return self.view()

    def _place_limit_buy(self, snapshot: MarketSnapshot, log_fn) -> None:
        if not self._client:
            return
        spread_u = snapshot.ask - snapshot.bid
        entry_price = round((snapshot.bid + spread_u * self._entry_spread_ratio) / TICK_SIZE) * TICK_SIZE
        order = self._client.place_limit_buy(entry_price, self._config.order_size_u)
        self._order_id = int(order["orderId"])
        self._entry_price = entry_price
        self._status = LiveStatus.WAIT_FILL
        log_fn(f"[LIVE] LIMIT BUY placed order_id={self._order_id} @ {entry_price:.2f}")

    def _check_fill_and_sell(self, log_fn) -> None:
        if not self._client or self._order_id is None:
            return
        order = self._client.get_order(self._order_id)
        if order.get("status") != "FILLED":
            return

        self._status = LiveStatus.FILLED
        self._entry_qty = float(order["executedQty"])
        buy_value_u = float(order["cummulativeQuoteQty"])
        log_fn(f"[LIVE] BUY filled order_id={self._order_id}")

        self._status = LiveStatus.SELLING
        sell = self._client.market_sell(self._entry_qty)
        log_fn("[LIVE] MARKET SELL sent")

        sell_value_u = float(sell.get("cummulativeQuoteQty", 0.0))
        if sell_value_u <= 0.0:
            sell_order_id = int(sell["orderId"])
            sell_q = self._client.get_order(sell_order_id)
            sell_value_u = float(sell_q.get("cummulativeQuoteQty", 0.0))

        self._pnl_u = sell_value_u - buy_value_u
        self._pnl_ticks = self._pnl_u / TICK_SIZE
        self._exit_price = (sell_value_u / self._entry_qty) if self._entry_qty > 0 else None

        self._real_trades += 1
        self._real_total_pnl_u += self._pnl_u
        if self._pnl_u >= 0:
            self._status = LiveStatus.WIN
            self._real_wins += 1
            log_fn(f"[LIVE] TRADE WIN {self._pnl_ticks:+.0f} ticks")
        else:
            self._status = LiveStatus.LOSS
            self._real_losses += 1
            log_fn(f"[LIVE] TRADE LOSS {self._pnl_ticks:+.0f} ticks")

        self._order_id = None
        self._entry_qty = 0.0

    def view(self) -> LiveView:
        winrate = (self._real_wins / self._real_trades * 100.0) if self._real_trades else 0.0
        avg = (self._real_total_pnl_u / self._real_trades) if self._real_trades else 0.0
        return LiveView(
            live_mode="ON" if self._config.live_enabled else "OFF",
            status=self._status,
            entry_price=self._entry_price,
            exit_price=self._exit_price,
            pnl_ticks=self._pnl_ticks,
            pnl_u=self._pnl_u,
            real_trades=self._real_trades,
            real_wins=self._real_wins,
            real_losses=self._real_losses,
            real_winrate=winrate,
            real_total_pnl_u=self._real_total_pnl_u,
            real_avg_pnl_u=avg,
        )
