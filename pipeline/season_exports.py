"""Offline exports of the season analysis (same data as site/data/season_analysis.json).

    python -m pipeline.season_exports [OUT_DIR]     # default: ./exports (git-ignored)

Produces, with base name chelsea-season-analysis-<season>:
  .html      self-contained interactive page (Chart.js, CSS, JS and data inlined; works offline)
  .pdf       static print version (matplotlib charts + tables), rendered with headless Chrome
  .xlsx      workbook with one sheet per topic
  -csv.zip   the same tables as CSV files
"""
from __future__ import annotations

import base64
import html
import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, ROOT, SEASON_LABEL, SITE_DATA_DIR

CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"
BLUE, GOLD, RED, GREY, CYAN, LIGHT = "#034694", "#DBA111", "#c0392b", "#8a94a6", "#2a9fd6", "#b9c6dc"
LGN = {"PL": "Premier League", "LL": "La Liga", "SA": "Serie A", "BL": "Bundesliga", "L1": "Ligue 1"}
ABBR = {"Fulham": "FUL", "Luton": "LUT", "Brighton": "BHA", "Arsenal": "ARS", "Leeds": "LEE", "Hull": "HUL", "Brentford": "BRE",
        "Bournemouth": "BOU", "Everton": "EVE", "Tottenham": "TOT", "Liverpool": "LIV", "Man United": "MUN", "Sunderland": "SUN"}


def load():
    return json.loads((SITE_DATA_DIR / "season_analysis.json").read_text())


# ---------------------------------------------------------------- shared calculations (mirror site/js/season.js)
def _num(v):
    return v if isinstance(v, (int, float)) and v is not None else 0


def _sum(rs, k):
    return sum(_num(m.get(k)) for m in rs)


def _mean(rs, k):
    v = [m[k] for m in rs if isinstance(m.get(k), (int, float))]
    return sum(v) / len(v) if v else None


def _fx(x, dp):
    return "n/a" if x is None else f"{x:.{dp}f}"


def _sg(x, dp):
    return "n/a" if x is None else ("+" if x > 0 else "") + f"{x:.{dp}f}"


def _per(rs, k, dp):
    return _fx(_sum(rs, k) / len(rs), dp)


LINES = {
    "Attack": [("Goals per match", lambda r: _per(r, "gf", 2)), ("xG per match", lambda r: _per(r, "xg", 2)),
               ("Non-penalty xG per match", lambda r: _per(r, "npxg", 2)), ("Goals minus xG (total)", lambda r: _sg(_sum(r, "gf") - _sum(r, "xg"), 1)),
               ("Shots per match", lambda r: _per(r, "sh", 1)), ("Shots on target per match", lambda r: _per(r, "sot", 1)),
               ("xG per shot", lambda r: _fx(_sum(r, "xg") / _sum(r, "sh"), 3)), ("Big chances per match", lambda r: _per(r, "bc", 1)),
               ("Touches in opposition box per match", lambda r: _per(r, "box", 1))],
    "Defence": [("Goals conceded per match", lambda r: _per(r, "ga", 2)), ("xG conceded per match", lambda r: _per(r, "xga", 2)),
                ("Shots conceded per match", lambda r: _per(r, "osh", 1)), ("Shots on target conceded per match", lambda r: _per(r, "osot", 1)),
                ("xG per shot conceded", lambda r: _fx(_sum(r, "xga") / _sum(r, "osh"), 3)), ("Big chances conceded per match", lambda r: _per(r, "obc", 1)),
                ("Clean sheets", lambda r: f"{sum(1 for m in r if m['ga'] == 0)} of {len(r)}"), ("Tackles per match", lambda r: _per(r, "tkl", 1)),
                ("Interceptions per match", lambda r: _per(r, "itc", 1))],
    "Possession & build-up": [("Possession % (match average)", lambda r: _fx(_mean(r, "poss"), 1)), ("Pass accuracy % (match average)", lambda r: _fx(_mean(r, "pacc"), 1)),
                              ("Long-ball share of passes %", lambda r: _fx(_mean(r, "lbs"), 1)), ("Long-ball accuracy %", lambda r: _fx(_mean(r, "lba"), 1)),
                              ("Goalkeeper passes played long %", lambda r: _fx(_mean(r, "gkls"), 1)), ("Goalkeeper long-ball accuracy %", lambda r: _fx(_mean(r, "gkla"), 1)),
                              ("Final-third entries per match", lambda r: _fx(_mean(r, "fte"), 1)), ("Line-breaking passes per match (PL only)", lambda r: _fx(_mean(r, "lbp"), 1))],
    "Pressing": [("PPDA, Understat (PL rounds 1–8 only)", lambda r: _fx(_mean(r, "ppda"), 2)), ("Opponent PPDA against us, Understat", lambda r: _fx(_mean(r, "oppda"), 2)),
                 ("PPDA proxy, FotMob (all matches)", lambda r: _fx(_mean(r, "ppdap"), 2))],
    "Set pieces & discipline": [("Set-piece goals scored (shot-based)", lambda r: f"{_sum(r, 'spg')}"), ("Set-piece xG created", lambda r: _fx(_sum(r, "spxg"), 2)),
                                ("Set-piece goals conceded (shot-based)", lambda r: f"{_sum(r, 'ospg')}"), ("Set-piece xG conceded", lambda r: _fx(_sum(r, "ospxg"), 2)),
                                ("Corners per match", lambda r: _per(r, "cor", 1)), ("Fouls per match", lambda r: _per(r, "fo", 1)),
                                ("Yellow cards", lambda r: f"{_sum(r, 'yc')}"), ("Red cards", lambda r: f"{_sum(r, 'rc')}")],
}


