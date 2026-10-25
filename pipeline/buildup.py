"""Build-up & pressing metrics (table team_match_buildup + team_match_buildup_units).

Recomputed from the cached raw source files on every `python -m pipeline.update`,
so new matches get them automatically and a formula change backfills everything.

Metrics and sources
-------------------
PPDA (passes allowed per defensive action) - lower = more aggressive pressing.
  * `ppda`: Understat's event-based PPDA (computed by Understat from Opta event
    coordinates; their glossary: "passes allowed per defensive action in the
    opposition half"). Premier League only. We store Understat's numerator
    (`ppda_opp_passes`) and denominator (`ppda_def_actions`) too.
  * `ppda_proxy`: a whole-pitch approximation for every match (incl. cups) from FotMob
    team totals: other team's accurate own-half passes / (this side's tackles +
    interceptions + fouls, anywhere on the pitch). FotMob gives no zone split for
    defensive actions, so this is NOT on the same scale as `ppda`; use it for the
    trend shape and for cup matches only.
Passing style (both sides)
  * long_ball_share = long balls / passes; long_ball_accuracy = accurate / long balls.
    Opta team stats (totalLongBalls, accurateLongBalls, totalPass) for PL matches,
    FotMob team stats ("Accurate long balls" x/y, "Passes") for cups.
  * long_own_to_opp: Opta longPassOwnToOpp (long passes from own half into the opposition half), PL only.
  * final_third_entries: Opta team finalThirdEntries (PL); cups: sum of FotMob "passes into final third".
  * line_breaking_passes: sum of FotMob player "line-breaking passes" (FotMob does not publish them for cups).
Goalkeeper distribution (both sides)
  * From the player stats of every keeper who played: passes, long balls, accurate long balls
    (Opta per-player for Chelsea in PL matches, FotMob otherwise - the numbers are the same Opta feed).
  * goal_kicks / goal_kicks_accurate: Opta team stats, PL only. No source splits goal kicks into
    long/short, so "goal kicks long %" is not available.
Units (Chelsea only): passes, long balls, final-third entries and line-breaking passes summed by
the player's listed position (Goalkeeper / Defender / Midfielder / Forward).
"""
from __future__ import annotations

import json

from . import db
from .config import FOTMOB_TEAM_ID, PL_TEAM_ID, UNDERSTAT_TEAM
from .ingest import first_int, flatten_fotmob_player
from .sources import fotmob, premier_league as pl, understat

UNITS = ["Goalkeeper", "Defender", "Midfielder", "Forward"]


def _ratio(a, b, nd=4):
    return None if a is None or not b else round(a / b, nd)


def _fotmob_team_stats(fm) -> dict:
    vals = {}
    for block in fm["content"]["stats"]["Periods"]["All"]["stats"]:
        for s in block["stats"]:
            if s.get("stats") and s["stats"][0] is not None and s["key"] not in vals:
                vals[s["key"]] = s["stats"]
    return vals


def _understat_ppda(us_league, us_team, us_match_id):
    """Understat league history row for this match (matched on kickoff datetime)."""
    if not us_league or not us_match_id:
        return None
    dt = next((d["datetime"] for d in us_team["dates"] if str(d["id"]) == str(us_match_id)), None)
    team = next((t for t in us_league["teams"].values() if t["title"] == UNDERSTAT_TEAM), None)
    if not dt or not team:
        return None
    return next((h for h in team["history"] if h["date"] == dt), None)


