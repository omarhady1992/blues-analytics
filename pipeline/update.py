"""One command to run after every match:

    python -m pipeline.update            # fetch new finished matches, rebuild reports + site JSON
    python -m pipeline.update --refresh  # re-download everything (e.g. if a source corrected stats)
    python -m pipeline.update --refresh-match 9   # re-download one match (our match_id)
    python -m pipeline.update --offline  # no network: rebuild DB/reports/site from data/raw cache
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from . import buildup, db, export, ingest, reports
from .sources import fotmob, premier_league as pl, understat

# Wait a bit after full time so sources have published final numbers
SETTLE_HOURS = 3


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-download every match")
    ap.add_argument("--refresh-match", type=int, action="append", default=[], help="re-download one match_id")
    ap.add_argument("--offline", action="store_true", help="use cached raw JSON only")
    args = ap.parse_args(argv)
    live = not args.offline

    con = db.connect()
    print("1/4 Fetching fixture lists and squad ...")
    fm_team = fotmob.team(refresh=live)
    pl_matches = pl.season_matches(refresh=live)
    try:  # Understat is optional: if it is down, keep going with the cached copy
        us_team = understat.team(refresh=live)
    except Exception as e:
        print(f"   ! Understat team data unavailable ({e}); using cache, new matches get no Understat xG")
        us_team = understat.team(refresh=False)
    try:  # league data carries Understat's per-match PPDA; never let it block an update
        us_league = understat.league(refresh=live)
    except Exception as e:
        print(f"   ! Understat league data unavailable ({e}); using cache if present")
        try:
            us_league = understat.league(refresh=False)
        except Exception:
            us_league = None
    ingest.sync_pl_squad(con, pl.squad(refresh=live))
    con.commit()

    print("2/4 Ingesting finished matches ...")
    now = datetime.now(timezone.utc)
    new, skipped = [], []
    for fx in ingest.competitive_fixtures(fm_team):
        st = fx["status"]
        if not st.get("finished"):
            continue
        kickoff = ingest.to_utc(st["utcTime"])
        if now - kickoff < timedelta(hours=SETTLE_HOURS):
            skipped.append(fx["id"])
            continue
        existing = db.entity_for(con, "match", "fotmob", fx["id"])
        refresh = args.refresh or (existing in args.refresh_match)
        if existing and not refresh and not args.offline:
            continue
        label = f"{st['utcTime'][:10]} {fx['home']['name']} {st.get('scoreStr')} {fx['away']['name']} ({fx['tournament']['name']})"
        try:
            mid = ingest.ingest_match(con, fx, pl_matches, us_team, refresh=refresh and live)
            con.commit()
            new.append(mid)
            print(f"   ✓ [{mid}] {label}")
        except Exception as e:  # keep going; report the failure
            con.rollback()
            print(f"   ✗ {label}: {e}")
    if skipped:
        print(f"   (waiting for {len(skipped)} just-finished match(es) to settle; rerun in a few hours)")

    print("3/4 Computing build-up & pressing metrics, writing reports ...")
    buildup.build_all(con, us_league)
    reports.build_all(con)
    print("4/4 Exporting site JSON ...")
    export.build_all(con)
    try:  # season analysis page + elite comparison (uses cached league data; refresh with --refresh)
        from . import season_analysis
        season_analysis.build(refresh=False)
    except Exception as e:
        print(f"   ! season analysis not rebuilt: {e}")
    n = con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    calls = fotmob.client.network_calls + pl.client.network_calls + understat.client.network_calls
    print(f"Done. {len(new)} match(es) (re)ingested, {n} in database, {calls} network calls.")


if __name__ == "__main__":
    main()