def splits(D):
    M = D["matches"]
    return {"All matches": M, "Premier League": [m for m in M if m["c"] == "PL"], "PL home": [m for m in M if m["c"] == "PL" and m["v"] == "H"],
            "PL away": [m for m in M if m["c"] == "PL" and m["v"] == "A"], "EFL Cup": [m for m in M if m["c"] == "EFL"]}


def record_rows(D):
    out = []
    for name, rs in splits(D).items():
        w = sum(m["r"] == "W" for m in rs); d = sum(m["r"] == "D" for m in rs); l = sum(m["r"] == "L" for m in rs)
        out.append(dict(Split=name, Played=len(rs), W=w, D=d, L=l, Points=3 * w + d, PPG=round((3 * w + d) / len(rs), 2), GF=_sum(rs, "gf"), GA=_sum(rs, "ga"),
                        xG=round(_sum(rs, "xg"), 2), xGA=round(_sum(rs, "xga"), 2)))
    return out


def metric_lines(D):
    sp = splits(D)
    rows = []
    for topic, lines in LINES.items():
        for label, f in lines:
            rows.append({"Topic": topic, "Metric": label, **{k: f(v) for k, v in sp.items()}})
    return rows


def mdefs(D):
    return {m["k"]: m for m in D["metrics"]}


def fmt_m(MK, k, x):
    if x is None:
        return "n/a"
    return _sg(x, MK[k]["dp"]) if MK[k]["signed"] else f"{x:.{MK[k]['dp']}f}"


