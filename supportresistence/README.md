# Support / Resistence Collector

Generates daily **support/resistance levels** for key index ETFs using the **Alpaca Market Data API**.

Outputs (gitignored) a single JSON snapshot containing:
- Traditional (floor trader) pivots: `P, R1, R2, S1, S2`
- Fibonacci pivots: `FP, FR1, FR2, FS1, FS2`
- Simple moving averages: `SMA20, SMA50, SMA200`

## Configuration

Edit `config.yml` to change tickers, bar lookback, and output file name.

## Environment Variables

This collector uses Alpaca authentication headers.

Set one of each:
- `ALPACA_API_KEY` (or `APCA-API-KEY-ID`)
- `ALPACA_API_SECRET` (or `APCA-API-SECRET-KEY`)

Optional:
- `ALPACA_DATA_URL` (defaults to `https://data.alpaca.markets`)

Important:
- This collector uses **Alpaca Market Data** (`https://data.alpaca.markets`) for bars.
- The paper trading base URL (`https://paper-api.alpaca.markets/v2`) is for **trading/account** APIs, not historical bars.
- Don’t paste API secrets into chat or commit them to git; prefer env vars or GitHub Actions secrets.

## Run

```bash
cd deanfi-collectors/supportresistence
python fetch_support_resistence.py
```

You can also override:

```bash
python fetch_support_resistence.py --config config.yml --output support_resistence.json
```
