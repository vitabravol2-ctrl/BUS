from __future__ import annotations

import json
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal
from websocket import WebSocketApp

from app.core.market_state import build_snapshot

WS_URL = "wss://stream.binance.com:9443/ws/btcu@bookTicker"


class WsClient(QObject):
    market = Signal(object)
    status = Signal(str)
    metrics = Signal(float, float)  # updates_per_sec, ws_age_sec

    def __init__(self) -> None:
        super().__init__()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws: Optional[WebSocketApp] = None
        self._last_recv_monotonic = 0.0
        self._last_event_ms = 0
        self._updates_counter = 0
        self._counter_window_start = time.monotonic()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_forever, daemon=True, name="ws-client")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws:
            self._ws.close()

    def _run_forever(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            self.status.emit("LOST")
            self.status.emit("CONNECTING")
            self._ws = WebSocketApp(
                WS_URL,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self._ws.run_forever(ping_interval=15, ping_timeout=10)
            if self._stop_event.is_set():
                break
            self.status.emit(f"RECONNECT in {backoff:.1f}s")
            time.sleep(backoff)
            backoff = min(backoff * 1.8, 10.0)

    def _on_open(self, ws: WebSocketApp) -> None:
        self.status.emit("CONNECTED")

    def _on_message(self, ws: WebSocketApp, message: str) -> None:
        now = time.monotonic()
        payload = json.loads(message)
        bid = float(payload["b"])
        ask = float(payload["a"])
        event_ms = int(payload.get("E", int(time.time() * 1000)))

        snapshot = build_snapshot(bid, ask, event_ms, now)
        self.market.emit(snapshot)

        self._last_recv_monotonic = now
        self._last_event_ms = event_ms
        self._updates_counter += 1

        elapsed = now - self._counter_window_start
        if elapsed >= 1.0:
            ups = self._updates_counter / elapsed
            ws_age = max(0.0, (time.time() * 1000 - self._last_event_ms) / 1000.0)
            self.metrics.emit(ups, ws_age)
            self._updates_counter = 0
            self._counter_window_start = now

    def _on_error(self, ws: WebSocketApp, error: object) -> None:
        self.status.emit(f"ERROR: {error}")

    def _on_close(self, ws: WebSocketApp, code: int, msg: str) -> None:
        self.status.emit(f"LOST ({code})")
