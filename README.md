# BUS BTCU Spread Shooter v0.1.0

Ultra-light realtime BTCU spread monitor.

## Run

```bash
python main.py
```

## Architecture

- `main.py`
- `app/core/ws_client.py`
- `app/core/market_state.py`
- `app/core/logger.py`
- `app/gui/main_window.py`

## Stream

- `wss://stream.binance.com:9443/ws/btcu@bookTicker`
