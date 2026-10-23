# MatchOracle — World Cup Probability Analysis

MatchOracle is an open-source football probability analysis prototype. It combines team-strength and goal models with tournament rules, market probabilities, and data-quality checks to explain match forecasts. It is a research and analysis tool, not a betting or wagering product.

**Status:** active prototype. Historical evaluation has identified probability-calibration gaps; forecasts should not be treated as betting advice or as proven to outperform market baselines.

## What it does

- Estimates 90-minute win/draw/loss probabilities and score distributions with a Poisson goal model.
- Models World Cup tournament rules separately from 90-minute match outcomes.
- Supports lineup-impact analysis, tournament-context and upset-risk signals, with confidence affected by data freshness and reliability.
- Converts decimal odds into de-vigged implied probabilities and compares them with model probabilities.
- Provides historical replay, rolling-origin validation, and Brier Score / Log Loss evaluation utilities.
- Includes provider-neutral contracts for importing structured match facts; external credentials are read from environment variables.

## Run locally

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5012`. The repository does not include live match feeds, provider credentials, or local runtime databases. Configure a data provider for live fixtures. Example environment templates are in `deploy/`; copy them to a local file that is not committed, then add your own authorized credentials.

Historical backtests require the included match-result datasets and their source notes in [DATA_SOURCES.md](DATA_SOURCES.md). Elo rating snapshots from international-football.net and local database files are intentionally excluded. Do not commit provider tokens, `.env` files, SQLite databases, or downloaded datasets unless you have verified their redistribution terms.

## Project layout

- `app.py` — Flask application and API routes
- `src/worldcup/` — prediction, tournament, market, data-reliability, and provider modules
- `src/` — model evaluation, calibration, and historical replay tools
- `scripts/` — data validation, worker, and release-readiness utilities
- `tests/` — automated tests
- `data/` — selected public-domain / CC0 historical data and synthetic provider examples

## Data and licensing

The MIT license in this repository applies to the project code only. Included third-party datasets retain their own terms. See [DATA_SOURCES.md](DATA_SOURCES.md) before using, modifying, or redistributing data.

## Contributing

Issues and pull requests are welcome. For model changes, include the evaluation period, pre-match information cutoff, baseline comparison, and calibration metrics. Avoid claims of predictive superiority unless supported by reproducible out-of-sample evidence.
