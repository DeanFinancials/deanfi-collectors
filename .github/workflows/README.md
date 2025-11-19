# GitHub Actions Workflows

This directory contains automated workflows for collecting market data and publishing to the [deanfi-data](https://github.com/GibsonNeo/deanfi-data) repository.

## 📋 Workflows Overview

| Workflow | Schedule | Datasets | Runtime | Monthly Hours |
|----------|----------|----------|---------|---------------|
| `daily-news.yml` | Twice daily (9:30am & 4pm ET) | Daily news, Sector news | ~2 min | ~1.5h |
| `analyst-trends.yml` | Weekly (Sun 12pm ET) | Recommendations, Sector trends | ~5 min | ~0.3h |
| `earnings.yml` | Weekly (Sun 12pm ET) | Calendar, Surprises | ~5 min | ~0.3h |
| `market-breadth.yml` | Every 15min (market hours) | A/D, MA%, Highs/Lows | ~3 min | ~30h |
| `major-indexes.yml` | Every 15min (market hours) | US, Sectors, International, Bonds | ~2 min | ~20h |
| `implied-volatility.yml` | Every 15min (market hours) | VIX, Options IV | ~2 min | ~20h |
| `growth-output.yml` | Daily (Mon-Fri 12pm ET) | GDP, Industrial Production, Capacity | ~3 min | ~3h |
| `inflation-prices.yml` | Daily (Mon-Fri 12pm ET) | CPI, PCE, PPI, Breakeven Inflation | ~3 min | ~3h |
| `labor-employment.yml` | Daily (Mon-Fri 12pm ET) | Unemployment, Payrolls, Wages | ~3 min | ~3h |
| `money-markets.yml` | Daily (Mon-Fri 12pm ET) | Fed Funds, Treasuries, Yield Spread | ~3 min | ~3h |
| **TOTAL** | - | **11 categories** | - | **~89 hours** |

## 🔒 Required Secrets

Set these up in: **Settings → Secrets and variables → Actions**

### FINNHUB_API_KEY
- **Get it:** [https://finnhub.io/register](https://finnhub.io/register)
- **Used by:** `daily-news.yml`, `analyst-trends.yml`, `earnings.yml`
- **Rate limits:** 60 calls/minute on free tier

### FRED_API_KEY
- **Get it:** [https://fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)
- **Used by:** `growth-output.yml`, `inflation-prices.yml`, `labor-employment.yml`, `money-markets.yml`
- **Rate limits:** 120 calls/minute on free tier

### DATA_REPO_TOKEN
- **Get it:** [https://github.com/settings/tokens](https://github.com/settings/tokens)
- **Permissions needed:** `repo` (Full control of private repositories)
- **Used by:** All workflows (for pushing to deanfi-data repo)
- **Scopes required:**
  - ✅ `repo` - Full control of private repositories
  - ✅ `workflow` - Update GitHub Actions workflows (optional)

**To create PAT:**
1. Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Name: "deanfi-collectors-automation"
4. Expiration: 90 days (or custom)
5. Select scopes: `repo`
6. Generate token and copy it
7. Add to repository secrets as `DATA_REPO_TOKEN`

## 🚀 Manual Triggers

All workflows can be manually triggered via the GitHub Actions UI:

1. Go to **Actions** tab
2. Select the workflow you want to run
3. Click **Run workflow** button
4. Select branch (main) and click **Run workflow**

This is useful for:
- Testing after initial setup
- Immediate data updates
- Debugging workflow issues

## ⏰ Schedule Details

### High-Frequency (Every 15 minutes)
```yaml
# Runs: 9:30am - 4:15pm ET (market hours)
cron: '*/15 14-21 * * 1-5'
```
- **Workflows:** `market-breadth.yml`, `major-indexes.yml`, `implied-volatility.yml`
- **Runs per day:** 28 (19 intervals from 9:30am-4:15pm)
- **Days per month:** ~22 trading days
- **Total runs:** ~616/month per workflow (~1,848 total)

### Twice Daily (Market open & close)
```yaml
# Market open: 9:30am ET
cron: '30 14 * * 1-5'
# Market close: 4:00pm ET
cron: '0 21 * * 1-5'
```
- **Workflows:** `daily-news.yml`
- **Runs per day:** 2
- **Days per month:** ~22 trading days
- **Total runs:** ~44/month

### Weekly (Sunday noon ET)
```yaml
# Runs: Sunday 12:00pm ET
cron: '0 17 * * 0'
```
- **Workflows:** `analyst-trends.yml`, `earnings.yml`
- **Runs per week:** 1
- **Total runs:** ~4/month per workflow (~8 total)

### Daily Weekdays (Noon ET)
```yaml
# Runs: Mon-Fri 12:00pm ET (17:00 UTC during EST, 16:00 UTC during EDT)
# Note: Adjust for daylight saving time
cron: '0 17 * * 1-5'  # EST
# cron: '0 16 * * 1-5'  # EDT (comment/uncomment as needed)
```
- **Workflows:** `growth-output.yml`, `inflation-prices.yml`, `labor-employment.yml`, `money-markets.yml`
- **Runs per week:** 5 (Mon-Fri)
- **Total runs:** ~20/month per workflow (~80 total)

## 📊 Data Flow

```
┌─────────────────────────────────────────────────────────┐
│  1. GitHub Actions Triggered (schedule or manual)       │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  2. Checkout both repositories                          │
│     - deanfi-collectors (this repo)                     │
│     - deanfi-data (data storage + cache)                │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  3. Set up Python environment                           │
│     - Python 3.11                                       │
│     - Install dependencies (pip cache)                  │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  4. Run collector scripts                               │
│     - Check cache age (market-breadth, major-indexes)   │
│     - Fetch from APIs (Finnhub, Yahoo Finance)          │
│       * Full download OR incremental update             │
│     - Process and validate data                         │
│     - Update cache files (parquet)                      │
│     - Generate JSON outputs                             │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  5. Copy outputs to data repo                           │
│     - Create directories if needed                      │
│     - Copy all generated JSON files                     │
│     - Include updated cache files                       │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  6. Commit and push to deanfi-data                      │
│     - Git pull --rebase (handle concurrent runs)        │
│     - Git add changed files                             │
│     - Commit with timestamp                             │
│     - Push to main branch                               │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  7. Data available via GitHub raw URLs                  │
│     https://raw.githubusercontent.com/...               │
└─────────────────────────────────────────────────────────┘
```

## 🐛 Troubleshooting

### Workflow Failing?

1. **Check the Actions tab** for error messages
2. **Common issues:**
   - Missing or invalid secrets (FINNHUB_API_KEY, DATA_REPO_TOKEN)
   - API rate limits exceeded
   - Network timeouts
   - Python script errors

### Testing Locally

Before committing workflow changes, test scripts locally:

```bash
# Set environment variables
export FINNHUB_API_KEY="your_key"

# Test a collector
cd dailynews
python fetch_top_news.py

# Verify output
cat top_news.json | head -50
```

### Viewing Logs

- Go to **Actions** tab
- Click on a workflow run
- Click on the job name
- Expand steps to see detailed logs

### Debugging

Add debug output to workflows:

```yaml
- name: Debug environment
  run: |
    echo "Working directory: $(pwd)"
    ls -la
    echo "Python version: $(python --version)"
```

## 📈 Performance Optimization

### Pip Dependency Caching
Workflows use GitHub's cache action for pip dependencies:
```yaml
- uses: actions/setup-python@v4
  with:
    cache: 'pip'
```
This speeds up subsequent runs by ~30 seconds.

### Intelligent Data Caching
Market breadth and major indexes workflows use intelligent data caching:
- **Cache location:** `deanfi-data/cache/` (persists across runs)
- **Strategy:**
  - <24h old: Downloads last 5 days only, merges with cache
  - 24h-168h old: Downloads last 10 days only, merges with cache
  - >168h old: Full rebuild of entire dataset
- **Benefits:**
  - Reduces yfinance API calls by ~85%
  - Speeds up workflows by 60-90 seconds
  - More reliable (less API throttling)
  - Cache committed to deanfi-data for persistence

### Concurrency Control
All workflows use concurrency groups to prevent conflicts:
```yaml
concurrency:
  group: deanfi-data-write
  cancel-in-progress: false
```
This ensures only one workflow can push to deanfi-data at a time, preventing git conflicts.

### Parallel Execution
Multiple data fetchers run in sequence within each workflow, but different workflows run in parallel. This maximizes throughput while respecting API rate limits.

### Error Handling
Some collectors use `|| echo "...continuing"` to prevent entire workflow failure if one data source is temporarily unavailable.

## 🔄 Updating Workflows

To modify workflows:

1. **Create a feature branch:**
   ```bash
   git checkout -b fix/update-workflow-schedule
   ```

2. **Edit the workflow file:**
   ```bash
   # Edit .github/workflows/daily-news.yml
   ```

3. **Test manually:**
   - Push to GitHub
   - Go to Actions tab
   - Manually trigger the workflow
   - Verify it works

4. **Create PR and merge**

## 📝 Adding New Workflows

Template for a new workflow:

```yaml
name: New Data Collection

on:
  schedule:
    - cron: '0 22 * * 1-5'
  workflow_dispatch:

env:
  FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
  DATA_REPO: GibsonNeo/deanfi-data
  DATA_REPO_TOKEN: ${{ secrets.DATA_REPO_TOKEN }}

jobs:
  fetch-and-publish:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout collectors repo
        uses: actions/checkout@v4
      
      - name: Checkout data repo
        uses: actions/checkout@v4
        with:
          repository: ${{ env.DATA_REPO }}
          token: ${{ secrets.DATA_REPO_TOKEN }}
          path: data-cache
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
          cache: 'pip'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Fetch data
        run: |
          cd newcollector
          python fetch_new_data.py
      
      - name: Copy to data repo
        run: |
          mkdir -p data-cache/new-category
          cp newcollector/*.json data-cache/new-category/
      
      - name: Commit and push
        run: |
          cd data-cache
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add new-category/
          git diff --staged --quiet || git commit -m "chore: update new data - $(date -u +"%Y-%m-%d")"
          git push
```

## ⚠️ Important Notes

- **Secrets are never exposed in logs** - GitHub automatically redacts them
- **Workflows only run on main branch** unless configured otherwise
- **Forks won't have access to secrets** for security
- **Rate limits apply** - Be mindful of API quotas
- **Workflow run time is limited** - Max 6 hours per workflow run
- **Consider time zones** - Cron runs in UTC, schedule accordingly

## 📚 Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Workflow syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)
- [Cron schedule examples](https://crontab.guru/)
- [Actions marketplace](https://github.com/marketplace?type=actions)
