"""Data-driven markdown reports. Every sentence is computed from the database:
no opinions, no facts that are not in the numbers.

Outputs (rendered by the website):
  site/data/reports/match/<match_id>.md
  site/data/reports/monthly/<YYYY-MM>.md
  site/data/reports/season/<season>.md      (placeholder + season to date)
  site/data/reports/index.json
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .analysis import fmt, load, per90
from .config import LOCAL_TZ, SEASON_LABEL, SITE_DATA_DIR

OUT = SITE_DATA_DIR / "reports"
SOURCE_NOTE = {
    "premier_league": "Player and team numbers: Opta via premierleague.com. Ratings and physical data: FotMob.",
    "fotmob": "Player and team numbers: FotMob (cup match, not covered by the Premier League API).",
}
# metric -> (label, minimum absolute gap vs expectation to count as an outlier)
OUTLIER_METRICS = {
    "xg": ("xG", 0.4), "xa": ("xA", 0.3), "shots": ("shots", 2), "chances_created": ("chances created", 2),
    "final_third_entries": ("final-third entries", 3), "dribbles_won": ("successful dribbles", 2),
    "touches_opp_box": ("touches in the opposition box", 3), "tackles": ("tackles", 2),
    "interceptions": ("interceptions", 2), "recoveries": ("ball recoveries", 3),
    "duels_won": ("duels won", 4), "passes_accurate": ("accurate passes", 15),
    "defensive_actions": ("defensive actions", 4),
}


def _when(ts: pd.Timestamp) -> str:
    return ts.strftime("%A %-d %B %Y, %H:%M") + " Cairo time"


def _score_line(m) -> str:
    home, away = ("Chelsea", m.opponent) if m.venue == "H" else (m.opponent, "Chelsea")
    hg, ag = (m.goals_for, m.goals_against) if m.venue == "H" else (m.goals_against, m.goals_for)
    line = f"{home} {hg}–{ag} {away}"
    pf, pa = getattr(m, "pens_for", None), getattr(m, "pens_against", None)
    if pf is not None and pa is not None and pf == pf and pa == pa:  # skip NULL/NaN
        hp, ap = (int(pf), int(pa)) if m.venue == "H" else (int(pa), int(pf))
        winner = "Chelsea" if pf > pa else m.opponent
        line += f" ({winner} won {max(hp, ap)}–{min(hp, ap)} on penalties)"
    return line


def _round(m) -> str:
    r = m["round"]
    if not r:
        return ""
    return f" · Round {r}" if str(r).isdigit() else f" · {r}"


def _leader(df, col, n=1, min_val=None):
    d = df.dropna(subset=[col])
    if min_val is not None:
        d = d[d[col] >= min_val]
    return d.sort_values(col, ascending=False).head(n)


# ------------------------------------------------------------------ match report
def match_report(m, matches, pms, shots, bu=None, bu_units=None) -> str:
    mp = pms[pms.match_id == m.match_id].copy()
    prior = pms[pms.kickoff_local < m.kickoff_local]
    prior_matches = matches[matches.kickoff_local <= m.kickoff_local]
    L = [f"# {_score_line(m)}",
         f"*{m.competition}{_round(m)}"
         f" · {_when(m.kickoff_local)} · {m.ground or ''}*", ""]

    # ---- team numbers
    rows = [("Possession %", "possession", 1), ("Expected goals (xG)", "xg", 2), ("Shots", "shots", 0),
            ("Shots on target", "shots_on_target", 0), ("Big chances", "big_chances", 0),
            ("Touches in opposition box", "touches_opp_box", 0), ("Passes", "passes", 0),
            ("Accurate passes", "passes_accurate", 0), ("Corners", "corners", 0), ("Saves", "saves", 0)]
    L += ["## The numbers", "", f"| | Chelsea | {m.opponent} |", "|---|---:|---:|"]
    for label, col, nd in rows:
        a, b = m.get(f"chelsea_{col}"), m.get(f"opponent_{col}")
        if pd.isna(a) and pd.isna(b):
            continue
        L.append(f"| {label} | {fmt(a, nd)} | {fmt(b, nd)} |")
    if pd.notna(m.xg_understat_for):
        L.append(f"| xG (Understat model) | {m.xg_understat_for:.2f} | {m.xg_understat_against:.2f} |")
    L.append("")

    # ---- goals
    scorers = mp[mp.goals > 0].sort_values("goals", ascending=False)
    assisters = mp[mp.assists > 0].sort_values("assists", ascending=False)
    L.append("## Goals and assists")
    L.append("")
    L.append("- **Scorers:** " + (", ".join(f"{r['name']}" + (f" ×{int(r.goals)}" if r.goals > 1 else "")
                                           for _, r in scorers.iterrows()) or "none"))
    L.append("- **Assists:** " + (", ".join(f"{r['name']}" + (f" ×{int(r.assists)}" if r.assists > 1 else "")
                                           for _, r in assisters.iterrows()) or "none recorded"))
    credited = int(scorers.goals.sum())
    if credited < m.goals_for:
        L.append(f"- {m.goals_for - credited} goal(s) are not credited to a Chelsea player in the player data (for example an own goal).")
    L.append("")

    # ---- standout data
    L += ["## Standout data", ""]
    t = _leader(mp, "xg")
    if len(t) and t.iloc[0].xg > 0:
        r = t.iloc[0]
        L.append(f"- **Biggest goal threat:** {r['name']} — {r.xg:.2f} xG from {fmt(r.shots)} shot(s), {fmt(r.shots_on_target)} on target.")
    t = _leader(mp, "chances_created", min_val=1)
    if len(t):
        r = t.iloc[0]
        L.append(f"- **Chief creator:** {r['name']} — {fmt(r.chances_created)} chance(s) created"
                 + (f", {r.xa:.2f} xA" if pd.notna(r.xa) else "")
                 + (f", {fmt(r.big_chances_created)} big chance(s)" if pd.notna(r.big_chances_created) and r.big_chances_created > 0 else "") + ".")
    t = _leader(mp, "final_third_entries", min_val=1)
    if len(t):
        r = t.iloc[0]
        L.append(f"- **Ball progression:** {r['name']} led the team with {fmt(r.final_third_entries)} final-third entries"
                 + (f" and {fmt(r.line_breaking_passes)} line-breaking passes" if pd.notna(r.line_breaking_passes) else "") + ".")
    t = _leader(mp, "dribbles_won", min_val=2)
    if len(t):
        r = t.iloc[0]
        L.append(f"- **Dribbling:** {r['name']} completed {fmt(r.dribbles_won)} of {fmt(r.dribbles)} take-ons.")
    p = mp[mp.passes >= 20].assign(acc=lambda d: d.passes_accurate / d.passes)
    if len(p):
        r = p.sort_values("passes_accurate", ascending=False).iloc[0]
        L.append(f"- **Most accurate passes:** {r['name']} — {fmt(r.passes_accurate)}/{fmt(r.passes)} ({r.acc:.0%}).")
    t = _leader(mp, "defensive_actions", min_val=1)
    if len(t):
        r = t.iloc[0]
        L.append(f"- **Defensive leader:** {r['name']} — {fmt(r.defensive_actions)} defensive actions "
                 f"({fmt(r.tackles)} tackles, {fmt(r.interceptions)} interceptions, {fmt(r.recoveries)} recoveries, "
                 f"{fmt(r.clearances)} clearances, {fmt(r.blocks)} blocks).")
    t = _leader(mp, "duels_won", min_val=1)
    if len(t):
        r = t.iloc[0]
        L.append(f"- **Duels:** {r['name']} won {fmt(r.duels_won)} duels (lost {fmt(r.duels_lost)}).")
    gk = mp[(mp.position == "Goalkeeper")]
    for _, r in gk.iterrows():
        bits = [f"{fmt(r.saves)} save(s)"]
        if pd.notna(r.goals_prevented):
            bits.append(f"{r.goals_prevented:+.2f} goals prevented (FotMob)")
        L.append(f"- **Goalkeeping:** {r['name']} ({int(r.minutes)}') — " + ", ".join(bits) + ".")
    t = _leader(mp, "rating", n=3)
    if len(t):
        L.append("- **Highest FotMob ratings:** " + ", ".join(f"{r['name']} {r.rating:.1f}" for _, r in t.iterrows()) + ".")
    t = _leader(mp, "distance_m")
    if len(t):
        r = t.iloc[0]
        s = _leader(mp, "top_speed_kmh").iloc[0]
        L.append(f"- **Physical:** {r['name']} covered the most ground ({r.distance_m / 1000:.1f} km); "
                 f"{s['name']} hit the top speed ({s.top_speed_kmh:.1f} km/h).")
    L.append("")

    # ---- observations: team context and individual outliers
    obs = []
    n_prior = len(prior_matches)
    if n_prior >= 3:
        for col, label in (("chelsea_xg", "xG created"), ("opponent_xg", "xG conceded"),
                           ("chelsea_shots", "shots taken"), ("chelsea_possession", "possession")):
            v = m.get(col)
            series = prior_matches[col].dropna()
            if pd.isna(v) or len(series) < 3:
                continue
            if v == series.max():
                obs.append(f"Chelsea's highest {label} of the season so far ({fmt(v)} across {len(series)} matches to date).")
            elif v == series.min():
                obs.append(f"Chelsea's lowest {label} of the season so far ({fmt(v)} across {len(series)} matches to date).")
    if pd.notna(m.chelsea_xg):
        diff = m.goals_for - m.chelsea_xg
        if diff >= 1.5:
            obs.append(f"Finishing ran hot: {m.goals_for} goals from {m.chelsea_xg:.2f} xG (+{diff:.2f}).")
        elif diff <= -1:
            obs.append(f"Finishing fell short: {m.goals_for} goals from {m.chelsea_xg:.2f} xG ({diff:.2f}).")
        ddiff = m.goals_against - m.opponent_xg
        if ddiff >= 1.5:
            obs.append(f"{m.opponent} scored {m.goals_against} from {m.opponent_xg:.2f} xG (+{ddiff:.2f} above expectation).")
        elif ddiff <= -1:
            obs.append(f"{m.opponent} scored {m.goals_against} from {m.opponent_xg:.2f} xG ({ddiff:.2f}).")
    if pd.notna(m.chelsea_xg) and pd.notna(m.opponent_xg):
        if m.result == "L" and m.chelsea_xg > m.opponent_xg:
            obs.append(f"Chelsea lost despite out-creating {m.opponent} on xG ({m.chelsea_xg:.2f} v {m.opponent_xg:.2f}).")
        if m.result == "W" and m.chelsea_xg < m.opponent_xg:
            obs.append(f"Chelsea won despite {m.opponent} creating more xG ({m.opponent_xg:.2f} v {m.chelsea_xg:.2f}).")

    outliers = []
    for _, r in mp[mp.minutes >= 45].iterrows():
        hist = prior[prior.player_id == r.player_id]
        if len(hist) < 2 or hist.minutes.sum() < 135:
            continue
        for col, (label, gap) in OUTLIER_METRICS.items():
            h = hist.dropna(subset=[col])
            if pd.isna(r[col]) or len(h) < 2:
                continue
            exp = h[col].sum() / h.minutes.sum() * r.minutes
            if r[col] >= max(2 * exp, exp + gap):
                outliers.append((r[col] / max(exp, 0.05),
                                 f"{r['name']}: {fmt(r[col])} {label} in {int(r.minutes)} minutes — his previous "
                                 f"{len(h)} appearances average {exp:.2f} for the same minutes."))
    outliers.sort(key=lambda x: -x[0])
    if bu is not None:
        L += buildup_section(m, matches, bu, bu_units)
    L += ["## Notable observations", ""]
    L += [f"- {o}" for o in obs] + [f"- {o[1]}" for o in outliers[:6]]
    if not obs and not outliers:
        L.append("- Nothing stood out against the season-to-date baselines (needs at least 2 previous appearances per player).")
    L += ["", "*How outliers work: a player is flagged when a number is at least double what his previous "
          "appearances this season would predict for the minutes he played, and above a minimum gap.*", ""]

    # ---- shots summary
    s = shots[(shots.match_id == m.match_id)]
    src = "understat" if (s.source == "understat").any() else "fotmob"
    s = s[s.source == src]
    if len(s):
        cs = s[s.side == "chelsea"]
        big = cs.sort_values("xg", ascending=False).head(3)
        L += ["## Best Chelsea chances", "",
              f"| Minute | Player | xG | Outcome |", "|---:|---|---:|---|"]
        L += [f"| {int(r.minute)}' | {r.player_name} | {r.xg:.2f} | {r.result} |" for _, r in big.iterrows()]
        L += ["", f"*Shot data: {'Understat' if src == 'understat' else 'FotMob'}.*", ""]

    L += ["---", f"*{SOURCE_NOTE[m.player_stats_source]} Generated automatically from the data; no manual edits.*"]
    return "\n".join(L)


BUILDUP_ROWS = [  # (label, column, kind) kind: 'n' number, 'p' percent, 'r' ratio
    ("PPDA (Understat; lower = more pressing)", "ppda", "r"),
    ("PPDA proxy (FotMob, whole pitch)", "ppda_proxy", "r"),
    ("Long-ball share of passes", "long_ball_share", "p"),
    ("Long-ball accuracy", "long_ball_accuracy", "p"),
    ("Final-third entries", "final_third_entries", "n"),
    ("Line-breaking passes", "line_breaking_passes", "n"),
    ("GK passes", "gk_passes", "n"),
    ("GK long-ball share", "gk_long_share", "p"),
    ("GK long-ball accuracy", "gk_long_accuracy", "p"),
    ("Goal kicks (accurate)", "goal_kicks", "gk"),
]


def _bu_fmt(v, kind, acc=None):
    if v is None or pd.isna(v):
        return "n/a"
    if kind == "p":
        return f"{v * 100:.1f}%"
    if kind == "r":
        return f"{v:.2f}"
    if kind == "gk":
        return f"{int(round(v))}" + (f" ({int(acc)})" if acc is not None and not pd.isna(acc) else "")
    return f"{v:.1f}" if v != int(v) else f"{int(v)}"


def buildup_section(m, matches, bu, bu_units) -> list[str]:
    mine = bu[bu.match_id == m.match_id].set_index("side")
    if mine.empty:
        return []
    prev_ids = matches[matches.kickoff_utc < m.kickoff_utc].match_id
    prev = bu[(bu.side == "chelsea") & bu.match_id.isin(prev_ids)]
    c, o = mine.loc["chelsea"], mine.loc["opponent"]
    L = ["## Build-up & pressing", "",
         f"| | Chelsea | {m.opponent} | Chelsea avg, previous matches |", "|---|---:|---:|---:|"]
    for label, col, kind in BUILDUP_ROWS:
        acc = "goal_kicks_accurate" if kind == "gk" else None
        avg = prev[col].mean() if prev[col].notna().any() else None
        L.append(f"| {label} | {_bu_fmt(c[col], kind, c[acc] if acc else None)} | "
                 f"{_bu_fmt(o[col], kind, o[acc] if acc else None)} | {_bu_fmt(avg, 'n' if kind == 'gk' else kind)} |")
    L.append("")
    notes = []
    for col, low, high in (("ppda", "most intense press", "least intense press"),
                           ("gk_long_share", "shortest goalkeeper distribution", "most direct goalkeeper distribution")):
        allc = bu[(bu.side == "chelsea") & bu[col].notna() & bu.match_id.isin(list(prev_ids) + [m.match_id])]
        if pd.notna(c[col]) and len(allc) >= 3:
            if c[col] == allc[col].max():
                notes.append(f"{high} of the season so far ({_bu_fmt(c[col], 'p' if col != 'ppda' else 'r')})")
            elif c[col] == allc[col].min():
                notes.append(f"{low} of the season so far ({_bu_fmt(c[col], 'p' if col != 'ppda' else 'r')})")
    if notes:
        L += ["- Chelsea: " + "; ".join(notes) + ".", ""]
    u = bu_units[bu_units.match_id == m.match_id].set_index("unit")
    if len(u):
        L += ["| Chelsea unit | Passes | Long balls | Final-third entries | Line-breaking passes |", "|---|---:|---:|---:|---:|"]
        for unit in ("Goalkeeper", "Defender", "Midfielder", "Forward"):
            if unit in u.index:
                r = u.loc[unit]
                L.append(f"| {unit} | {_bu_fmt(r.passes, 'n')} | {_bu_fmt(r.long_balls, 'n')} | "
                         f"{_bu_fmt(r.final_third_entries, 'n')} | {_bu_fmt(r.line_breaking_passes, 'n')} |")
        L.append("")
    L += ["*PPDA = opponent passes allowed per Chelsea defensive action in the pressing zone (Understat, Premier League only). "
          "The proxy uses whole-pitch tackles + interceptions + fouls and is not on the same scale. Goal kicks: Opta, Premier League only. "
          "n/a = not provided by the source for this match.*", ""]
    return L


# ------------------------------------------------------------------ monthly report
def _team_month(ms: pd.DataFrame) -> dict:
    n = len(ms)
    return dict(n=n, w=(ms.result == "W").sum(), d=(ms.result == "D").sum(), l=(ms.result == "L").sum(),
                gf=ms.goals_for.sum(), ga=ms.goals_against.sum(),
                xg=ms.chelsea_xg.mean(), xga=ms.opponent_xg.mean(), shots=ms.chelsea_shots.mean(),
                shots_against=ms.opponent_shots.mean(), poss=ms.chelsea_possession.mean(),
                gf_pm=ms.goals_for.mean(), ga_pm=ms.goals_against.mean())


def monthly_report(month: str, matches, pms, today_month: str) -> tuple[str, str]:
    ms = matches[matches.month == month]
    title = datetime.strptime(month, "%Y-%m").strftime("%B %Y") + (" (to date)" if month == today_month else "")
    L = [f"# {title}", ""]
    t = _team_month(ms)
    L += [f"**{t['n']} matches · {t['w']}W {t['d']}D {t['l']}L · goals {t['gf']}–{t['ga']}**", "",
          "| Date | Competition | Match | Result | xG for | xG against |", "|---|---|---|---|---:|---:|"]
    for _, m in ms.iterrows():
        L.append(f"| {m.kickoff_local:%d %b} | {m.competition} | [{_score_line(m)}](#/reports/match/{m.match_id}) | {m.result} | "
                 f"{fmt(m.chelsea_xg)} | {fmt(m.opponent_xg)} |")
    L.append("")

    prev_months = sorted(matches.month.unique())
    prev = prev_months[prev_months.index(month) - 1] if prev_months.index(month) > 0 else None
    L += ["## Team trends (per match)", ""]
    rows = [("Goals for", "gf_pm"), ("Goals against", "ga_pm"), ("xG for", "xg"), ("xG against", "xga"),
            ("Shots for", "shots"), ("Shots against", "shots_against"), ("Possession %", "poss")]
    if prev:
        p = _team_month(matches[matches.month == prev])
        pt = datetime.strptime(prev, "%Y-%m").strftime("%B")
        L += [f"| | {title.split(' (')[0]} | {pt} | Change |", "|---|---:|---:|---:|"]
        L += [f"| {lab} | {t[k]:.2f} | {p[k]:.2f} | {t[k] - p[k]:+.2f} |" for lab, k in rows]
    else:
        L += ["| | Per match |", "|---|---:|"] + [f"| {lab} | {t[k]:.2f} |" for lab, k in rows]
    L += ["", f"*xG: Opta (via premierleague.com) for league matches, FotMob for cup matches.*", ""]

    mp = pms[pms.month == month]
    agg = per90(mp, ["goals", "assists", "xg", "xa", "chances_created", "defensive_actions", "final_third_entries"])
    rat = mp.dropna(subset=["rating"]).groupby("name").rating.agg(["mean", "count"])
    L += ["## Player leaders", ""]

    def line(label, col, n=3, nd=2, min_minutes=0, per=False):
        d = agg[(agg.minutes >= min_minutes)].dropna(subset=[col]).sort_values(col, ascending=False).head(n)
        d = d[d[col] > 0]
        if len(d):
            L.append(f"- **{label}:** " + ", ".join(f"{r['name']} {fmt(r[col], nd)}" for _, r in d.iterrows()))
    line("Minutes", "minutes", n=5, nd=0)
    line("Goals", "goals", nd=0)
    line("Assists", "assists", nd=0)
    line("xG", "xg")
    line("xA", "xa")
    line("Chances created", "chances_created", nd=0)
    line("Final-third entries per 90 (min 180')", "final_third_entries_p90", min_minutes=180)
    line("Defensive actions per 90 (min 180')", "defensive_actions_p90", min_minutes=180)
    r = rat[rat["count"] >= 2].sort_values("mean", ascending=False).head(3)
    if len(r):
        L.append("- **Average FotMob rating (min 2 rated apps):** " + ", ".join(f"{n} {v:.2f}" for n, v in r["mean"].items()))
    L.append("")

    if prev:
        a = per90(mp, ["xg", "xa"], 180).assign(xgxa=lambda d: d.xg_p90 + d.xa_p90)
        b = per90(pms[pms.month == prev], ["xg", "xa"], 180).assign(xgxa=lambda d: d.xg_p90 + d.xa_p90)
        j = a.merge(b[["player_id", "xgxa"]], on="player_id", suffixes=("", "_prev"))
        j["delta"] = j.xgxa - j.xgxa_prev
        if len(j):
            up, down = j.sort_values("delta").iloc[-1], j.sort_values("delta").iloc[0]
            L += ["## Biggest changes vs previous month", ""]
            if up.delta > 0:
                L.append(f"- **Attacking output up:** {up['name']} — xG+xA per 90 {up.xgxa_prev:.2f} → {up.xgxa:.2f}.")
            if down.delta < 0:
                L.append(f"- **Attacking output down:** {down['name']} — xG+xA per 90 {down.xgxa_prev:.2f} → {down.xgxa:.2f}.")
            L += ["", f"*xG+xA per 90 for the {len(j)} players with at least 180 minutes in both months.*", ""]
    L += ["---", "*Generated automatically from the data; no manual edits.*"]
    return title, "\n".join(L)


def season_report(matches, pms) -> str:
    t = _team_month(matches)
    agg = per90(pms, ["goals", "assists", "xg", "xa"])
    top = agg.sort_values(["goals", "xg"], ascending=False).head(3)
    return "\n".join([
        f"# Season review {SEASON_LABEL}", "",
        "> **Placeholder.** The full season review is written after the final match. Below is a season-to-date snapshot.", "",
        f"- **Record (all competitions):** {t['n']} played, {t['w']}W {t['d']}D {t['l']}L, goals {t['gf']}–{t['ga']}",
        f"- **xG per match:** {t['xg']:.2f} for, {t['xga']:.2f} against",
        "- **Top scorers:** " + ", ".join(f"{r['name']} {int(r.goals)}" for _, r in top.iterrows()),
        "", "---", "*Generated automatically from the data.*"])


def build_all(con) -> None:
    d = load(con)
    matches, pms, shots, bu, bu_units = d["matches"], d["pms"], d["shots"], d["bu"], d["bu_units"]
    for sub in ("match", "monthly", "season"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    index = {"match": [], "monthly": [], "season": []}
    for _, m in matches.iterrows():
        (OUT / "match" / f"{m.match_id}.md").write_text(match_report(m, matches, pms, shots, bu, bu_units))
        index["match"].append(dict(id=int(m.match_id), title=_score_line(m), competition=m.competition,
                                   date=m.kickoff_local.strftime("%Y-%m-%d"), result=m.result))
    today_month = datetime.now(ZoneInfo(LOCAL_TZ)).strftime("%Y-%m")
    for month in sorted(matches.month.unique()):
        title, md = monthly_report(month, matches, pms, today_month)
        (OUT / "monthly" / f"{month}.md").write_text(md)
        index["monthly"].append(dict(id=month, title=title, matches=int((matches.month == month).sum())))
    (OUT / "season" / f"{SEASON_LABEL}.md").write_text(season_report(matches, pms))
    index["season"].append(dict(id=SEASON_LABEL, title=f"Season review {SEASON_LABEL}", placeholder=True))
    index["match"].reverse()
    index["monthly"].reverse()
    (OUT / "index.json").write_text(json.dumps(index, indent=1))
