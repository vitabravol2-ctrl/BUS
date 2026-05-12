from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from binance.exceptions import BinanceAPIException

from app.core.binance_client import BinanceClient
from app.core.market_state import MarketSnapshot, TICK_SIZE


class LiveStatus(str, Enum):
    IDLE = "IDLE"
    READY = "READY"
    PLACE_FAST_BUY = "PLACE_FAST_BUY"
    WAIT_BUY_FILL = "WAIT_BUY_FILL"
    PLACE_FAST_SELL = "PLACE_FAST_SELL"
    WAIT_SELL_FILL = "WAIT_SELL_FILL"
    WIN = "WIN"
    LOSS = "LOSS"
    CANCEL = "CANCEL"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"
    BALANCE_LOW = "BALANCE_LOW"
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
    buy_age_ms: int
    sell_age_ms: int
    real_trades: int
    real_wins: int
    real_losses: int
    real_winrate: float
    real_total_pnl_u: float
    real_avg_pnl_u: float
    base_asset: str
    base_free: float
    quote_asset: str
    quote_free: float
    usdt_free: float


class LiveTrader:
    def __init__(self, min_spread_ticks: float = 500.0) -> None:
        self._min_spread_ticks = min_spread_ticks
        self._config = LiveConfig()
        self._client: Optional[BinanceClient] = None
        self._status = LiveStatus.IDLE
        self._buy_order_id: Optional[int] = None
        self._sell_order_id: Optional[int] = None
        self._entry_price: Optional[float] = None
        self._exit_price: Optional[float] = None
        self._entry_qty: float = 0.0
        self._buy_value_u: float = 0.0
        self._pnl_ticks = 0.0
        self._pnl_u = 0.0
        self._buy_start_mono = 0.0
        self._sell_start_mono = 0.0
        self._buy_timeout_ms = 180
        self._sell_timeout_ms = 110
        self._last_bid = 0.0
        self._last_ask = 0.0
        self._last_spread_ticks = 0.0
        self._real_trades = 0
        self._real_wins = 0
        self._real_losses = 0
        self._real_total_pnl_u = 0.0
        self._base_asset = "BTC"
        self._base_free = 0.0
        self._quote_asset = "U"
        self._quote_free = 0.0
        self._usdt_free = 0.0
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

    def apply_config(self, config: LiveConfig) -> None:
        self._config = config

    def start_live(self, log_fn) -> bool:
        if not self._config.api_key or not self._config.api_secret:
            log_fn("error: API key/secret missing")
            self._status = LiveStatus.ERROR
            return False
        self._client = BinanceClient(self._config.api_key, self._config.api_secret, symbol="BTCU")
        self._config.live_enabled = True
        self._status = LiveStatus.READY
        self.refresh_balances(log_fn)
        self._stop_evt.clear()
        self._worker = threading.Thread(target=self._worker_loop, args=(log_fn,), daemon=True, name="live-worker")
        self._worker.start()
        log_fn("live started")
        return True

    def stop_live(self, log_fn) -> None:
        self._config.live_enabled = False
        self._stop_evt.set()
        self._status = LiveStatus.IDLE
        log_fn("live stopped")

    def refresh_balances(self, log_fn) -> None:
        if not self._client:
            return
        snap = self._client.get_balance_snapshot()
        self._base_asset = snap.base_asset
        self._base_free = snap.base_free
        self._quote_asset = snap.quote_asset
        self._quote_free = snap.quote_free
        self._usdt_free = snap.usdt_free
        log_fn(f"[ACCOUNT] {self._base_asset}={self._base_free:.8f} {self._quote_asset}={self._quote_free:.8f}")

    def on_snapshot(self, snapshot: MarketSnapshot, log_fn) -> LiveView:
        self._last_bid = snapshot.bid
        self._last_ask = snapshot.ask
        self._last_spread_ticks = snapshot.spread_ticks
        return self.view()

    def _worker_loop(self, log_fn) -> None:
        while not self._stop_evt.is_set() and self._config.live_enabled and self._client:
            try:
                if self._status == LiveStatus.READY and self._last_spread_ticks >= self._min_spread_ticks:
                    self.refresh_balances(log_fn)
                    if self._quote_free < self._config.order_size_u * 1.01:
                        self._status = LiveStatus.BALANCE_LOW
                        time.sleep(0.05)
                        self._status = LiveStatus.READY
                        continue
                    self._status = LiveStatus.PLACE_FAST_BUY
                    self._entry_price = self._last_bid + (60 * TICK_SIZE)
                    prepared = self._client.prepare_limit_buy(self._entry_price, self._config.order_size_u)
                    if prepared.error:
                        log_fn(prepared.error)
                        self._status = LiveStatus.READY
                        continue
                    self._entry_price = prepared.price
                    self._buy_timeout_ms = random.randint(120, 250)
                    self._buy_start_mono = time.monotonic()
                    buy_order = self._client.place_limit_buy_prepared(prepared)
                    self._buy_order_id = int(buy_order["orderId"])
                    self._status = LiveStatus.WAIT_BUY_FILL
                    log_fn("BUY_SENT")

                    while self._status == LiveStatus.WAIT_BUY_FILL and self._buy_order_id:
                        order = self._client.get_order(self._buy_order_id)
                        if order.get("status") == "FILLED":
                            buy_ms = int((time.monotonic() - self._buy_start_mono) * 1000)
                            log_fn(f"BUY_FILLED {buy_ms}ms")
                            self._handle_buy_filled(order, log_fn)
                            break
                        age = int((time.monotonic() - self._buy_start_mono) * 1000)
                        if age > self._buy_timeout_ms:
                            self._client.cancel_order(self._buy_order_id)
                            self._buy_order_id = None
                            self._status = LiveStatus.CANCEL
                            log_fn("buy cancel timeout")
                            self._status = LiveStatus.READY
                            break
                        time.sleep(random.uniform(0.03, 0.05))

                time.sleep(0.005)
            except BinanceAPIException as exc:
                log_fn(f"error: {getattr(exc, 'message', str(exc))}")
                self._status = LiveStatus.ERROR
                time.sleep(0.1)
            except Exception as exc:
                log_fn(f"error: {exc}")
                self._status = LiveStatus.ERROR
                time.sleep(0.1)

    def _handle_buy_filled(self, order: dict, log_fn) -> None:
        self._entry_qty = float(order.get("executedQty", 0.0))
        self._buy_value_u = float(order.get("cummulativeQuoteQty", 0.0))
        if not self._client or self._entry_qty <= 0:
            self._status = LiveStatus.ERROR
            return

        self._status = LiveStatus.PLACE_FAST_SELL
        self._sell_timeout_ms = random.randint(80, 150)
        self._sell_start_mono = time.monotonic()
        self._exit_price = self._last_bid + (20 * TICK_SIZE)
        sell_order = self._client.place_limit_sell_near_top(self._entry_qty, self._last_bid)
        self._sell_order_id = int(sell_order["orderId"])
        self._status = LiveStatus.WAIT_SELL_FILL
        log_fn("SELL_SENT")

        while self._status == LiveStatus.WAIT_SELL_FILL and self._sell_order_id:
            if self._last_spread_ticks < 20:
                market = self._client.market_sell(self._entry_qty)
                sell_ms = int((time.monotonic() - self._sell_start_mono) * 1000)
                log_fn(f"SELL_FILLED {sell_ms}ms")
                self._finish_trade(float(market.get("cummulativeQuoteQty", 0.0)), LiveStatus.EMERGENCY_EXIT, log_fn)
                break
            order_state = self._client.get_order(self._sell_order_id)
            if order_state.get("status") == "FILLED":
                sell_ms = int((time.monotonic() - self._sell_start_mono) * 1000)
                log_fn(f"SELL_FILLED {sell_ms}ms")
                sell_value_u = float(order_state.get("cummulativeQuoteQty", 0.0))
                self._finish_trade(sell_value_u, LiveStatus.WIN if sell_value_u >= self._buy_value_u else LiveStatus.LOSS, log_fn)
                break
            age = int((time.monotonic() - self._sell_start_mono) * 1000)
            if age > self._sell_timeout_ms:
                market = self._client.market_sell(self._entry_qty)
                self._status = LiveStatus.EMERGENCY_EXIT
                sell_ms = int((time.monotonic() - self._sell_start_mono) * 1000)
                log_fn(f"SELL_FILLED {sell_ms}ms")
                self._finish_trade(float(market.get("cummulativeQuoteQty", 0.0)), LiveStatus.EMERGENCY_EXIT, log_fn)
                break
            time.sleep(random.uniform(0.03, 0.05))

    def _finish_trade(self, sell_value_u: float, result: LiveStatus, log_fn) -> None:
        self._pnl_u = sell_value_u - self._buy_value_u
        self._pnl_ticks = self._pnl_u / TICK_SIZE
        log_fn(f"TRADE_CLOSED {self._pnl_ticks:+.0f} ticks")
        self._real_trades += 1
        self._real_total_pnl_u += self._pnl_u
        if result == LiveStatus.WIN:
            self._real_wins += 1
        else:
            self._real_losses += 1
        self._status = LiveStatus.READY if self._config.live_enabled else LiveStatus.IDLE
        self._buy_order_id = None
        self._sell_order_id = None
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
            buy_age_ms=int((time.monotonic() - self._buy_start_mono) * 1000) if self._buy_start_mono else 0,
            sell_age_ms=int((time.monotonic() - self._sell_start_mono) * 1000) if self._sell_start_mono else 0,
            real_trades=self._real_trades,
            real_wins=self._real_wins,
            real_losses=self._real_losses,
            real_winrate=winrate,
            real_total_pnl_u=self._real_total_pnl_u,
            real_avg_pnl_u=avg,
            base_asset=self._base_asset,
            base_free=self._base_free,
            quote_asset=self._quote_asset,
            quote_free=self._quote_free,
            usdt_free=self._usdt_free,
        )