def rankings(D):
    MK, T = mdefs(D), D["elite"]
    che = next(t for t in T if t["n"] == "Chelsea")
    rows = []
    for m in D["metrics"]:
        k = m["k"]
        better = (lambda a, b: a < b) if m["low"] else (lambda a, b: a > b)
        rank = 1 + sum(1 for o in T if better(o["v"][k], che["v"][k]))
        vals = sorted(t["v"][k] for t in T)
        best = sorted(T, key=lambda t: t["v"][k], reverse=not m["low"])[0]
        rows.append(dict(Metric=m["label"], Chelsea=che["v"][k], Rank=rank, Of=len(T), **{"Elite median": vals[len(vals) // 2]},
                         Best=best["n"], **{"Best value": best["v"][k]}, **{"Lower is better": m["low"]},
                         **{"Chelsea percentile (big five)": che["pct"].get(k)}))
    return rows


def frames(D):
    MK = mdefs(D)
    matches = pd.DataFrame(D["matches"]).rename(columns={
        "id": "match_id", "d": "date", "c": "comp", "v": "venue", "o": "opponent", "gf": "goals_for", "ga": "goals_against", "r": "result",
        "pens": "shootout", "xg": "xg", "xga": "xg_against", "npxg": "npxg", "sh": "shots", "sot": "shots_on_target", "osh": "shots_against",
        "osot": "sot_against", "bc": "big_chances", "obc": "big_chances_against", "poss": "possession_pct", "pacc": "pass_accuracy_pct",
        "box": "touches_opp_box", "cor": "corners", "fo": "fouls", "yc": "yellow_cards", "rc": "red_cards", "tkl": "tackles", "itc": "interceptions",
        "ppda": "ppda_understat", "ppdap": "ppda_proxy_fotmob", "oppda": "opp_ppda_understat", "lbs": "long_ball_share_pct", "lba": "long_ball_accuracy_pct",
        "gkls": "gk_long_share_pct", "gkla": "gk_long_accuracy_pct", "fte": "final_third_entries", "lbp": "line_breaking_passes",
        "spg": "set_piece_goals", "spxg": "set_piece_xg", "ospg": "set_piece_goals_against", "ospxg": "set_piece_xg_against", "fm": "formation"})
    core = ["match_id", "date", "competition", "venue", "opponent", "goals_for", "goals_against", "result", "shootout", "formation", "xg", "xg_against", "npxg",
            "shots", "shots_on_target", "shots_against", "sot_against", "big_chances", "big_chances_against", "possession_pct", "pass_accuracy_pct",
            "touches_opp_box", "corners", "fouls", "yellow_cards", "red_cards", "tackles", "interceptions", "set_piece_goals", "set_piece_xg",
            "set_piece_goals_against", "set_piece_xg_against"]
    bu = ["match_id", "date", "opponent", "venue", "competition", "ppda_understat", "opp_ppda_understat", "ppda_proxy_fotmob", "long_ball_share_pct",
          "long_ball_accuracy_pct", "gk_long_share_pct", "gk_long_accuracy_pct", "final_third_entries", "line_breaking_passes", "possession_pct"]
    P = pd.DataFrame(D["players"]).rename(columns={"n": "player", "p": "pos", "ap": "apps", "st": "starts", "mi": "minutes", "g": "goals", "a": "assists",
        "sh": "shots", "kp": "key_passes", "tkl": "tackles", "itc": "interceptions", "rec": "recoveries", "clr": "clearances", "dw": "duels_won", "dl": "duels_lost",
        "lbp": "line_breaking_passes", "fte": "final_third_entries", "yc": "yellow_cards", "rc": "red_cards", "gp": "goals_prevented", "rt": "avg_rating"})
    P["xg_xa_per90"] = ((P["xg"] + P["xa"]) / P["minutes"] * 90).round(2)
    P["tkl_int_per90"] = ((P["tackles"] + P["interceptions"]) / P["minutes"] * 90).round(2)
    P["pct_of_minutes"] = (P["minutes"] / (len(D["matches"]) * 90) * 100).round(1)
    elite = []
    pct = []
    for t in D["elite"]:
        base = {"Team": t["n"], "League": t["league"], "League pos": t["pos"], "Played": t["mp"], "W": t["w"], "D": t["d"], "L": t["l"], "Pts": t["pts"],
                "GF": t["gf"], "GA": t["ga"], "xTable pos": t["xpos"]}
        elite.append({**base, **{MK[k]["label"]: v for k, v in t["v"].items()}})
        pct.append({"Team": t["n"], "League": t["league"], **{MK[k]["label"]: v for k, v in t["pct"].items()}})
    ppda = pd.DataFrame(D["pl_ppda"], columns=["Team", "PPDA (Understat, PL rounds 1-8)"])
    ppda.insert(0, "Rank", range(1, len(ppda) + 1))
    findings = ([{"Type": "Verdict", "Text": D["verdict"]}] + [{"Type": f"KPI: {k['label']}", "Text": f"{k['value']} ({k.get('detail', '')})"} for k in D["kpis"]]
                + [{"Type": "Strength", "Text": s} for s in D["strengths"]] + [{"Type": "Weakness", "Text": s} for s in D["weaknesses"]]
                + [{"Type": "Observation", "Text": s} for s in D["observations"]] + [{"Type": "Bottom line", "Text": D["bottom_line"]}]
                + [{"Type": f"Commentary: {k}", "Text": v} for k, v in D["text"].items()])
    meta = D["meta"]
    notes = ([{"Item": "Title", "Value": D["title"]}, {"Item": "Chelsea data through", "Value": meta["last_match"]},
              {"Item": "Chelsea matches", "Value": meta["n_matches"]}, {"Item": "Elite data date", "Value": meta["elite_data_date"]},
              {"Item": "Elite set", "Value": meta["elite_rule"]}, {"Item": "Clubs in big five (percentile base)", "Value": meta["n_big5"]},
              {"Item": "Built", "Value": f"{meta['generated_at']} ({meta['timezone']})"}]
             + [{"Item": f"Note {i + 1}", "Value": n} for i, n in enumerate(D["notes"])]
             + [{"Item": f"Source: {s['title']}", "Value": f"{s['use']} – {s['href']}"} for s in D["sources"]]
             + [{"Item": "Metric definition: " + m["label"], "Value": f"key {m['k']}; {'lower' if m['low'] else 'higher'} is better"} for m in D["metrics"]])
    inj = pd.DataFrame(D["injuries"]).rename(columns={"title": "Player", "detail": "Detail", "status": "Status"})
    inj["As of"] = D["injuries_asof"]
    return {
        "Sources & notes": pd.DataFrame(notes),
        "Findings": pd.DataFrame(findings),
        "Chelsea matches": matches[core],
        "Chelsea splits": pd.DataFrame(record_rows(D)),
        "Chelsea metrics by split": pd.DataFrame(metric_lines(D)),
        "Player season stats": P,
        "Build-up & pressing": matches[bu],
        "PL PPDA table": ppda,
        "Elite comparison": pd.DataFrame(elite),
        "Elite percentiles": pd.DataFrame(pct),
        "Chelsea rankings": pd.DataFrame(rankings(D)),
        "Injuries": inj,
    }


def write_xlsx(D, path: Path):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    fr = frames(D)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in fr.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "B2"
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="034694")
                c.alignment = Alignment(wrap_text=True, vertical="top")
            for i, col in enumerate(df.columns, 1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].tolist()[:200]])
                ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 90)
            if name in ("Findings", "Sources & notes", "Injuries"):
                for row in ws.iter_rows(min_row=2):
                    for c in row:
                        c.alignment = Alignment(wrap_text=True, vertical="top")
            if name in ("Elite comparison", "Elite percentiles", "Chelsea matches", "Player season stats"):
                for row in ws.iter_rows(min_row=2):
                    if row[0].value == "Chelsea":
                        for c in row:
                            c.fill = PatternFill("solid", fgColor="FFF6DC")
    return fr


