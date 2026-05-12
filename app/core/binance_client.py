from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any

from binance.client import Client


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str, symbol: str = "BTCUSDT") -> None:
        self._client = Client(api_key, api_secret)
        self._symbol = symbol
        self._step_size = self._load_step_size()

    @property
    def symbol(self) -> str:
        return self._symbol

    def _load_step_size(self) -> Decimal:
        info = self._client.get_symbol_info(self._symbol)
        if not info:
            raise RuntimeError(f"Binance symbol not found: {self._symbol}")
        for flt in info.get("filters", []):
            if flt.get("filterType") == "LOT_SIZE":
                return Decimal(flt["stepSize"])
        raise RuntimeError("LOT_SIZE filter missing")

    def _quantize_qty(self, qty: Decimal) -> Decimal:
        return qty.quantize(self._step_size, rounding=ROUND_DOWN)

    def quote_to_base_qty(self, quote_u: float, price: float) -> float:
        raw_qty = Decimal(str(quote_u)) / Decimal(str(price))
        qty = self._quantize_qty(raw_qty)
        if qty <= 0:
            raise RuntimeError("Order quantity is zero after LOT_SIZE quantization")
        return float(qty)

    def place_limit_buy(self, price: float, quote_u: float) -> dict[str, Any]:
        qty = self.quote_to_base_qty(quote_u, price)
        return self._client.create_order(
            symbol=self._symbol,
            side=Client.SIDE_BUY,
            type=Client.ORDER_TYPE_LIMIT,
            timeInForce=Client.TIME_IN_FORCE_GTC,
            quantity=f"{qty:.8f}",
            price=f"{price:.2f}",
        )

    def get_order(self, order_id: int) -> dict[str, Any]:
        return self._client.get_order(symbol=self._symbol, orderId=order_id)

    def market_sell(self, qty: float) -> dict[str, Any]:
        qty_q = self._quantize_qty(Decimal(str(qty)))
        if qty_q <= 0:
            raise RuntimeError("Sell quantity is zero after LOT_SIZE quantization")
        return self._client.create_order(
            symbol=self._symbol,
            side=Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=f"{float(qty_q):.8f}",
        )
