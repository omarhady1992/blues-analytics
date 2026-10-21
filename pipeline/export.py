"""Write the processed JSON the static website reads (site/data/*.json).

Only our processed tables go out — never the raw source responses.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from . import ingest
from .analysis import load
from .config import FOTMOB_TEAM_ID, LOCAL_TZ, SEASON_LABEL, SITE_DATA_DIR
from .sources import fotmob

PLAYER_STAT_COLS = [
    "started", "minutes", "goals", "assists", "xg", "xa", "xgot", "shots", "shots_on_target", "chances_created",
    "big_chances_created", "touches", "touches_opp_box", "passes", "passes_accurate", "final_third_entries",
    "pen_area_entries", "line_breaking_passes", "long_balls", "long_balls_accurate", "crosses", "crosses_accurate",
    "dribbles", "dribbles_won", "tackles", "interceptions", "recoveries", "clearances", "blocks",
    "defensive_actions", "duels_won", "duels_lost", "aerials_won", "aerials_lost", "fouls", "was_fouled",
    "dispossessed", "yellow_cards", "red_cards", "saves", "goals_conceded", "goals_prevented", "rating",
    "distance_m", "sprints", "top_speed_kmh",
]


def clean(v):
    """JSON-safe value: NaN -> None, numpy -> python, round floats."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        if math.isnan(v):
            return None
        return int(v) if v.is_integer() else round(v, 3)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    return v


def records(df: pd.DataFrame) -> list[dict]:
    return [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def write(name: str, obj) -> None:
    path = SITE_DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def age_on(birth: str | None, today: date) -> int | None:
    if not isinstance(birth, str) or not birth:
        return None
    b = date.fromisoformat(birth[:10])
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def upcoming_fixtures(n=5) -> list[dict]:
    try:
        team = fotmob.team(refresh=False)  # cached by the update run
    except Exception:
        return []
    out = []
    for f in ingest.competitive_fixtures(team):
        if f["status"].get("finished") or f["status"].get("started"):
            continue
        ko = ingest.to_utc(f["status"]["utcTime"])
        home = f["home"]["id"] == FOTMOB_TEAM_ID
        out.append(dict(kickoff_local=ko.astimezone(ZoneInfo(LOCAL_TZ)).isoformat(),
                        competition=f["tournament"]["name"], venue="H" if home else "A",
                        opponent=(f["away"] if home else f["home"])["name"]))
    return sorted(out, key=lambda x: x["kickoff_local"])[:n]


def build_all(con) -> None:
    d = load(con)
    matches, pms, players, shots = d["matches"], d["pms"], d["players"], d["shots"]
    today = datetime.now(ZoneInfo(LOCAL_TZ)).date()

    m = matches.copy()
    m["kickoff_local"] = m["kickoff_local"].dt.strftime("%Y-%m-%dT%H:%M")
    m = m.drop(columns=[c for c in m.columns if c.endswith("_source") and c != "player_stats_source"])
    write("matches.json", records(m))

    p = players.copy()
    p["age"] = p["birth_date"].map(lambda b: age_on(b, today))
    played = pms.groupby("player_id").size()
    p["apps"] = p["player_id"].map(played).fillna(0).astype(int)
    write("players.json", records(p))

    pm = pms[["match_id", "player_id", "stats_source"] + PLAYER_STAT_COLS]
    write("player_matches.json", records(pm))

    for mid in matches.match_id:
        s = shots[shots.match_id == mid]
        write(f"matches/{mid}.json", dict(
            match_id=int(mid),
            shots=records(s.drop(columns=["shot_id", "match_id", "source_shot_id"]).sort_values("minute")),
        ))

    write("meta.json", dict(
        season=SEASON_LABEL,
        generated_at=datetime.now(ZoneInfo(LOCAL_TZ)).strftime("%Y-%m-%d %H:%M"),
        timezone=LOCAL_TZ,
        matches=len(matches), players_used=int(pms.player_id.nunique()),
        upcoming=upcoming_fixtures(),
        sources=[
            {"name": "Opta via premierleague.com", "used_for": "Premier League player and team stats"},
            {"name": "FotMob", "used_for": "fixtures, cup-match stats, ratings, physical data, cup shot maps"},
            {"name": "Understat", "used_for": "shot-level xG for Premier League matches"},
        ],
    ))
