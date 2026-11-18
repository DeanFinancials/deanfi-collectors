# Housing & Affordability Collector

FRED-based export of U.S. housing activity, price, mortgage, and affordability metrics. Outputs a structured JSON with inline documentation (`_README`) plus metadata, current graded readings, and resampled history for charting.

## Indicators

- `HOUST` – Housing starts (SAAR, thousands)
- `PERMIT` – Building permits (SAAR, thousands)
- `HSN1F` – New one-family houses sold (SAAR, thousands)
- `EXHOSLUSM495S` – Existing single-family home sales (SAAR, thousands)
- `CSUSHPINSA` – S&P/Case-Shiller U.S. National Home Price Index (NSA)
- `MORTGAGE30US` – 30-year fixed mortgage rate (NSA, weekly)
- `MORTGAGE15US` – 15-year fixed mortgage rate (NSA, weekly)
- `TDSP` – Household debt service ratio (SA, quarterly)
- `MDSP` – Mortgage debt service ratio (SA, quarterly)
- `T10YIE` – 10-year breakeven inflation rate (NSA, daily)

> Note: The NAHB/Wells Fargo Housing Market Index (`HMI`) is excluded because the series is not available via FRED.

## Methodology

- **Lookback:** 20 years (7,300 days) to compute robust percentiles and grades.
- **Grading:** Percentile-based letter grades respect each indicator's interpretation (`higher_is_better`, `lower_is_better`, or `neutral`).
- **Trend/Changes:** Includes trend direction and multi-horizon percentage changes (1y/5y/10y/20y where applicable).
- **Resampling:** Uses adaptive resampling per frequency to store history compactly for downstream charting.

## Output Structure

- `_README`: Human-readable documentation (title, description, purposes, metric explanations, trading applications, notes).
- `metadata`: Generation timestamp, source, indicator list, lookback window, date range.
- `current`: Latest date, overall grade, per-indicator values, percentiles, grades, trends, change metrics, interpretations.
- `history`: Resampled historical series with `dates[]` and `values[]` per indicator.

## Running Locally

```bash
cd housingaffordability
python fetch_housing_affordability.py --output housing_affordability.json
```

- Configure FRED access via environment variable `FRED_API_KEY`.
- Optional: `--config` to point to a custom `config.yml`; `--output` to change the target JSON path.

## Update Frequency

Runs twice each weekday in `economy-indicators.yml` with the other FRED collectors (see `docs/workflows.md`).

## Data Source

- Federal Reserve Economic Data (FRED) API
