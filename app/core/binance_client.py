from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any

from binance.client import Client




@dataclass(slots=True)
class BalanceSnapshot:
    base_asset: str
    base_free: float
    quote_asset: str
    quote_free: float
    usdt_free: float

@dataclass(slots=True)
class FilterCheckResult:
    qty: float
    price: float
    error: str = ""


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str, symbol: str = "BTCUSDT") -> None:
        self._client = Client(api_key, api_secret)
        self._symbol = symbol
        self._step_size = Decimal("0.000001")
        self._min_qty = Decimal("0")
        self._min_notional = Decimal("0")
        self._tick_size = Decimal("0.01")
        self.load_filters()

    def load_filters(self) -> None:
        info = self._client.get_symbol_info(self._symbol)
        if not info:
            raise RuntimeError(f"Binance symbol not found: {self._symbol}")
        for flt in info.get("filters", []):
            f_type = flt.get("filterType")
            if f_type == "LOT_SIZE":
                self._step_size = Decimal(flt["stepSize"])
                self._min_qty = Decimal(flt["minQty"])
            elif f_type in {"MIN_NOTIONAL", "NOTIONAL"}:
                self._min_notional = Decimal(flt.get("minNotional", flt.get("notional", "0")))
            elif f_type == "PRICE_FILTER":
                self._tick_size = Decimal(flt["tickSize"])

    def _floor_to_step(self, value: Decimal, step: Decimal) -> Decimal:
        return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

    def prepare_limit_buy(self, price: float, quote_u: float) -> FilterCheckResult:
        price_d = self._floor_to_step(Decimal(str(price)), self._tick_size)
        raw_qty = Decimal(str(quote_u)) / price_d
        qty_d = self._floor_to_step(raw_qty, self._step_size)
        if qty_d < self._min_qty:
            return FilterCheckResult(qty=0.0, price=float(price_d), error="FILTER_FAIL_LOT_SIZE")
        if (qty_d * price_d) < self._min_notional:
            return FilterCheckResult(qty=float(qty_d), price=float(price_d), error="FILTER_FAIL_MIN_NOTIONAL")
        return FilterCheckResult(qty=float(qty_d), price=float(price_d))

    def place_limit_buy_prepared(self, prepared: FilterCheckResult) -> dict[str, Any]:
        return self._client.create_order(
            symbol=self._symbol,
            side=Client.SIDE_BUY,
            type=Client.ORDER_TYPE_LIMIT,
            timeInForce=Client.TIME_IN_FORCE_GTC,
            quantity=f"{prepared.qty:.8f}",
            price=f"{prepared.price:.2f}",
        )

    def get_order(self, order_id: int) -> dict[str, Any]:
        return self._client.get_order(symbol=self._symbol, orderId=order_id)

    def cancel_order(self, order_id: int) -> dict[str, Any]:
        return self._client.cancel_order(symbol=self._symbol, orderId=order_id)

    def market_sell(self, qty: float) -> dict[str, Any]:
        qty_q = self._floor_to_step(Decimal(str(qty)), self._step_size)
        if qty_q <= 0:
            raise RuntimeError("Sell quantity is zero after LOT_SIZE quantization")
        return self._client.create_order(
            symbol=self._symbol,
            side=Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=f"{float(qty_q):.8f}",
        )

    def _get_symbol_assets(self) -> tuple[str, str]:
        info = self._client.get_symbol_info(self._symbol)
        if not info:
            raise RuntimeError(f"Binance symbol not found: {self._symbol}")
        return str(info.get("baseAsset", "BTC")), str(info.get("quoteAsset", "USDT"))

    def get_balance_snapshot(self) -> BalanceSnapshot:
        account = self._client.get_account()
        balances = {item.get("asset"): float(item.get("free", 0.0)) for item in account.get("balances", [])}
        base_asset, quote_asset = self._get_symbol_assets()
        return BalanceSnapshot(
            base_asset=base_asset,
            base_free=balances.get(base_asset, 0.0),
            quote_asset=quote_asset,
            quote_free=balances.get(quote_asset, 0.0),
            usdt_free=balances.get("USDT", 0.0),
        )

    def get_balances(self) -> dict[str, Any]:
        return self._client.get_account()
