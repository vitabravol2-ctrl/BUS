from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QMainWindow, QTextEdit, QVBoxLayout, QWidget

from app.core.logger import UiLogger
from app.core.market_state import MarketSnapshot
from app.core.ws_client import WsClient


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BUS BTCU Spread Shooter v0.1.0")
        self.resize(620, 520)

        self._logger = UiLogger()
        self._ws = WsClient()

        self._status = QLabel("WS STATUS: LOST")
        self._metrics = QLabel("UPDATES/SEC: 0.0 | WS AGE: -")
        self._bid = QLabel("BID\n-")
        self._ask = QLabel("ASK\n-")
        self._spread = QLabel("SPREAD\n- ticks\n- U")
        self._log_panel = QTextEdit()
        self._log_panel.setReadOnly(True)

        self._setup_ui()
        self._connect_signals()

        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_log)
        self._render_timer.start(250)

        self._ws.start()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._ws.stop()
        super().closeEvent(event)

    def _setup_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        font_big = QFont("Consolas", 28, QFont.Weight.Bold)
        font_mid = QFont("Consolas", 12, QFont.Weight.Bold)

        self._status.setFont(font_mid)
        self._metrics.setFont(font_mid)
        self._bid.setFont(font_big)
        self._ask.setFont(font_big)
        self._spread.setFont(font_big)

        self.setStyleSheet(
            "QMainWindow { background-color: #0f1115; }"
            "QLabel { color: #d7dbdf; }"
            "QTextEdit { background-color: #090b0f; color: #83f28f; border: 1px solid #2a2f39; }"
        )

        layout.addWidget(self._status)
        layout.addWidget(self._metrics)
        layout.addSpacing(10)
        layout.addWidget(self._bid)
        layout.addWidget(self._ask)
        layout.addWidget(self._spread)
        layout.addSpacing(16)
        layout.addWidget(self._log_panel)

    def _connect_signals(self) -> None:
        self._ws.status.connect(self._on_status)
        self._ws.market.connect(self._on_market)
        self._ws.metrics.connect(self._on_metrics)

    def _on_status(self, status: str) -> None:
        self._status.setText(f"WS STATUS: {status}")
        self._logger.log(status)

    def _on_market(self, snapshot: MarketSnapshot) -> None:
        self._bid.setText(f"BID\n{snapshot.bid:.2f}")
        self._ask.setText(f"ASK\n{snapshot.ask:.2f}")
        self._spread.setText(
            f"SPREAD\n{snapshot.spread_ticks:.0f} ticks\n{snapshot.spread_u:.2f} U"
        )

    def _on_metrics(self, updates_per_sec: float, ws_age_sec: float) -> None:
        self._metrics.setText(f"UPDATES/SEC: {updates_per_sec:.1f} | WS AGE: {ws_age_sec:.3f}s")

    def _render_log(self) -> None:
        self._log_panel.setPlainText("\n".join(self._logger.lines()))
