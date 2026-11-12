"""Season analysis + elite comparison data for the website and the exports.

    python -m pipeline.season_analysis            # rebuild from cached league data (data/raw/fotmob_leagues)
    python -m pipeline.season_analysis --refresh  # re-download FotMob big-five league team stats first

Writes:
  site/data/elite_comparison.json  – Chelsea + Europe's elite clubs, league matches, per-match metrics,
                                     plus percentiles among all big-five league clubs
  site/data/season_analysis.json   – everything the Season analysis page needs (Chelsea matches,
                                     squad, pressing table, metric definitions, commentary)

Elite set = Premier League top four plus Chelsea, and the top three of La Liga, Serie A,
Bundesliga and Ligue 1 by league position at build time.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DB_PATH, LOCAL_TZ, RAW_DIR, SITE_DATA_DIR

LEAGUE_DIR = RAW_DIR / "fotmob_leagues"
LEAGUES = {"PL": (47, "Premier League", 4), "LaLiga": (87, "La Liga", 3), "SerieA": (55, "Serie A", 3),
           "Bundesliga": (54, "Bundesliga", 3), "Ligue1": (53, "Ligue 1", 3)}
SHORT = {"Premier League": "PL", "La Liga": "LL", "Serie A": "SA", "Bundesliga": "BL", "Ligue 1": "L1"}
CHELSEA_FOTMOB = 8455

# FotMob stat list -> our key (value); some lists also carry a useful sub-stat
STAT = {
    "goals_team_match": "gf_pm", "goals_conceded_team_match": "ga_pm", "expected_goals_team": "xg_tot",
    "expected_goals_conceded_team": "xga_tot", "possession_percentage_team": "poss", "accurate_pass_team": "accpass_pm",
    "accurate_long_balls_team": "acclong_pm", "big_chance_team": "bc_tot", "big_chance_missed_team": "bcm_tot",
    "ontarget_scoring_att_team": "sot_pm", "touches_in_opp_box_team": "box_tot", "corner_taken_team": "corners_tot",
    "_set_piece_goals_team": "spg_tot", "_set_piece_goals_conceded_team": "spga_tot", "clean_sheet_team": "cs_tot",
    "interception_team": "int_pm", "total_tackle_team": "tkl_pm", "poss_won_att_3rd_team": "pw3_pm",
    "fk_foul_lost_team": "fouls_pm", "total_yel_card_team": "yc_tot", "rating_team": "rating", "squad_value_team": "value",
}
SUB = {"accurate_pass_team": "pass_pct", "accurate_long_balls_team": "long_pct", "ontarget_scoring_att_team": "shot_conv",
       "_set_piece_goals_team": "spxg_tot"}
ZERO_OMITTED = {"clean_sheet_team"}  # FotMob leaves clubs with 0 out of these lists

# Metric definitions shared by the site page and the exports. low = fewer is better.
METRICS = [
    ("ppg", "Points per match", "PPG", 2, False, False), ("xppg", "Expected points per match", "xPPG", 2, False, False),
    ("xgd_pm", "xG difference per match", "xGD/m", 2, False, True), ("rating", "FotMob team rating", "Rating", 2, False, False),
    ("value", "Squad value (FotMob, €m)", "Value €m", 0, False, False), ("gf_pm", "Goals per match", "G/m", 2, False, False),
    ("xg_pm", "xG per match", "xG/m", 2, False, False), ("fin", "Goals minus xG (season)", "G−xG", 1, False, True),
    ("bc_pm", "Big chances per match", "BC/m", 1, False, False), ("bc_conv", "Big chance conversion %", "BC conv %", 1, False, False),
    ("sot_pm", "Shots on target per match", "SoT/m", 1, False, False), ("shot_conv", "Shot conversion %", "Conv %", 1, False, False),
    ("box_pm", "Touches in opposition box per match", "Box touches/m", 1, False, False),
    ("ga_pm", "Goals conceded per match", "GA/m", 2, True, False), ("xga_pm", "xG conceded per match", "xGA/m", 2, True, False),
    ("gk", "xG conceded minus goals conceded", "xGA−GA", 1, False, True), ("cs_pct", "Clean sheet %", "CS %", 0, False, False),
    ("tkl_pm", "Tackles per match", "Tkl/m", 1, False, False), ("int_pm", "Interceptions per match", "Int/m", 1, False, False),
    ("pw3_pm", "Possession won in final third per match", "High regains/m", 1, False, False),
    ("poss", "Possession %", "Poss %", 1, False, False), ("accpass_pm", "Accurate passes per match", "Acc. passes/m", 0, False, False),
    ("pass_pct", "Pass accuracy %", "Pass %", 1, False, False), ("acclong_pm", "Accurate long balls per match", "Acc. long/m", 1, False, False),
    ("long_pct", "Long-ball accuracy %", "Long %", 1, False, False), ("corners_pm", "Corners per match", "Corners/m", 1, False, False),
    ("spg_pm", "Set-piece goals per match", "SP G/m", 2, False, False), ("spxg_pm", "Set-piece xG per match", "SP xG/m", 2, False, False),
    ("spga_pm", "Set-piece goals conceded per match", "SP GA/m", 2, True, False),
    ("fouls_pm", "Fouls per match (fewest first)", "Fouls/m", 1, True, False),
    ("yc_pm", "Yellow cards per match (fewest first)", "YC/m", 1, True, False),
]
GROUPS = {"Results": ["ppg", "xppg", "xgd_pm", "rating", "value"], "Attack": ["gf_pm", "xg_pm", "fin", "bc_pm", "sot_pm", "box_pm"],
          "Defence": ["ga_pm", "xga_pm", "gk", "cs_pct", "tkl_pm", "pw3_pm"], "Style": ["poss", "accpass_pm", "pass_pct", "acclong_pm", "long_pct"],
          "Set pieces": ["corners_pm", "spg_pm", "spxg_pm", "spga_pm", "fouls_pm", "yc_pm"]}
PRESETS = {"xG vs xGA": ["xg_pm", "xga_pm"], "Points vs xPoints": ["xppg", "ppg"],
           "Possession vs high regains": ["poss", "pw3_pm"], "Box touches vs big chances": ["box_pm", "bc_pm"]}
RADAR = {"xg_pm": "xG", "xga_pm": "xG conceded (inv.)", "fin": "Finishing", "bc_pm": "Big chances", "box_pm": "Box touches",
         "poss": "Possession", "pass_pct": "Pass %", "pw3_pm": "High regains", "tkl_pm": "Tackles", "spg_pm": "Set-piece goals",
         "cs_pct": "Clean sheets", "xppg": "xPoints"}


def fetch_leagues():
    from curl_cffi import requests as cr
    (LEAGUE_DIR / "stats").mkdir(parents=True, exist_ok=True)
    for code, (lid, _, _) in LEAGUES.items():
        r = cr.get("https://www.fotmob.com/api/data/leagues", params={"id": lid, "ccode3": "EGY"}, impersonate="chrome", timeout=40)
        r.raise_for_status()
        d = r.json()
        (LEAGUE_DIR / f"league_{code}.json").write_text(json.dumps(d))
        for s in d["stats"]["teams"]:
            x = cr.get(s["fetchAllUrl"], impersonate="chrome", timeout=40)
            if x.status_code == 200:
                (LEAGUE_DIR / "stats" / f"{code}_{s['name']}.json").write_text(x.text)
            time.sleep(0.4)


def league_teams() -> list[dict]:
    teams = {}
    for code, (_, name, _) in LEAGUES.items():
        d = json.loads((LEAGUE_DIR / f"league_{code}.json").read_text())
        tb = d["table"][0]["data"]["table"]
        for r in tb["all"]:
            gf, ga = (int(x) for x in r["scoresStr"].split("-"))
            teams[r["id"]] = dict(id=r["id"], name=r["shortName"], league=name, lg=code, pos=r["idx"], mp=r["played"],
                                  w=r["wins"], d=r["draws"], l=r["losses"], pts=r["pts"], gf=gf, ga=ga)
        for r in tb.get("xg", []):
            t = teams[r["id"]]
            t.update(xpts=r.get("xPoints"), xpos=r.get("xPosition"), xg_tot=r.get("xg"), xga_tot=r.get("xgConceded"))
        for f in (LEAGUE_DIR / "stats").glob(f"{code}_*.json"):
            key = f.stem[len(code) + 1:]
            if key not in STAT:
                continue
            seen = set()
            for e in json.loads(f.read_text())["TopLists"][0]["StatList"]:
                t = teams.get(e["TeamId"])
                if not t:
                    continue
                seen.add(e["TeamId"])
                if not (STAT[key] in ("xg_tot", "xga_tot") and t.get(STAT[key]) is not None):  # xG table is more precise
                    t[STAT[key]] = e["StatValue"]
                if key in SUB:
                    t[SUB[key]] = e["SubStatValue"]
            if key in ZERO_OMITTED:
                for tid, t in teams.items():
                    if t["lg"] == code and tid not in seen:
                        t[STAT[key]] = 0
    for t in teams.values():
        mp = t["mp"]
        # same rounding steps as the first published version, so ranks and percentiles are reproducible
        for a in ["xg", "xga", "bc", "box", "corners", "spg", "spga", "spxg", "yc"]:
            if t.get(a + "_tot") is not None:
                t[a + "_pm"] = round(t[a + "_tot"] / mp, 3)
        t["ppg"] = round(t["pts"] / mp, 3)
        t["xgd_pm"] = round(t["xg_pm"] - t["xga_pm"], 3)
        t["fin"] = round(t["gf"] - t["xg_tot"], 2)
        t["gk"] = round(t["xga_tot"] - t["ga"], 2)
        t["bc_conv"] = round((t["bc_tot"] - t.get("bcm_tot", 0)) / t["bc_tot"] * 100, 1) if t.get("bc_tot") else None
        t["xppg"] = round(t["xpts"] / mp, 3) if t.get("xpts") is not None else None
        t["cs_pct"] = round(t.get("cs_tot", 0) / mp * 100, 1)
    return list(teams.values())


def r2(v, n=2):
    return None if v is None else round(v, n)


def percentile(v, vals, low):
    vals = [x for x in vals if x is not None]
    if v is None or len(vals) < 2:
        return None
    better = sum(1 for x in vals if (x > v if low else x < v))
    eq = sum(1 for x in vals if x == v)
    return round((better + 0.5 * (eq - 1)) / (len(vals) - 1) * 100)


def elite(all_teams):
    sel = []
    for code, (_, _, n) in LEAGUES.items():
        sel += [t for t in all_teams if t["lg"] == code and t["pos"] <= n]
    che = next(t for t in all_teams if t["id"] == CHELSEA_FOTMOB)
    if che not in sel:
        sel.insert(0, che)
    sel.sort(key=lambda t: (t["id"] != CHELSEA_FOTMOB))
    keys = [m[0] for m in METRICS]
    out = []
    for t in sel:
        v = {}
        for k in keys:
            x = t.get(k)
            v[k] = None if x is None else (round(x / 1e6) if k == "value" else round(x, 2))
        # percentile among all big-five league clubs
        low = {m[0]: m[4] for m in METRICS}
        pct = {k: percentile(t.get(k), [o.get(k) for o in all_teams], low[k]) for k in keys if k != "value"}
        out.append(dict(n=t["name"], lg=SHORT[t["league"]], league=t["league"], pos=t["pos"], mp=t["mp"], w=t["w"], d=t["d"],
                        l=t["l"], pts=t["pts"], gf=t["gf"], ga=t["ga"], xpos=t.get("xpos"), v=v, pct=pct))
    return out


SP = {"FromCorner", "FreeKick", "SetPiece", "ThrowInSetPiece"}


def chelsea(con):
    c = con
    c.row_factory = sqlite3.Row
    q = lambda s, *a: [dict(r) for r in c.execute(s, a)]
    M = q("""select m.*, t.xg, t.shots, t.shots_on_target sot, t.big_chances bc, t.possession poss, t.passes, t.passes_accurate pa,
      t.touches_opp_box box, t.corners, t.fouls, t.yellow_cards yc, t.red_cards rc, t.tackles, t.interceptions,
      o.xg xga, o.shots oshots, o.shots_on_target osot, o.big_chances obc,
      b.ppda, b.ppda_proxy, b.long_ball_share lbs, b.long_ball_accuracy lba, b.gk_long_share gkls, b.gk_long_accuracy gkla,
      b.final_third_entries fte, b.line_breaking_passes lbp, ob.ppda oppda
      from matches m join team_match_stats t on t.match_id=m.match_id and t.side='chelsea'
      join team_match_stats o on o.match_id=m.match_id and o.side='opponent'
      left join team_match_buildup b on b.match_id=m.match_id and b.side='chelsea'
      left join team_match_buildup ob on ob.match_id=m.match_id and ob.side='opponent' order by m.kickoff_utc""")
    rows = []
    for m in M:
        sh = lambda side: q("select situation, sum(result='Goal') g, sum(xg) xg from shots where match_id=? and side=? and source='fotmob' group by situation", m["match_id"], side)
        s, so = sh("chelsea"), sh("opponent")
        pen = sum(x["xg"] or 0 for x in s if x["situation"] == "Penalty")
        spg = sum(x["g"] or 0 for x in s if x["situation"] in SP); spxg = sum(x["xg"] or 0 for x in s if x["situation"] in SP)
        ospg = sum(x["g"] or 0 for x in so if x["situation"] in SP); ospxg = sum(x["xg"] or 0 for x in so if x["situation"] in SP)
        pct100 = lambda x: None if x is None else round(x * 100, 1)
        rows.append(dict(id=m["match_id"], d=m["kickoff_local"][:10], c="PL" if m["competition"] == "Premier League" else "EFL",
                         competition=m["competition"], v=m["venue"], o=m["opponent"], gf=m["goals_for"], ga=m["goals_against"], r=m["result"],
                         pens=f"{m['pens_for']}-{m['pens_against']}" if m["pens_for"] is not None else None,
                         xg=r2(m["xg"]), xga=r2(m["xga"]), npxg=r2(m["xg"] - pen), sh=m["shots"], sot=m["sot"], osh=m["oshots"], osot=m["osot"],
                         bc=m["bc"], obc=m["obc"], poss=m["poss"], pacc=r2(m["pa"] / m["passes"] * 100, 1), box=m["box"], cor=m["corners"],
                         fo=m["fouls"], yc=m["yc"], rc=m["rc"], tkl=m["tackles"], itc=m["interceptions"], ppda=r2(m["ppda"]),
                         ppdap=r2(m["ppda_proxy"]), oppda=r2(m["oppda"]), lbs=pct100(m["lbs"]), lba=pct100(m["lba"]), gkls=pct100(m["gkls"]),
                         gkla=pct100(m["gkla"]), fte=m["fte"], lbp=m["lbp"], spg=spg, spxg=r2(spxg), ospg=ospg, ospxg=r2(ospxg), fm=m["formation"]))
    asof = date.fromisoformat(rows[-1]["d"]) if rows else date.today()
    today = datetime.now(ZoneInfo(LOCAL_TZ)).date()
    P = q("""select p.name, p.position, p.birth_date, count(*) ap, sum(s.started) st, sum(s.minutes) mi, sum(s.goals) g, sum(s.assists) a,
      sum(s.xg) xg, sum(s.xa) xa, sum(s.shots) sh, sum(s.chances_created) kp, sum(s.tackles) tkl, sum(s.interceptions) itc,
      sum(s.recoveries) rec, sum(s.clearances) clr, sum(s.duels_won) dw, sum(s.duels_lost) dl, sum(s.line_breaking_passes) lbp,
      sum(s.final_third_entries) fte, sum(s.yellow_cards) yc, sum(s.red_cards) rc, sum(s.goals_prevented) gp, avg(s.rating) rt
      from player_match_stats s join players p using(player_id) where s.minutes>0 group by p.player_id order by mi desc""")
    used = len(P)
    players = []
    for p in P:
        age = None
        if p["birth_date"]:
            b = date.fromisoformat(p["birth_date"])
            age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
        if p["mi"] < 45:
            continue
        pos = {"Goalkeeper": "GK", "Defender": "DEF", "Midfielder": "MID", "Forward": "FWD"}.get(p["position"], p["position"])
        players.append(dict(n=p["name"], p=pos, age=age, **{k: p[k] for k in ["ap", "st", "mi", "g", "a", "sh", "kp", "tkl", "itc", "rec", "clr", "dw", "dl", "lbp", "fte", "yc", "rc"]},
                            xg=r2(p["xg"]), xa=r2(p["xa"]), gp=r2(p["gp"]), rt=r2(p["rt"])))
    return rows, players, used


def pl_ppda():
    """Season PPDA for every PL club from Understat league data (cached copy if Understat is offline)."""
    f = RAW_DIR / "understat" / "league_EPL_2026.json"
    if not f.exists():
        return [], None
    d = json.loads(f.read_text())
    ren = {"Manchester United": "Man United", "Manchester City": "Man City", "Nottingham Forest": "Nottm Forest", "Newcastle United": "Newcastle"}
    out, last, rounds = [], "", 0
    for t in d["teams"].values():
        h = t["history"]
        rounds = max(rounds, len(h))
        last = max([last] + [x["date"] for x in h])
        out.append([ren.get(t["title"], t["title"]), round(sum(x["ppda"]["att"] for x in h) / sum(x["ppda"]["def"] for x in h), 2)])
    out.sort(key=lambda r: r[1])
    return out, dict(rounds=rounds, last_match=last[:10])


def build(refresh=False):
    if refresh:
        fetch_leagues()
    all_teams = league_teams()
    el = elite(all_teams)
    con = sqlite3.connect(DB_PATH)
    matches, players, used = chelsea(con)
    ppda, ppda_meta = pl_ppda()
    league_mtime = datetime.fromtimestamp((LEAGUE_DIR / "league_PL.json").stat().st_mtime, ZoneInfo(LOCAL_TZ)).strftime("%Y-%m-%d")
    meta = dict(generated_at=datetime.now(ZoneInfo(LOCAL_TZ)).strftime("%Y-%m-%d %H:%M"), timezone=LOCAL_TZ,
                elite_data_date=league_mtime, n_big5=len(all_teams), n_elite=len(el), players_used=used,
                last_match=matches[-1]["d"] if matches else None, n_matches=len(matches), ppda=ppda_meta,
                elite_rule="Premier League top four plus Chelsea, and the top three in La Liga, Serie A, Bundesliga and Ligue 1 by league position")
    metrics = [dict(k=k, label=l, short=s, dp=dp, low=low, signed=sg) for k, l, s, dp, low, sg in METRICS]
    elite_doc = dict(meta=meta, metrics=metrics, teams=el,
                     sources=["FotMob league team stats and xG table (big five leagues)"])
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DATA_DIR / "elite_comparison.json").write_text(json.dumps(elite_doc, ensure_ascii=False, indent=1))
    content = json.loads((Path(__file__).with_name("season_analysis_content.json")).read_text())
    doc = dict(meta=meta, metrics=metrics, groups=GROUPS, presets=PRESETS, radar=RADAR, elite=el, matches=matches,
               players=players, pl_ppda=ppda, **content)
    (SITE_DATA_DIR / "season_analysis.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    print(f"season_analysis: {len(el)} elite clubs (of {len(all_teams)}), {len(matches)} Chelsea matches, {len(players)} players")
    return doc


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-download FotMob league data")
    build(ap.parse_args().refresh)
