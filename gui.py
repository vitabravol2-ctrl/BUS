from __future__ import annotations

import tkinter as tk
from pathlib import Path

from logger import RuntimeLogger
from shooter import Config, Shooter
from ws_client import WsClient


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BUS v0.1 — Minimal Spread Shooter")
        self.root.configure(bg="#111")
        self.root.geometry("860x700")

        self.log = RuntimeLogger(Path("logs/runtime.log"))
        self.shooter = Shooter(Config())
        self.ws = WsClient(self.on_ticker, self.on_status)

        self.vars = {k: tk.StringVar(value="-") for k in ["bid", "ask", "spread", "impulse", "position", "entry", "pnl", "hold", "shots", "wins", "losses", "wr", "avg"]}
        self._build()
        self._refresh()

    def _build(self) -> None:
        def label(t, r, c, v=None):
            tk.Label(self.root, text=t, fg="#bbb", bg="#111", font=("Consolas", 13, "bold")).grid(row=r, column=c, sticky="w", padx=8, pady=4)
            if v:
                tk.Label(self.root, textvariable=self.vars[v], fg="#3df", bg="#111", font=("Consolas", 18, "bold")).grid(row=r, column=c + 1, sticky="w")

        for i, (t, v) in enumerate([("BID", "bid"), ("ASK", "ask"), ("SPREAD", "spread"), ("IMPULSE", "impulse"), ("POSITION", "position")]):
            label(t, i, 0, v)
        for i, (t, v) in enumerate([("ENTRY", "entry"), ("CURRENT PNL", "pnl"), ("HOLD MS", "hold"), ("SHOTS", "shots"), ("WINS", "wins"), ("LOSSES", "losses"), ("WINRATE", "wr"), ("AVG PNL", "avg")], start=0):
            label(t, i, 2, v)

        self.inputs = {}
        row = 9
        for key, val in vars(self.shooter.cfg).items():
            tk.Label(self.root, text=key, fg="#bbb", bg="#111").grid(row=row, column=0, sticky="w", padx=8)
            e = tk.Entry(self.root, width=10, bg="#222", fg="#eee", insertbackground="#eee")
            e.insert(0, str(val))
            e.grid(row=row, column=1, sticky="w")
            self.inputs[key] = e
            row += 1

        tk.Button(self.root, text="CONNECT", command=self.connect, bg="#222", fg="#eee").grid(row=9, column=2, padx=4)
        tk.Button(self.root, text="START", command=self.start, bg="#204020", fg="#fff").grid(row=9, column=3, padx=4)
        tk.Button(self.root, text="STOP", command=self.stop, bg="#402020", fg="#fff").grid(row=10, column=2, padx=4)
        tk.Button(self.root, text="PANIC EXIT", command=self.panic, bg="#602020", fg="#fff").grid(row=10, column=3, padx=4)

        self.log_box = tk.Text(self.root, height=14, width=110, bg="#0b0b0b", fg="#8f8", font=("Consolas", 9))
        self.log_box.grid(row=20, column=0, columnspan=4, padx=8, pady=8)

    def _apply_settings(self) -> None:
        cfg = self.shooter.cfg
        for k, e in self.inputs.items():
            cur = getattr(cfg, k)
            setattr(cfg, k, type(cur)(e.get()))

    def connect(self) -> None:
        self.ws.connect()

    def start(self) -> None:
        self._apply_settings()
        self.shooter.start()
        self.log.info("START")

    def stop(self) -> None:
        self.shooter.stop()
        self.log.info("STOP")

    def panic(self) -> None:
        self.log.warn(self.shooter.panic_exit())

    def on_status(self, msg: str) -> None:
        self.log.info(msg)

    def on_ticker(self, tick) -> None:
        msg = self.shooter.on_ticker(tick)
        self.vars["bid"].set(f"{tick.bid:.2f}")
        self.vars["ask"].set(f"{tick.ask:.2f}")
        self.vars["spread"].set(f"{tick.ask - tick.bid:.4f}")
        self.vars["impulse"].set(self.shooter.impulse().value)
        self.vars["position"].set(self.shooter.position.value)
        self.vars["entry"].set(f"{self.shooter.shot.entry:.2f}")
        self.vars["pnl"].set(f"{self.shooter.shot.pnl:.4f}")
        self.vars["hold"].set(str(self.shooter.shot.hold_ms))
        s = self.shooter.stats()
        self.vars["shots"].set(str(s["shots"]))
        self.vars["wins"].set(str(s["wins"]))
        self.vars["losses"].set(str(s["losses"]))
        self.vars["wr"].set(f"{s['winrate']:.1f}%")
        self.vars["avg"].set(f"{s['avg_pnl']:.4f}")
        if msg:
            self.log.info(msg)

    def _refresh(self) -> None:
        self.log_box.delete("1.0", tk.END)
        self.log_box.insert(tk.END, "\n".join(self.log.tail()))
        self.root.after(200, self._refresh)


def run_app() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