def write_csv_zip(fr, path: Path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (name, df) in enumerate(fr.items(), 1):
            fn = f"{i:02d}_{name.lower().replace(' & ', '_').replace(' ', '_')}.csv"
            z.writestr(fn, df.to_csv(index=False))


# ---------------------------------------------------------------- standalone HTML
def chart_js() -> str:
    f = DATA_DIR / "vendor" / "chart.umd.min.js"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(CHART_JS_URL, f)
    return f.read_text()


def write_html(D, path: Path):
    css = (ROOT / "site" / "css" / "style.css").read_text()
    js = (ROOT / "site" / "js" / "season.js").read_text()
    data = json.dumps(D, ensure_ascii=False).replace("</", "<\\/")
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(D['title'])}</title>
<style>{css}
.sa-filters{{top:0}}</style>
<script>{chart_js()}</script>
</head><body>
<header class="topbar"><span class="brand"><span class="logo">BA</span> Blues Analytics · Season analysis</span>
<a href="https://omarhady1992.github.io/blues-analytics/#/season-analysis" style="color:#dfe8f7;font-size:.85rem">Live version</a></header>
<main id="app"></main>
<footer><p>Unofficial fan project, not affiliated with Chelsea FC. Data: Opta via premierleague.com, FotMob, Understat. Offline copy built {html.escape(D['meta']['generated_at'])} (Cairo time).</p></footer>
<script>window.SEASON_DATA = {data};</script>
<script>{js}</script>
<script>Chart.defaults.font.family = getComputedStyle(document.body).fontFamily; Chart.defaults.maintainAspectRatio = false;
renderSeason(document.getElementById("app"), window.SEASON_DATA);</script>
</body></html>"""
    path.write_text(doc)


# ---------------------------------------------------------------- PDF
def _png(fig) -> str:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def pdf_charts(D):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({"font.size": 8.5, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#e3e8ef",
                         "grid.linewidth": .6, "axes.axisbelow": True, "axes.edgecolor": "#9aa5b5"})
    M = D["matches"]
    lab = [("@" if m["v"] == "A" else "") + ABBR.get(m["o"], m["o"][:3].upper()) for m in M]
    x = np.arange(len(M))
    out = {}
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    ax.bar(x - .2, [m["xg"] for m in M], .4, color=BLUE, label="xG for")
    ax.bar(x + .2, [m["xga"] for m in M], .4, color=RED, label="xG against")
    for i, m in enumerate(M):
        ax.text(i, max(m["xg"], m["xga"]) + .08, f"{m['gf']}–{m['ga']}", ha="center", fontsize=7, color="#334")
    ax.set_xticks(x, lab); ax.legend(frameon=False, ncol=2, loc="upper left"); ax.set_ylabel("xG"); ax.set_ylim(0, 3.5)
    out["xg"] = _png(fig)
    roll = lambda k: [np.mean([M[j][k] for j in range(max(0, i - 2), i + 1)]) for i in range(len(M))]
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    ax.plot(x, roll("xg"), color=BLUE, lw=2, label="xG for, 3-match rolling"); ax.fill_between(x, roll("xg"), color=BLUE, alpha=.12)
    ax.plot(x, roll("xga"), color=RED, lw=2, label="xG against, 3-match rolling")
    ax.set_xticks(x, lab); ax.legend(frameon=False, ncol=2, loc="upper right"); ax.set_ylim(0, 3)
    out["roll"] = _png(fig)
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    ax.plot(x, [m["poss"] for m in M], color=BLUE, lw=2, marker="o", ms=3, label="Possession %")
    ax.plot(x, [m["gkla"] for m in M], color=GOLD, lw=2, marker="o", ms=3, label="GK long-ball accuracy %")
    ax.set_xticks(x, lab); ax.set_ylim(0, 100); ax.legend(frameon=False, ncol=2, loc="upper left")
    out["poss"] = _png(fig)
    pp = D["pl_ppda"]
    fig, ax = plt.subplots(figsize=(3.5, 3.9))
    ax.barh([r[0] for r in pp][::-1], [r[1] for r in pp][::-1], color=[BLUE if r[0] == "Chelsea" else LIGHT for r in pp][::-1])
    ax.set_xlabel("PPDA (lower = more aggressive press)"); ax.tick_params(axis="y", labelsize=7.5); ax.grid(axis="y", visible=False)
    out["ppda"] = _png(fig)
    P = D["players"]
    ga = sorted([p for p in P if p["g"] + p["a"] > 0], key=lambda p: -(p["g"] + p["a"]))[:8][::-1]
    fig, ax = plt.subplots(figsize=(3.5, 2.8))
    ax.barh([p["n"] for p in ga], [p["g"] for p in ga], color=BLUE, label="Goals")
    ax.barh([p["n"] for p in ga], [p["a"] for p in ga], left=[p["g"] for p in ga], color=GOLD, label="Assists")
    ax.legend(frameon=False, loc="lower right"); ax.grid(axis="y", visible=False)
    out["ga"] = _png(fig)
    T = D["elite"]
    MK = mdefs(D)

    def scatter(kx, ky, name, diag=False):
        fig, ax = plt.subplots(figsize=(3.6, 3.3))
        for t in T:
            c = BLUE if t["n"] == "Chelsea" else GOLD if t["lg"] == "PL" else CYAN
            ax.scatter(t["v"][kx], t["v"][ky], s=60 if t["n"] == "Chelsea" else 28, color=c, zorder=3)
            ax.annotate(t["n"], (t["v"][kx], t["v"][ky]), xytext=(3, 3), textcoords="offset points", fontsize=6.5,
                        color=BLUE if t["n"] == "Chelsea" else "#445", weight="bold" if t["n"] == "Chelsea" else "normal")
        if diag:
            lo = min(min(t["v"][kx], t["v"][ky]) for t in T); hi = max(max(t["v"][kx], t["v"][ky]) for t in T)
            ax.plot([lo, hi], [lo, hi], ls="--", color=GREY, lw=1)
        ax.set_xlabel(MK[kx]["label"]); ax.set_ylabel(MK[ky]["label"])
        out[name] = _png(fig)
    scatter("xg_pm", "xga_pm", "sc1"); scatter("xppg", "ppg", "sc2", diag=True)
    scatter("poss", "pw3_pm", "sc3"); scatter("box_pm", "bc_pm", "sc4")
    keys = list(D["radar"].keys())
    che = next(t for t in T if t["n"] == "Chelsea")
    med = {k: sorted(t["pct"][k] for t in T)[len(T) // 2] for k in keys}
    ang = np.linspace(0, 2 * np.pi, len(keys), endpoint=False).tolist()
    fig = plt.figure(figsize=(4.2, 4.2)); ax = fig.add_subplot(polar=True)
    for vals, c, l in [([che["pct"][k] for k in keys], BLUE, "Chelsea"), ([med[k] for k in keys], GOLD, "Elite median percentile")]:
        ax.plot(ang + ang[:1], vals + vals[:1], color=c, lw=2, label=l); ax.fill(ang + ang[:1], vals + vals[:1], color=c, alpha=.15)
    ax.set_xticks(ang, [D["radar"][k] for k in keys], fontsize=7.5); ax.set_ylim(0, 100); ax.set_yticks([25, 50, 75, 100], ["25", "50", "75", "100"], fontsize=6.5)
    ax.set_theta_offset(np.pi / 2); ax.set_theta_direction(-1); ax.set_rlabel_position(195)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(.5, -.06), ncol=2, fontsize=7.5)
    out["radar"] = _png(fig)
    return out


def _tbl(cols, rows, left=1, cls=""):
    e = html.escape
    head = "".join(f'<th class="{"l" if i < left else ""}">{e(str(c))}</th>' for i, c in enumerate(cols))
    body = "".join("<tr" + (' class="hl"' if r and str(r[0]) == "Chelsea" else "") + ">" +
                   "".join(f'<td class="{"l" if i < left else ""}">{v if str(v).startswith("<") else e(str(v))}</td>' for i, v in enumerate(r)) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def write_pdf(D, path: Path):
    e = html.escape
    ch = pdf_charts(D)
    MK = mdefs(D)
    T = D["elite"]
    meta = D["meta"]
    lines = metric_lines(D)
    spl = list(splits(D).keys())

    def topic_table(topic):
        return _tbl(["Metric"] + spl, [[r["Metric"]] + [r[s] for s in spl] for r in lines if r["Topic"] == topic], cls="small")
    rec = record_rows(D)
    res = lambda r: f'<span class="b {r}">{r}</span>'
    mlog = _tbl(["Date", "Comp", "H/A", "Opponent", "Score", "Res", "xG", "xGA", "Shots", "Poss %", "PPDA"],
                [[m["d"], m["c"], m["v"], m["o"], f"{m['gf']}–{m['ga']}" + (f" (p {m['pens']})" if m["pens"] else ""), res(m["r"]), _fx(m["xg"], 2), _fx(m["xga"], 2),
                  f"{m['sh']}–{m['osh']}", _fx(m["poss"], 1), _fx(m["ppda"], 1)] for m in D["matches"]], left=4, cls="small")
    gks = [p for p in D["players"] if p["p"] == "GK"]
    gkt = _tbl(["Goalkeeper", "Apps", "Mins", "Goals prevented", "Per 90", "Avg rating"],
               [[p["n"], p["ap"], p["mi"], _sg(p["gp"], 2), _sg(p["gp"] / p["mi"] * 90, 2), _fx(p["rt"], 2)] for p in gks], cls="small")
    avail = len(D["matches"]) * 90
    P = D["players"]
    sq = _tbl(["Player", "Pos", "Age", "Apps", "St", "Mins", "% mins", "G", "A", "xG", "xA", "xG+xA/90", "Tkl", "Int", "Rating"],
              [[p["n"], p["p"], p["age"] if p["age"] is not None else "n/a", p["ap"], p["st"], p["mi"], _fx(p["mi"] / avail * 100, 0), p["g"], p["a"], _fx(p["xg"], 2), _fx(p["xa"], 2),
                _fx((p["xg"] + p["xa"]) / p["mi"] * 90, 2) if p["mi"] >= 270 else "–", p["tkl"], p["itc"], _fx(p["rt"], 2)] for p in P], left=2, cls="small")
    aged = [p for p in P if p["age"] is not None]
    w_age = sum(p["age"] * p["mi"] for p in aged) / sum(p["mi"] for p in aged)
    squad_text = D["text"]["squad"].replace("players have been used, and", f"players have been used. The minutes-weighted average age is {w_age:.1f}, and", 1)
    elite_tables = []
    for g, keys in D["groups"].items():
        s = sorted(T, key=lambda t: t["v"][keys[0]], reverse=not MK[keys[0]]["low"])
        elite_tables.append(f"<h3>{e(g)} <span class='muted'>(sorted by {e(MK[keys[0]]['label'])})</span></h3>" +
                            _tbl(["Team", "League", "Pld", "Pts"] + [MK[k]["short"] for k in keys],
                                 [[t["n"], LGN[t["lg"]], t["mp"], t["pts"]] + [fmt_m(MK, k, t["v"][k]) for k in keys] for t in s], left=2, cls="small"))
    rk = rankings(D)
    rtab = _tbl(["Metric", "Chelsea", "Rank", "Elite median", "Best", "Big-five pct"],
                [[r["Metric"], fmt_m(MK, m["k"], r["Chelsea"]),
                  f'<span class="{"good" if r["Rank"] <= 4 else "bad" if r["Rank"] >= r["Of"] - 3 else ""}">{r["Rank"]} / {r["Of"]}</span>',
                  fmt_m(MK, m["k"], r["Elite median"]), f"{r['Best']} ({fmt_m(MK, m['k'], r['Best value'])})",
                  "–" if r["Chelsea percentile (big five)"] is None else r["Chelsea percentile (big five)"]] for r, m in zip(rk, D["metrics"])], cls="small")
    kpis = "".join(f'<div class="kpi"><div class="v {"bad" if k.get("tone") == "bad" else ""}">{e(k["value"])}</div><div class="l">{e(k["label"])}</div><div class="d">{e(k.get("detail", ""))}</div></div>' for k in D["kpis"])
    inj = "".join(f'<tr><td class="l"><strong>{e(i["title"])}</strong></td><td class="l">{e(i["detail"])}</td><td><span class="pill {i["status"].lower()}">{e(i["status"])}</span></td></tr>' for i in D["injuries"])
    img = lambda k, w="100%": f'<img src="{ch[k]}" style="width:{w}">'
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(D['title'])}</title><style>
@page {{ size: A4; margin: 14mm 13mm 16mm; }}
body {{ font-family: "DejaVu Sans", Arial, sans-serif; color:#1b2533; font-size:9pt; line-height:1.4; }}
h1 {{ color:#022a5c; font-size:19pt; margin:0 0 4px; }} h2 {{ color:#034694; font-size:12.5pt; margin:16px 0 6px; border-bottom:2px solid #DBA111; padding-bottom:2px; }}
h3 {{ font-size:9.5pt; color:#022a5c; margin:10px 0 4px; }} p {{ margin:4px 0 6px; }} .muted {{ color:#66758a; font-weight:normal; }}
.cover {{ background:#034694; color:#fff; padding:14px 16px; border-radius:8px; margin-bottom:10px; }} .cover h1 {{ color:#fff; }} .cover p {{ color:#dfe8f7; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin:8px 0; }} .kpi {{ border:1px solid #dde3ec; border-radius:6px; padding:6px 8px; }}
.kpi .v {{ font-size:15pt; font-weight:bold; color:#034694; }} .kpi .v.bad, .bad {{ color:#c0392b; }} .good {{ color:#1f9d55; font-weight:bold; }}
.kpi .l {{ font-size:8pt; }} .kpi .d {{ font-size:7.5pt; color:#66758a; }}
table {{ border-collapse:collapse; width:100%; margin:4px 0 8px; }} th, td {{ padding:3px 5px; border-bottom:1px solid #e3e8ef; text-align:right; }}
th {{ background:#e8eff9; color:#022a5c; font-size:7.8pt; }} td.l, th.l {{ text-align:left; }} table.small td {{ font-size:7.8pt; }} tr.hl td {{ background:#fff6dc; font-weight:bold; }}
.b {{ display:inline-block; width:15px; text-align:center; color:#fff; border-radius:3px; font-weight:bold; font-size:7pt; }} .W {{ background:#1f9d55; }} .D {{ background:#8a94a6; }} .L {{ background:#d64545; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; align-items:start; }} .avoid {{ break-inside:avoid; }} .pb {{ break-before:page; }}
.callout {{ background:#fffaf0; border-left:4px solid #DBA111; padding:6px 10px; margin:8px 0; }}
.pill {{ padding:1px 6px; border-radius:8px; font-size:7.5pt; }} .pill.out {{ background:#fde2e2; }} .pill.doubt {{ background:#fff1cc; }} .pill.returning {{ background:#dcf3e5; }}
ul, ol {{ margin:4px 0 6px 16px; padding:0; }} li {{ margin:2px 0; }} .pros li::marker {{ content:"+  "; color:#1f9d55; }} .cons li::marker {{ content:"−  "; color:#c0392b; }}
</style></head><body>
<div class="cover"><h1>{e(D['title'])}</h1><p>{e(D['summary'])}</p>
<p style="font-size:8pt">Chelsea data to {e(meta['last_match'])} ({meta['n_matches']} competitive matches) · elite data {e(meta['elite_data_date'])} · built {e(meta['generated_at'])} Cairo time · Blues Analytics</p></div>
<h2>Verdict</h2><p>{e(D['verdict'])}</p><div class="kpis">{kpis}</div>
<div class="callout"><strong>Bottom line.</strong> {e(D['bottom_line'])}</div>
<div class="two avoid"><div><h3>Strengths</h3><ul class="pros">{''.join(f'<li>{e(s)}</li>' for s in D['strengths'])}</ul></div>
<div><h3>Weaknesses</h3><ul class="cons">{''.join(f'<li>{e(s)}</li>' for s in D['weaknesses'])}</ul></div></div>
<h2>Results and form</h2>
{_tbl(["Split", "Played", "W", "D", "L", "Pts", "PPG", "GF", "GA", "xG", "xGA"], [list(r.values()) for r in rec], cls="small")}
<div class="avoid"><h3>xG for and against, match by match (score above each pair)</h3>{img("xg")}</div>
<div class="avoid"><h3>3-match rolling xG</h3>{img("roll")}</div>
<p>{e(D['text']['results'])}</p>
<div class="avoid"><h3>Match log</h3>{mlog}</div>
<h2 class="pb">Attack</h2>{topic_table("Attack")}<p>{e(D['text']['attack'])}</p>
<h2>Defence and goalkeeping</h2>{topic_table("Defence")}{gkt}<p>{e(D['text']['defence'])}</p>
<h2>Possession and build-up</h2>{topic_table("Possession & build-up")}<div class="avoid">{img("poss")}</div><p>{e(D['text']['buildup'])}</p>
<h2 class="pb">Pressing</h2><div class="two"><div>{topic_table("Pressing")}<p>{e(D['text']['pressing'])}</p></div><div>{img("ppda")}</div></div>
<h2>Set pieces and discipline</h2>{topic_table("Set pieces & discipline")}<p>{e(D['text']['setpieces'])}</p>
<h2 class="pb">Squad</h2>{sq}<div class="two avoid"><div>{img("ga")}</div><div><p>{e(squad_text)}</p></div></div>
<h2>Injuries and absences</h2><p class="muted">{e(D['injuries_asof'])}</p><table class="small"><tbody>{inj}</tbody></table>
<h2 class="pb">Elite comparison</h2><p>League matches only, per match. Elite = {e(meta['elite_rule'])} ({meta['n_elite']} clubs, as of {e(meta['elite_data_date'])}).
Chelsea in blue, other Premier League elite in gold, other big-five elite in cyan.</p>
<div class="two avoid"><div><h3>xG vs xG conceded per match</h3>{img("sc1")}</div><div><h3>Points vs expected points per match (dashed = equal)</h3>{img("sc2")}</div></div>
<div class="two avoid"><div><h3>Possession vs high regains</h3>{img("sc3")}</div><div><h3>Box touches vs big chances</h3>{img("sc4")}</div></div>
<p>{e(D['text']['scatter'])}</p>
{''.join(f'<div class="avoid">{t}</div>' for t in elite_tables)}
<h2 class="pb">Where Chelsea rank</h2><p class="muted">Rank among the {meta['n_elite']} elite clubs (1 = best; for conceded, fouls and cards, fewer is better). Big-five pct = percentile among all {meta['n_big5']} big-five league clubs.</p>{rtab}
<div class="two avoid"><div><h3>Percentile radar: Chelsea vs elite median</h3>{img("radar")}</div><div><h3>Observations</h3><ol>{''.join(f'<li>{e(s)}</li>' for s in D['observations'])}</ol></div></div>
<h2>Data notes and sources</h2><ul>{''.join(f'<li>{e(s)}</li>' for s in D['notes'])}</ul>
<ul>{''.join(f'<li>{e(s["title"])}: {e(s["use"])} ({e(s["href"])})</li>' for s in D['sources'])}</ul>
</body></html>"""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "report.html"
        src.write_text(doc)
        chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={path}", src.as_uri()],
                       check=True, capture_output=True, timeout=120)


def main(out_dir=None):
    D = load()
    out = Path(out_dir or ROOT / "exports")
    out.mkdir(parents=True, exist_ok=True)
    base = out / f"chelsea-season-analysis-{SEASON_LABEL}"
    write_html(D, base.with_suffix(".html"))
    fr = write_xlsx(D, base.with_suffix(".xlsx"))
    write_csv_zip(fr, out / f"{base.name}-csv.zip")
    write_pdf(D, base.with_suffix(".pdf"))
    for f in sorted(out.glob(base.name + "*")):
        print(f"   {f}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
