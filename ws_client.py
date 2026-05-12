from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import websockets


BOOK_TICKER_URL = "wss://stream.binance.com:9443/ws/btcuusdt@bookTicker"


@dataclass
class BookTicker:
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    event_time_ms: int


class WsClient:
    def __init__(self, on_ticker: Callable[[BookTicker], None], on_status: Callable[[str], None]) -> None:
        self.on_ticker = on_ticker
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def connect(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        self.on_status("WS connecting...")
        try:
            async with websockets.connect(BOOK_TICKER_URL, ping_interval=10, ping_timeout=10) as ws:
                self.on_status("WS connected")
                while not self._stop.is_set():
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(raw)
                    tick = BookTicker(
                        bid=float(data["b"]),
                        ask=float(data["a"]),
                        bid_qty=float(data["B"]),
                        ask_qty=float(data["A"]),
                        event_time_ms=int(data["E"]),
                    )
                    self.on_ticker(tick)
        except Exception as exc:
            self.on_status(f"WS error: {exc}")
