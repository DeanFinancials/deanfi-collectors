# Earnings Workflow Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic nightly earnings workflow with two independent workflows so `earnings-calendar` and `earnings-surprises` publish reliably and update downstream freshness independently.

**Architecture:** Delete the old `.github/workflows/earnings.yml` workflow and replace it with two single-purpose workflow files that each run one Finnhub collector, publish one dataset into `deanfi-data`, and update one `data_freshness.json` section. Update workflow docs so operations and incident response point to the new split topology.

**Tech Stack:** GitHub Actions YAML, Python collectors, git-based publish to `deanfi-data`, Markdown docs

---

### Task 1: Add focused workflow coverage for the split topology

**Files:**
- Create: `.github/workflows/earnings-calendar.yml`
- Create: `.github/workflows/earnings-surprises.yml`
- Delete: `.github/workflows/earnings.yml`

- [ ] **Step 1: Write the failing checks**

Add a temporary local validation target by asserting the old and new workflow filenames from the repo root:

```bash
test -f .github/workflows/earnings.yml
test ! -f .github/workflows/earnings-calendar.yml
test ! -f .github/workflows/earnings-surprises.yml
```

- [ ] **Step 2: Run the checks to verify the pre-change state**

Run:

```bash
test -f .github/workflows/earnings.yml && \
test ! -f .github/workflows/earnings-calendar.yml && \
test ! -f .github/workflows/earnings-surprises.yml
```

Expected: exit `0`, proving the repo still has the monolithic workflow only.

- [ ] **Step 3: Write the minimal implementation**

Create `.github/workflows/earnings-calendar.yml` with this shape:

```yaml
name: Earnings Calendar Collection

on:
  schedule:
    - cron: '45 3 * * 2-6'
  workflow_dispatch:

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"
  FINNHUB_API_KEY: "${{ secrets.FINNHUB_API_KEY }}"
  DATA_REPO: "${{ github.repository_owner }}/deanfi-data"
  DATA_REPO_TOKEN: "${{ secrets.DATA_REPO_TOKEN }}"

jobs:
  fetch-and-publish:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    concurrency:
      group: deanfi-data-repo
      cancel-in-progress: false
    steps:
      - name: Checkout collectors repo
        uses: actions/checkout@v5
      - name: Checkout data repo
        uses: actions/checkout@v5
        with:
          repository: ${{ env.DATA_REPO }}
          token: ${{ secrets.DATA_REPO_TOKEN }}
          path: data-cache
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: '3.11'
          cache: 'pip'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Fetch earnings calendar
        run: |
          cd earningscalendar
          python fetch_earnings_calendar.py
      - name: Copy to data repo
        run: |
          mkdir -p data-cache/earnings-calendar
          cp earningscalendar/earnings_calendar.json data-cache/earnings-calendar/
      - name: Update data freshness
        run: |
          python3 << 'EOF'
          import json
          from datetime import datetime, timezone
          from pathlib import Path

          now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
          fp = Path('data-cache/data_freshness.json')
          data = json.loads(fp.read_text()) if fp.exists() else {"sections": {}}
          data.setdefault("sections", {})["earnings-calendar"] = {"last_updated": now}
          fp.write_text(json.dumps(data, indent=2))
          EOF
      - name: Commit and push
        run: |
          cd data-cache
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add earnings-calendar/ data_freshness.json
          if git diff --staged --quiet; then
            echo "No changes to commit"
          else
            git commit -m "chore: update earnings calendar - $(date -u +"%Y-%m-%d")"
            git pull --rebase origin main
            git push
          fi
```

Create `.github/workflows/earnings-surprises.yml` with the same skeleton but:

```yaml
name: Earnings Surprises Collection
```

and:

```yaml
schedule:
  - cron: '5 4 * * 2-6'
```

and:

```yaml
timeout-minutes: 20
```

and the collector/publish scope changed to:

```yaml
cd earningssurprises
python fetch_earnings_surprises.py
mkdir -p data-cache/earnings-surprises
cp earningssurprises/earnings_surprises.json data-cache/earnings-surprises/
git add earnings-surprises/ data_freshness.json
git commit -m "chore: update earnings surprises - $(date -u +"%Y-%m-%d")"
```

with only this freshness update:

