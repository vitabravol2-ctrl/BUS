from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from binance.exceptions import BinanceAPIException

from app.core.binance_client import BinanceClient, FilterCheckResult
from app.core.market_state import MarketSnapshot, TICK_SIZE


class LiveStatus(str, Enum):
    IDLE = "IDLE"
    READY = "READY"
    WAIT_FILL = "WAIT_FILL"
    FILLED = "FILLED"
    SELLING = "SELLING"
    WIN = "WIN"
    LOSS = "LOSS"
    ERROR = "ERROR"


@dataclass(slots=True)
class LiveConfig:
    api_key: str = ""
    api_secret: str = ""
    order_size_u: float = 15.0
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
        self._exit_price: Optional[float] = None
        self._pnl_ticks = 0.0
        self._pnl_u = 0.0
        self._real_trades = 0
        self._real_wins = 0
        self._real_losses = 0
        self._real_total_pnl_u = 0.0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-binance")
        self._future: Optional[Future] = None
        self._poll_future: Optional[Future] = None

    def apply_config(self, config: LiveConfig) -> None:
        self._config = config

    def start_live(self, log_fn) -> bool:
        if not self._config.api_key or not self._config.api_secret:
            log_fn("error: API key/secret missing")
            self._status = LiveStatus.ERROR
            return False
        self._client = BinanceClient(self._config.api_key, self._config.api_secret)
        self._config.live_enabled = True
        self._status = LiveStatus.READY
        log_fn("live started")
        return True

    def stop_live(self, log_fn) -> None:
        self._config.live_enabled = False
        if self._order_id and self._client:
            self._executor.submit(self._client.cancel_order, self._order_id)
        if self._entry_qty > 0:
            log_fn("WARNING inventory exists")
        self._order_id = None
        self._status = LiveStatus.IDLE
        log_fn("live stopped")

    def on_snapshot(self, snapshot: MarketSnapshot, log_fn) -> LiveView:
        self._resolve_futures(log_fn)
        if not self._config.live_enabled or not self._client:
            return self.view()

        if self._status == LiveStatus.READY and not self._future and snapshot.spread_ticks >= self._min_spread_ticks:
            spread_u = snapshot.ask - snapshot.bid
            raw_entry = snapshot.bid + spread_u * self._entry_spread_ratio
            check = self._client.prepare_limit_buy(raw_entry, self._config.order_size_u)
            if check.error:
                log_fn(check.error)
                return self.view()
            self._entry_price = check.price
            self._future = self._executor.submit(self._client.place_limit_buy_prepared, check)
            self._status = LiveStatus.WAIT_FILL
            log_fn("buy placed")
        elif self._status == LiveStatus.WAIT_FILL and not self._poll_future and self._order_id:
            self._poll_future = self._executor.submit(self._client.get_order, self._order_id)
        return self.view()

    def _resolve_futures(self, log_fn) -> None:
        for attr in ("_future", "_poll_future"):
            fut = getattr(self, attr)
            if not fut or not fut.done():
                continue
            setattr(self, attr, None)
            try:
                result = fut.result()
                if isinstance(result, dict) and result.get("orderId") and self._order_id is None:
                    self._order_id = int(result["orderId"])
                elif isinstance(result, dict) and result.get("status") == "FILLED":
                    self._handle_filled_order(result, log_fn)
            except BinanceAPIException as exc:
                log_fn(f"error: {exc.message}")
                self._status = LiveStatus.ERROR
                self._config.live_enabled = False
            except Exception as exc:
                log_fn(f"error: {exc}")
                self._status = LiveStatus.ERROR
                self._config.live_enabled = False

    def _handle_filled_order(self, order: dict, log_fn) -> None:
        self._status = LiveStatus.FILLED
        self._entry_qty = float(order.get("executedQty", 0.0))
        buy_value_u = float(order.get("cummulativeQuoteQty", 0.0))
        log_fn("buy filled")
        self._status = LiveStatus.SELLING
        sell = self._client.market_sell(self._entry_qty) if self._client else {}
        log_fn("sell sent")
        sell_value_u = float(sell.get("cummulativeQuoteQty", 0.0))
        self._pnl_u = sell_value_u - buy_value_u
        self._pnl_ticks = self._pnl_u / TICK_SIZE
        self._exit_price = sell_value_u / self._entry_qty if self._entry_qty > 0 else None
        self._real_trades += 1
        self._real_total_pnl_u += self._pnl_u
        if self._pnl_u >= 0:
            self._status = LiveStatus.WIN
            self._real_wins += 1
        else:
            self._status = LiveStatus.LOSS
            self._real_losses += 1
        log_fn("trade closed")
        self._status = LiveStatus.READY if self._config.live_enabled else LiveStatus.IDLE
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
