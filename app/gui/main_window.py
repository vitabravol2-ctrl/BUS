from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.live_trader import LiveConfig, LiveTrader
from app.core.logger import UiLogger
from app.core.market_state import MarketSnapshot
from app.core.shooter_engine import ShooterEngine, ShooterStatus, ShooterView
from app.core.ws_client import WsClient


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BUS BTCU Spread Shooter v0.4.0")
        self.resize(760, 920)

        self._logger = UiLogger()
        self._ws = WsClient()
        self._shooter = ShooterEngine()
        self._live = LiveTrader()

        self._status = QLabel("WS STATUS: LOST")
        self._metrics = QLabel("UPDATES/SEC: 0.0 | WS AGE: -")
        self._bid = QLabel("BID\n-")
        self._ask = QLabel("ASK\n-")
        self._spread = QLabel("SPREAD\n- ticks\n- U")

        self._live_mode = QLabel("LIVE MODE: OFF")
        self._live_status = QLabel("STATUS\nIDLE")
        self._live_entry = QLabel("ENTRY\n-")
        self._live_exit = QLabel("EXIT\n-")
        self._live_pnl = QLabel("REAL PNL\n0.00 U | +0 ticks")
        self._real_session = QLabel("REAL TRADES: 0 | REAL WINS: 0 | REAL LOSSES: 0 | REAL WINRATE: 0.0% | REAL TOTAL PNL U: 0.00 | REAL AVG PNL: 0.00")

        self._shooter_header = QLabel("SIM SHOOTER")
        self._shooter_status = QLabel("STATUS\nIDLE")
        self._shooter_entry = QLabel("ENTRY\n-")
        self._shooter_live_bid = QLabel("LIVE BID\n-")
        self._shooter_live_ask = QLabel("LIVE ASK\n-")
        self._shooter_exit_bid = QLabel("EXIT BID\n-")
        self._shooter_pnl = QLabel("PNL\n0 ticks")
        self._shooter_hold = QLabel("HOLD\n0 ms")
        self._session = QLabel("TRADES: 0 | WINS: 0 | LOSSES: 0 | WINRATE: 0.0% | AVG PNL: 0.0 ticks")

        self._api_key = QLineEdit()
        self._api_secret = QLineEdit()
        self._order_size_u = QLineEdit("10")
        self._live_enable = QCheckBox("LIVE ENABLE")

        self._log_panel = QTextEdit()
        self._log_panel.setReadOnly(True)

        self._setup_ui()
        self._connect_signals()
        self._apply_live_config()

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
        font_small = QFont("Consolas", 11, QFont.Weight.Bold)

        self._status.setFont(font_mid)
        self._metrics.setFont(font_mid)
        self._bid.setFont(font_big)
        self._ask.setFont(font_big)
        self._spread.setFont(font_big)
        self._live_mode.setFont(font_mid)
        self._live_status.setFont(font_mid)
        self._live_entry.setFont(font_small)
        self._live_exit.setFont(font_small)
        self._live_pnl.setFont(font_small)
        self._real_session.setFont(font_small)
        self._shooter_header.setFont(font_mid)
        self._shooter_status.setFont(font_mid)
        self._shooter_entry.setFont(font_small)
        self._shooter_live_bid.setFont(font_small)
        self._shooter_live_ask.setFont(font_small)
        self._shooter_exit_bid.setFont(font_small)
        self._shooter_pnl.setFont(font_small)
        self._shooter_hold.setFont(font_small)
        self._session.setFont(font_small)

        self._api_secret.setEchoMode(QLineEdit.EchoMode.Password)

        config_group = QGroupBox("LIVE SETTINGS")
        form = QFormLayout(config_group)
        form.addRow("API KEY", self._api_key)
        form.addRow("API SECRET", self._api_secret)
        form.addRow("ORDER SIZE U", self._order_size_u)
        form.addRow("", self._live_enable)

        self.setStyleSheet(
            "QMainWindow { background-color: #0f1115; }"
            "QLabel, QGroupBox { color: #d7dbdf; }"
            "QLineEdit { background-color: #161a22; color: #d7dbdf; border: 1px solid #2a2f39; }"
            "QTextEdit { background-color: #090b0f; color: #83f28f; border: 1px solid #2a2f39; }"
        )

        for w in [self._status, self._metrics, self._bid, self._ask, self._spread, config_group, self._live_mode,
                  self._live_status, self._live_entry, self._live_exit, self._live_pnl, self._real_session,
                  self._shooter_header, self._shooter_status, self._shooter_entry, self._shooter_live_bid,
                  self._shooter_live_ask, self._shooter_exit_bid, self._shooter_pnl, self._shooter_hold,
                  self._session, self._log_panel]:
            layout.addWidget(w)

    def _connect_signals(self) -> None:
        self._ws.status.connect(self._on_status)
        self._ws.market.connect(self._on_market)
        self._ws.metrics.connect(self._on_metrics)
        self._live_enable.toggled.connect(self._apply_live_config)
        self._api_key.editingFinished.connect(self._apply_live_config)
        self._api_secret.editingFinished.connect(self._apply_live_config)
        self._order_size_u.editingFinished.connect(self._apply_live_config)

    def _apply_live_config(self) -> None:
        try:
            order_size_u = max(1.0, float(self._order_size_u.text().strip()))
        except ValueError:
            order_size_u = 10.0
            self._order_size_u.setText("10")
        cfg = LiveConfig(
            api_key=self._api_key.text().strip(),
            api_secret=self._api_secret.text().strip(),
            order_size_u=order_size_u,
            live_enabled=self._live_enable.isChecked(),
        )
        self._live.apply_config(cfg)

    def _on_status(self, status: str) -> None:
        self._status.setText(f"WS STATUS: {status}")
        self._logger.log(status)

    def _on_market(self, snapshot: MarketSnapshot) -> None:
        self._bid.setText(f"BID\n{snapshot.bid:.2f}")
        self._ask.setText(f"ASK\n{snapshot.ask:.2f}")
        self._spread.setText(f"SPREAD\n{snapshot.spread_ticks:.0f} ticks\n{snapshot.spread_u:.2f} U")
        self._spread.setStyleSheet("color: #4de1e8;")

        shooter = self._shooter.on_snapshot(snapshot)
        self._render_shooter(shooter)

        live = self._live.on_snapshot(snapshot, self._logger.log)
        self._render_live(live)

    def _on_metrics(self, updates_per_sec: float, ws_age_sec: float) -> None:
        self._metrics.setText(f"UPDATES/SEC: {updates_per_sec:.1f} | WS AGE: {ws_age_sec:.3f}s")

    def _render_live(self, view) -> None:
        self._live_mode.setText(f"LIVE MODE: {view.live_mode}")
        self._live_status.setText(f"STATUS\n{view.status.value}")
        self._live_entry.setText(f"ENTRY\n{view.entry_price:.2f}" if view.entry_price is not None else "ENTRY\n-")
        self._live_exit.setText(f"EXIT\n{view.exit_price:.2f}" if view.exit_price is not None else "EXIT\n-")
        self._live_pnl.setText(f"REAL PNL\n{view.pnl_u:+.2f} U | {view.pnl_ticks:+.0f} ticks")
        self._real_session.setText(
            f"REAL TRADES: {view.real_trades} | REAL WINS: {view.real_wins} | REAL LOSSES: {view.real_losses} | "
            f"REAL WINRATE: {view.real_winrate:.1f}% | REAL TOTAL PNL U: {view.real_total_pnl_u:+.2f} | "
            f"REAL AVG PNL: {view.real_avg_pnl_u:+.2f}"
        )

    def _render_shooter(self, view: ShooterView) -> None:
        self._shooter_status.setText(f"STATUS\n{view.status.value}")
        self._shooter_entry.setText(f"ENTRY\n{view.entry_price:.2f}" if view.entry_price is not None else "ENTRY\n-")
        self._shooter_live_bid.setText(f"LIVE BID\n{view.live_bid:.2f}" if view.live_bid is not None else "LIVE BID\n-")
        self._shooter_live_ask.setText(f"LIVE ASK\n{view.live_ask:.2f}" if view.live_ask is not None else "LIVE ASK\n-")
        self._shooter_exit_bid.setText(f"EXIT BID\n{view.exit_bid:.2f}" if view.exit_bid is not None else "EXIT BID\n-")
        self._shooter_pnl.setText(f"PNL\n{view.pnl_ticks:+.1f} ticks")
        self._shooter_hold.setText(f"HOLD\n{view.hold_ms} ms")
        self._session.setText(
            f"TRADES: {view.trades} | WINS: {view.wins} | LOSSES: {view.losses} | "
            f"WINRATE: {view.winrate:.1f}% | AVG PNL: {view.avg_pnl_ticks:+.1f} ticks"
        )

        color = "#d7dbdf"
        if view.status == ShooterStatus.WAIT_FILL:
            color = "#f5d742"
        elif view.status == ShooterStatus.WIN:
            color = "#4cef72"
        elif view.status in {ShooterStatus.LOSS, ShooterStatus.TIMEOUT}:
            color = "#ff5f6d"
        self._shooter_status.setStyleSheet(f"color: {color};")
        self._shooter_pnl.setStyleSheet(f"color: {color};")

    def _render_log(self) -> None:
        self._log_panel.setPlainText("\n".join(self._logger.lines()))
