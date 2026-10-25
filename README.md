# Blues Analytics

Match-by-match performance analytics for **Chelsea FC's men's first team, season 2026-27**.
It's a hobby project and a playground for practising Python, SQL, Pandas, machine learning, Tableau and dashboard design.

**Live site:** https://omarhady1992.github.io/blues-analytics/

The site has:

- **Overview:** record, form, next fixtures, xG trends.
- **Squad:** a sortable, filterable player table with totals or per-90 values, filtered by competition.
- **Player pages:** match-by-match charts, a percentile radar against the rest of the squad, and a match log.
- **Matches:** a page per match with team stats, a shot map and the standout performers.
- **Reports:** an automatic report for every match, monthly reports, and a season review (a placeholder for now).

## Architecture

```
 sources (HTTP)                  pipeline (Python)                    outputs
 ─────────────────               ─────────────────────                ──────────────────────────
 Premier League API (Opta) ─┐
 FotMob                     ├─► http.py  cache ► data/raw/*.json      (git-ignored)
 Understat                  ┘        │
                                     ▼
                                ingest.py  ─────► data/blues.db       SQLite (git-ignored, rebuildable)
                                     │             schema: pipeline/schema.sql
                                     ▼
                         analysis.py (pandas)
                          ├─ reports.py ─────────► site/data/reports/**.md
                          └─ export.py  ─────────► site/data/*.json   (processed numbers only)
                                                         │
                                  GitHub Actions ◄───────┘  (.github/workflows/pages.yml)
                                         └──► GitHub Pages (static site: site/index.html + js/app.js)
```

| Module | What it does |
|---|---|
| `pipeline/config.py` | Every setting in one place: season, team ids, time zone, rate limit. |
| `pipeline/http.py` | HTTP client with an on-disk JSON cache, per-host rate limiting (1.2 s between calls) and retries. |
| `pipeline/sources/*.py` | One small module per source. They only fetch and return raw JSON. |
| `pipeline/ingest.py` | Maps the raw JSON to our tables and links each player and match across the three sources. |
| `pipeline/schema.sql` | The SQLite schema: tables, a long-format table of raw stats, and a view. |
| `pipeline/buildup.py` | Build-up & pressing metrics (PPDA, long-ball share, goalkeeper distribution, by-unit progression), recomputed from the cached raw files on every run. |
| `pipeline/analysis.py` | Loads the database into Pandas, plus per-90 helpers. |
| `pipeline/reports.py` | Writes the data-driven match, monthly and season reports in Markdown. |
| `pipeline/export.py` | Writes the JSON files the website reads. |
| `pipeline/update.py` | The one command you run after each match. |
| `site/` | Plain HTML/CSS/JS with Chart.js and marked.js from a CDN, an SVG shot map and hash routing. There is no build step. |

### Data sources (and who provides what)

| Source | Used for | Notes |
|---|---|---|
| **Premier League API** (`sdp-prem-prod.premier-league-prod.pulselive.com`), Opta data | Player and team stats for Premier League matches (about 100 Opta fields per player), and the squad list | Undocumented public API. Premier League matches only. |
| **FotMob** (`fotmob.com/api/data`) | The fixture list for every competition, player and team stats for cup matches, ratings, physical data (distance, sprints, top speed), shot maps | Needs a browser-like TLS fingerprint, which `curl_cffi` provides. |
| **Understat** (`understat.com/getMatchData`) | Shot-level xG from Understat's own model, and per-match PPDA from `getLeagueData` (Premier League only) | Shown as a second xG opinion next to the Opta numbers. |

The sources are linked through the `source_ids` table. FotMob exposes each player's Opta id, so FotMob and Premier League players match exactly. Understat players are matched by name.

**Data rules**
- `NULL` means the source did not provide the number. It is never treated as 0.
- Only processed and aggregated numbers are published. Raw responses stay in `data/raw/`, which is git-ignored.
- Reports state only what the data shows.

### Database tables

`players`, `matches`, `team_match_stats` (one row each for Chelsea and the opponent), `player_match_stats` (one row per player per match, with unified columns), `player_match_stats_long` (every numeric stat the sources gave, in long format), `shots` (x and y normalised to 0–1, with the shooting team attacking towards x = 1), `source_ids`, `team_match_buildup` (build-up & pressing per match and side), `team_match_buildup_units` (Chelsea passing by unit), and the view `v_player_season`. See `pipeline/schema.sql`, and `sql/examples.sql` for practice queries.

## How to run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m pipeline.update                 # fetch new finished matches, rebuild DB rows, reports and site JSON
python -m pipeline.update --refresh-match 9   # re-download one match (our match_id) if a source corrected stats
python -m pipeline.update --refresh       # re-download everything
python -m pipeline.update --offline       # no network: rebuild from the data/raw cache

python -m http.server -d site 8000        # preview the site at http://localhost:8000
git add site && git commit -m "Update after <match>" && git push   # GitHub Actions redeploys the site
```

`update` waits until 3 hours after kick-off before ingesting a match, so the sources have time to publish final numbers. Matches already in the database are skipped. The first run downloads about 200 requests (roughly 4 minutes because of the rate limit). Each later match takes about 25 requests.

## Roadmap (exercises)

- [x] v1: data pipeline, SQLite database, automatic reports, interactive site
- [x] Build-up & pressing: PPDA, long-ball share, goalkeeper distribution, progression by unit
- [ ] **Pandas/SQL:** rolling 5-match xG trends, home vs away splits, results by formation.
- [ ] **ML 1, clustering:** group players into roles (K-means or a Gaussian mixture on per-90 profiles). Check whether the clusters match the listed positions.
- [ ] **ML 2, match rating model:** predict FotMob ratings from Opta stats (linear regression, then gradient boosting with SHAP) to see which stats drive the ratings.
- [ ] **ML 3, xG model:** train a shot xG model on Understat shot coordinates and situations, then compare it with Understat and Opta. StatsBomb open data can supply more training shots.
- [ ] **ML 4, outcome model:** predict results from pre-match form features. Be honest about the small sample.
- [ ] **Tableau:** export `player_match_stats` to CSV, build a Tableau Public dashboard, and embed it on a new site page.
- [ ] Season review page with season-long charts (end of season).
- [ ] Opponent comparison: fetch both teams' player data.

Put your notebooks in `notebooks/` (see `notebooks/README.md`).

## Disclaimer

This is an unofficial fan project and is not affiliated with Chelsea FC, the Premier League, Opta/Stats Perform, FotMob or Understat. It uses public, undocumented endpoints with gentle rate limits for personal, non-commercial analysis. The data belongs to its owners.
