from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, List


@dataclass
class RuntimeLogger:
    log_file: Path
    _buffer: Deque[str] = field(default_factory=lambda: deque(maxlen=200))

    def __post_init__(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, level: str, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{ts}] [{level}] {message}"
        self._buffer.append(line)
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def info(self, message: str) -> None:
        self.write("INFO", message)

    def warn(self, message: str) -> None:
        self.write("WARN", message)

    def error(self, message: str) -> None:
        self.write("ERROR", message)

    def tail(self) -> List[str]:
        return list(self._buffer)
