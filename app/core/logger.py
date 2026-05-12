from __future__ import annotations

import time
from collections import deque


class UiLogger:
    def __init__(self, max_lines: int = 200, dedup_window_sec: float = 1.0) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._last_message = ""
        self._last_ts = 0.0
        self._dedup_window_sec = dedup_window_sec

    def log(self, message: str) -> None:
        now = time.monotonic()
        if message == self._last_message and (now - self._last_ts) < self._dedup_window_sec:
            return
        self._last_message = message
        self._last_ts = now
        stamp = time.strftime("%H:%M:%S", time.gmtime())
        self._lines.append(f"[{stamp}] {message}")

    def lines(self) -> list[str]:
        return list(self._lines)
