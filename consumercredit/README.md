# Consumer & Credit Collector

Daily FRED-based export of U.S. consumer sentiment, spending, saving, and credit balance indicators. Outputs a structured JSON with inline documentation (`_README`) plus metadata, current graded readings, and resampled history for charting.

## Indicators

- `UMCSENT` – University of Michigan consumer sentiment (NSA)
- `CONCCONF` – Conference Board consumer confidence (NSA, fallback to OECD CSCICP03USM665S when unavailable)
- `RSAFS` – Advance retail and food services sales (SA, nominal)
- `RRSFS` – Real retail and food services sales (SA, chained 2017 dollars)
- `RSXFS` – Retail sales ex autos (SA, nominal)
- `PCE` – Personal consumption expenditures (SAAR, nominal)
- `PCEC96` – Real personal consumption expenditures (SAAR, chained 2017 dollars)
- `PSAVERT` – Personal saving rate (SA, % of DPI)
- `TOTALSL` – Total consumer credit outstanding (SA)
- `REVOLSL` – Revolving consumer credit (SA)
- `NONREVSL` – Nonrevolving consumer credit (SA)
- `BAMLH0A0HYM2` – ICE BofA US High Yield Index option-adjusted spread (Daily, credit stress proxy)

## Methodology

- **Lookback:** 20 years (7,300 days) to compute robust percentiles and grades.
- **Grading:** Percentile-based letter grades respect each indicator's interpretation (`higher_is_better`, `lower_is_better`, or `neutral`).
- **Trend/Changes:** Includes trend direction and multi-horizon percentage changes (1y/5y/10y/20y where applicable).
- **Resampling:** Uses adaptive resampling per frequency to store history compactly for downstream charting.
- **Fallback:** `CONCCONF` falls back to OECD consumer confidence (`CSCICP03USM665S`) if the Conference Board series is unavailable.

## Output Structure

- `_README`: Human-readable documentation (title, description, purposes, metric explanations, trading applications, notes).
- `metadata`: Generation timestamp, source, indicator list, lookback window, date range.
- `current`: Latest date, overall grade, per-indicator values, percentiles, grades, trends, change metrics, interpretations.
- `history`: Resampled historical series with `dates[]` and `values[]` per indicator.

## Running Locally

```bash
cd consumercredit
python fetch_consumer_credit.py --output consumer_credit.json
```

- Configure FRED access via environment variable `FRED_API_KEY`.
- Optional: `--config` to point to a custom `config.yml`; `--output` to change the target JSON path.

## Update Frequency

Intended to run daily around 12:00 PM ET alongside other economy collectors.

## Data Source

- Federal Reserve Economic Data (FRED) API