```python
data.setdefault("sections", {})["earnings-surprises"] = {"last_updated": now}
```

Delete `.github/workflows/earnings.yml`.

- [ ] **Step 4: Run checks to verify the workflow split exists**

Run:

```bash
test ! -f .github/workflows/earnings.yml && \
test -f .github/workflows/earnings-calendar.yml && \
test -f .github/workflows/earnings-surprises.yml
```

Expected: exit `0`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/earnings-calendar.yml .github/workflows/earnings-surprises.yml .github/workflows/earnings.yml
git commit -m "fix: split earnings collectors into independent workflows"
```

### Task 2: Update workflow documentation and operator references

**Files:**
- Modify: `.github/workflows/README.md`

- [ ] **Step 1: Write the failing checks**

Capture the old workflow references:

```bash
rg -n "earnings\.yml|Earnings Collection|analyst-trends\.yml|earnings.yml" .github/workflows/README.md
```

- [ ] **Step 2: Run the checks to verify the old references exist**

Run:

```bash
rg -n "earnings\.yml|Earnings Collection" .github/workflows/README.md
```

Expected: at least one match referencing the old workflow.

- [ ] **Step 3: Write the minimal implementation**

Update `.github/workflows/README.md` so the workflow inventory and any supporting prose refer to:

```markdown
| `earnings-calendar.yml` | Weeknights 11:45pm ET (Tue–Sat UTC) | Earnings calendar | ~10 min | ~1 day |
| `earnings-surprises.yml` | Weeknights 12:05am ET (Tue–Sat UTC) | Earnings surprises | ~10 min | ~1 day |
```

Replace any prose that implies a single earnings workflow with wording that states:

```markdown
The earnings data pipeline is split into two nightly workflows so a long-running calendar fetch cannot block earnings surprises publication, and each dataset updates its own `data_freshness.json` section independently.
```

- [ ] **Step 4: Run checks to verify the new references**

Run:

```bash
rg -n "earnings-calendar\.yml|earnings-surprises\.yml|split into two nightly workflows" .github/workflows/README.md && \
! rg -n "earnings\.yml" .github/workflows/README.md
```

Expected: matches for the new workflow names and no match for `earnings.yml`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/README.md
git commit -m "docs: update workflow docs for split earnings collectors"
```

### Task 3: Verify no misleading repo references remain and validate the new YAML

**Files:**
- Test: `.github/workflows/earnings-calendar.yml`
- Test: `.github/workflows/earnings-surprises.yml`
- Test: repo-wide workflow references

- [ ] **Step 1: Write the failing checks**

Plan to fail if old references remain or if YAML parsing breaks:

```bash
rg -n "earnings\.yml" . || true
python - <<'PY'
import sys, yaml
for path in [
    '.github/workflows/earnings-calendar.yml',
    '.github/workflows/earnings-surprises.yml',
]:
    with open(path, 'r', encoding='utf-8') as fh:
        yaml.safe_load(fh)
print('yaml-ok')
PY
```

- [ ] **Step 2: Run the checks to verify they catch the pre-fix issues**

Run the reference scan before cleanup is complete:

```bash
rg -n "earnings\.yml" .
```

Expected: any remaining matches are intentional references in the design/plan docs or stale operator docs that must be reviewed.

- [ ] **Step 3: Write the minimal implementation**

If repo-wide matches outside the new spec/plan docs remain, update those files so operational guidance points to the new split workflow names. Do not scrub historical references inside the dated design and plan docs where `earnings.yml` is part of the recorded incident context.

- [ ] **Step 4: Run the final verification**

Run:

```bash
python - <<'PY'
import yaml
for path in [
    '.github/workflows/earnings-calendar.yml',
    '.github/workflows/earnings-surprises.yml',
]:
    with open(path, 'r', encoding='utf-8') as fh:
        yaml.safe_load(fh)
print('yaml-ok')
PY
```

Run:

```bash
rg -n "earnings\.yml" .github docs README.md AGENTS.md || true
```

Expected:

- YAML parser prints `yaml-ok`
- no misleading references to the removed workflow remain in operator-facing docs

- [ ] **Step 5: Commit**

```bash
git add .github docs README.md AGENTS.md
git commit -m "chore: verify split earnings workflow references"
```
