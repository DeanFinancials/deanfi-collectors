# Contributing

Thanks for your interest. This repository runs the DeanFi data collectors; issues and pull requests are welcome.

## Set up

```bash
git clone https://github.com/<your-fork>/deanfi-collectors.git
cd deanfi-collectors
pip install -r requirements.txt
```

Collectors need the API keys listed in [docs/workflows.md](../docs/workflows.md#secrets-and-variables). Finnhub and FRED offer free keys; yfinance-based collectors need none. See [docs/collectors.md](../docs/collectors.md#running-a-collector-locally) for running one.

## Make a change

1. Branch from `main`.
2. Follow [docs/requirements.md](../docs/requirements.md) and the existing patterns in the collector you touch.
3. Run the tests: `python3 -m pytest -q` (and `node --test scheduler/next-run.test.mjs` if you touch `scheduler/`).
4. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages and the PR title, for example `fix(majorindexes): skip null closes`.
5. Open a pull request describing what changed, why, and how you tested it. Include a sample of any new or changed JSON output.

`ci.yml` runs the same suites (plus `python3 -m pytest -q dailynews/tests`) on every push and pull request, forks included; it needs no secrets. Forks do not receive this repository's secrets, so workflows that publish to `deanfi-data` will not run from a fork.

## Rules that matter most

- Never commit API keys or `.env` files. Read secrets from environment variables.
- Do not change a published JSON field's name or shape without saying so in the PR; the website reads these files.
- Report security problems privately as described in [SECURITY.md](../SECURITY.md), not in an issue.

By contributing you agree that your contributions are licensed under the MIT License.