def compute_match(con, match_id: int, us_league, us_team) -> None:
    ids = {r["source"]: r["source_id"] for r in con.execute(
        "SELECT source, source_id FROM source_ids WHERE entity_type='match' AND entity_id=?", (match_id,))}
    fm = fotmob.match(ids["fotmob"], refresh=False)
    home = fm["general"]["homeTeam"]["id"] == FOTMOB_TEAM_ID
    ci, oi = (0, 1) if home else (1, 0)
    fts = _fotmob_team_stats(fm)
    fv = lambda k, i: first_int(fts[k][i]) if k in fts else None

    rows = {s: {"match_id": match_id, "side": s} for s in ("chelsea", "opponent")}
    idx = {"chelsea": ci, "opponent": oi}
    other = {"chelsea": "opponent", "opponent": "chelsea"}

    # ---- PPDA (Understat, PL)
    h = _understat_ppda(us_league, us_team, ids.get("understat"))
    if h:
        for side, key in (("chelsea", "ppda"), ("opponent", "ppda_allowed")):
            p = h[key]
            rows[side].update(ppda=_ratio(p["att"], p["def"], 2), ppda_opp_passes=p["att"], ppda_def_actions=p["def"])
    # ---- PPDA proxy (FotMob, every match)
    for side in rows:
        i, j = idx[side], idx[other[side]]
        acts = [fv("matchstats.headers.tackles", i), fv("interceptions", i), fv("fouls", i)]
        passes = fv("own_half_passes", j)
        if passes is not None and None not in acts:
            rows[side]["ppda_proxy"] = _ratio(passes, sum(acts), 2)

    # ---- FotMob player stats for both teams (minutes > 0)
    fm_players = {"chelsea": [], "opponent": []}
    for ps in (fm["content"].get("playerStats") or {}).values():
        f = flatten_fotmob_player(ps)
        if not f.get("minutes_played"):
            continue
        fm_players["chelsea" if ps.get("teamId") == FOTMOB_TEAM_ID else "opponent"].append((ps, f))

    def fm_sum(side, key):
        vals = [f.get(key) for _, f in fm_players[side]]
        covered = any(v is not None for side_ in fm_players.values() for _, f in side_ for v in [f.get(key)])
        return sum(v or 0 for v in vals) if covered else None

    # ---- passing style
    plm = ids.get("premier_league")
    if plm:
        for t in pl.team_stats(plm, refresh=False):
            s, side = t["stats"], ("chelsea" if str(t["teamId"]) == PL_TEAM_ID else "opponent")
            g = lambda k: int(s.get(k, 0))  # Opta omits zeros
            rows[side].update(passing_source="premier_league", passes=g("totalPass"), long_balls=g("totalLongBalls"),
                              long_balls_accurate=g("accurateLongBalls"), long_own_to_opp=g("longPassOwnToOpp"),
                              long_own_to_opp_accurate=g("longPassOwnToOppSuccess"),
                              final_third_entries=g("finalThirdEntries"),
                              goal_kicks=g("goalKicks"), goal_kicks_accurate=g("accurateGoalKicks"))
    else:
        for side in rows:
            i = idx[side]
            # FotMob team stat is '19 (34%)' (accurate only); the attempt count is the sum over players
            acc, total = fv("long_balls_accurate", i), fm_sum(side, "long_balls_accurate.total")
            rows[side].update(passing_source="fotmob", passes=fv("passes", i), long_balls=total,
                              long_balls_accurate=acc, final_third_entries=fm_sum(side, "passes_into_final_third"))
    for side in rows:
        r = rows[side]
        r["line_breaking_passes"] = fm_sum(side, "line_breaking_passes")
        r["long_ball_share"] = _ratio(r.get("long_balls"), r.get("passes"))
        r["long_ball_accuracy"] = _ratio(r.get("long_balls_accurate"), r.get("long_balls"))

    # ---- goalkeepers
    for side in rows:
        r = rows[side]
        names, gp, gl, gla, src = [], 0, 0, 0, None
        if side == "chelsea":
            gks = con.execute("""SELECT p.name, s.passes, s.long_balls, s.long_balls_accurate, s.stats_source
                                 FROM player_match_stats s JOIN players p USING (player_id)
                                 WHERE s.match_id=? AND p.position='Goalkeeper' AND s.minutes>0""", (match_id,)).fetchall()
            for n, a, b, c, src in gks:
                names.append(n); gp += a or 0; gl += b or 0; gla += c or 0
            ok = bool(gks) and all(g[1] is not None and g[2] is not None for g in gks)
        else:
            gks = [(ps, f) for ps, f in fm_players["opponent"] if ps.get("isGoalkeeper")]
            for ps, f in gks:
                names.append(ps["name"])
                gp += f.get("accurate_passes.total") or 0
                gl += f.get("long_balls_accurate.total") or 0
                gla += f.get("long_balls_accurate.value") or 0
            src = "fotmob"
            ok = bool(gks) and all(f.get("accurate_passes.total") is not None for _, f in gks)
        if ok:
            r.update(gk_names=", ".join(names), gk_passes=gp, gk_long_balls=gl, gk_long_balls_accurate=gla,
                     gk_long_share=_ratio(gl, gp), gk_long_accuracy=_ratio(gla, gl), gk_source=src)

    for side, r in rows.items():
        con.execute("DELETE FROM team_match_buildup WHERE match_id=? AND side=?", (match_id, side))
        db.upsert(con, "team_match_buildup", r, ["match_id", "side"])

    # ---- Chelsea units
    con.execute("DELETE FROM team_match_buildup_units WHERE match_id=?", (match_id,))
    for unit in UNITS:
        con.execute("""INSERT INTO team_match_buildup_units
            SELECT s.match_id, p.position, COUNT(*), SUM(s.minutes), SUM(s.passes), SUM(s.long_balls),
                   SUM(s.final_third_entries), SUM(s.line_breaking_passes)
            FROM player_match_stats s JOIN players p USING (player_id)
            WHERE s.match_id=? AND p.position=? AND s.minutes>0 GROUP BY s.match_id, p.position""", (match_id, unit))


def build_all(con, us_league=None) -> None:
    us_team = understat.team(refresh=False)
    for (mid,) in con.execute("SELECT match_id FROM matches ORDER BY kickoff_utc").fetchall():
        compute_match(con, mid, us_league, us_team)
    con.commit()
