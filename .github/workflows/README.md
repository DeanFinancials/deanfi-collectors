# GitHub Actions Workflows

This directory contains automated workflows for collecting market data and publishing to the [deanfi-data](https://github.com/GibsonNeo/deanfi-data) repository.

## 📋 Workflows Overview

| Workflow | Schedule | Datasets | Runtime | Monthly Hours |
|----------|----------|----------|---------|---------------|
| `market-data-10min.yml` | Every 10 min (8:05am–4:55pm ET) | Breadth, major indexes, implied vol, mean reversion | ~4 min | ~90h |
| `daily-news.yml` | Twice daily (9:30am & 4pm ET) | Daily news, Sector news | ~2 min | ~1.5h |
| `analyst-trends.yml` | Weeknights 10:00pm ET (Tue–Sat UTC) | Recommendations, sector trends | ~10 min | ~4h |
| `earnings-calendar.yml` | Weeknights 10:45pm ET (Tue–Sat UTC) | Earnings calendar | ~20 min | ~7h |
| `earnings-surprises.yml` | Weeknights 11:05pm ET (Tue–Sat UTC) | Earnings surprises | ~20 min | ~7h |
| `sp100-growth.yml` | Weeknights 11:15pm ET (Tue–Sat UTC) | SP100 revenue & EPS growth | ~8 min | ~3h |
| `economy-indicators.yml` | Weekdays 8:00am & 12:00pm ET | Growth, inflation, labor, money markets | ~6 min | ~11h |
| **TOTAL** | - | **7 workflows** | - | **~125 hours** |

## 🔒 Required Secrets

Set these up in: **Settings → Secrets and variables → Actions**

### FINNHUB_API_KEY
- **Get it:** [https://finnhub.io/register](https://finnhub.io/register)
- **Used by:** `daily-news.yml`, `analyst-trends.yml`, `earnings-calendar.yml`, `earnings-surprises.yml`
- **Rate limits:** 60 calls/minute on free tier

### FRED_API_KEY
- **Get it:** [https://fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)
- **Used by:** `economy-indicators.yml`
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

### High-Frequency (Every 10 minutes)
```yaml
# Runs: 8:05am - 4:55pm ET with a 5-minute offset to avoid top-of-hour congestion
cron: '5-55/10 13-21 * * 1-5'   # EST (roughly Nov–Mar)
# cron: '5-55/10 12-20 * * 1-5' # EDT (roughly Mar–Nov)
```
- **Workflow:** `market-data-10min.yml`
- **Runs per day:** 54 (10-minute cadence across 9 trading hours)
- **Days per month:** ~22 trading days
- **Total runs:** ~1,188/month

### Twice Daily (Market open & close)
```yaml
# Market open: 9:30am ET
cron: '30 14 * * 1-5'
# Market close: 4:00pm ET
cron: '0 21 * * 1-5'
```
- **Workflow:** `daily-news.yml`
- **Runs per day:** 2
- **Days per month:** ~22 trading days
- **Total runs:** ~44/month

### Weeknights (Nightly Finnhub Collectors)
```yaml
# Analyst trends: 10:00pm ET (03:00 UTC Tue-Sat)
cron: '0 3 * * 2-6'

# Earnings calendar: 10:45pm ET (03:45 UTC Tue-Sat)
cron: '45 3 * * 2-6'

# Earnings surprises: 11:05pm ET (04:05 UTC Tue-Sat)
cron: '5 4 * * 2-6'
```
- **Workflows:** `analyst-trends.yml`, `earnings-calendar.yml`, `earnings-surprises.yml`
- **Runs per week:** 5 per workflow (Sunday–Thursday evenings, executed Tue–Sat UTC)
- **Total runs:** ~20/month per workflow (~60 total)
- **Operational note:** The earnings pipeline is split into two nightly workflows so a long-running calendar fetch cannot block earnings surprises publication, and each dataset updates its own `data_freshness.json` section independently.

### Weekday Economy Windows (8:00am & 12:00pm ET)
```yaml
# Morning window: 8:00am ET (13:00 UTC EST / 12:00 UTC EDT)
cron: '0 13 * * 1-5'
# cron: '0 12 * * 1-5'

# Midday window: 12:00pm ET (17:00 UTC EST / 16:00 UTC EDT)
cron: '0 17 * * 1-5'
# cron: '0 16 * * 1-5'
```
- **Workflow:** `economy-indicators.yml`
- **Runs per week:** 10 (two per trading day)
- **Total runs:** ~40/month

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
│     - Check cache age (market-data collectors)          │
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
  group: deanfi-data-repo
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
