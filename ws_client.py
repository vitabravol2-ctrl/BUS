from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

import websockets

EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"


@dataclass
class SymbolMeta:
    symbol: str
    tick_size: float
    step_size: float
    min_qty: float
    min_notional: float


@dataclass
class BookTicker:
    symbol: str
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    event_time_ms: int
    recv_time_ms: int


class WsClient:
    def __init__(
        self,
        on_ticker: Callable[[BookTicker], None],
        on_status: Callable[[str], None],
        on_symbol_meta: Optional[Callable[[SymbolMeta], None]] = None,
    ) -> None:
        self.on_ticker = on_ticker
        self.on_status = on_status
        self.on_symbol_meta = on_symbol_meta
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.symbol = "BTCUUSDT"

    def connect(self, symbol: str) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.symbol = symbol.upper()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        asyncio.run(self._run_async())

    def _validate_symbol(self, symbol: str) -> Optional[SymbolMeta]:
        query = urllib.parse.urlencode({"symbol": symbol})
        url = f"{EXCHANGE_INFO_URL}?{query}"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                self.on_status(f"INVALID SYMBOL: {symbol}")
                return None
            raise

        symbols = payload.get("symbols", [])
        if not symbols:
            self.on_status(f"INVALID SYMBOL: {symbol}")
            return None

        info = symbols[0]
        self.on_status(f"FOUND SYMBOL: {info['symbol']}")

        tick_size = step_size = min_qty = min_notional = 0.0
        for f in info.get("filters", []):
            ftype = f.get("filterType")
            if ftype == "PRICE_FILTER":
                tick_size = float(f.get("tickSize", 0.0))
            elif ftype == "LOT_SIZE":
                step_size = float(f.get("stepSize", 0.0))
                min_qty = float(f.get("minQty", 0.0))
            elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = float(f.get("minNotional", 0.0))

        self.on_status(
            "[FILTERS] "
            f"symbol={info['symbol']} tickSize={tick_size} stepSize={step_size} "
            f"minQty={min_qty} minNotional={min_notional}"
        )

        meta = SymbolMeta(
            symbol=info["symbol"],
            tick_size=tick_size,
            step_size=step_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        if self.on_symbol_meta:
            self.on_symbol_meta(meta)
        return meta

    async def _run_async(self) -> None:
        self.on_status("WS connecting...")
        try:
            meta = self._validate_symbol(self.symbol)
            if not meta:
                return

            stream = f"{meta.symbol.lower()}@bookTicker"
            ws_url = f"wss://stream.binance.com:9443/ws/{stream}"
            self.on_status(f"WS stream: {stream}")
            async with websockets.connect(ws_url, ping_interval=10, ping_timeout=10) as ws:
                self.on_status("WS connected")
                while not self._stop.is_set():
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    recv_ms = int(time.time() * 1000)
                    data = json.loads(raw)
                    tick = BookTicker(
                        symbol=data.get("s", meta.symbol),
                        bid=float(data["b"]),
                        ask=float(data["a"]),
                        bid_qty=float(data["B"]),
                        ask_qty=float(data["A"]),
                        event_time_ms=int(data["E"]),
                        recv_time_ms=recv_ms,
                    )
                    spread = tick.ask - tick.bid
                    age = recv_ms - tick.event_time_ms
                    self.on_status(
                        f"BOOK UPDATE bid={tick.bid:.8f} ask={tick.ask:.8f} spread={spread:.8f} age_ms={age}"
                    )
                    self.on_ticker(tick)
        except Exception as exc:
            self.on_status(f"WS error: {exc}")
