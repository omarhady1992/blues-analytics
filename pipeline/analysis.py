"""Pandas helpers shared by the reports and the site export."""
from __future__ import annotations

import sqlite3

import pandas as pd

DEFENSIVE_PARTS = ["tackles", "interceptions", "recoveries", "clearances", "blocks"]


def load(con: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    """Load the core tables as DataFrames, already joined where useful."""
    matches = pd.read_sql("SELECT * FROM matches ORDER BY kickoff_utc", con)
    matches["kickoff_local"] = pd.to_datetime(matches["kickoff_local"].str[:19])
    matches["month"] = matches["kickoff_local"].dt.strftime("%Y-%m")
    team = pd.read_sql("SELECT * FROM team_match_stats", con)
    pms = pd.read_sql("SELECT * FROM player_match_stats", con)
    players = pd.read_sql("SELECT * FROM players", con)
    shots = pd.read_sql("SELECT * FROM shots", con)
    pms = pms.merge(players[["player_id", "name", "position"]], on="player_id").merge(
        matches[["match_id", "kickoff_local", "competition", "opponent", "month"]], on="match_id")
    pms["defensive_actions"] = pms[DEFENSIVE_PARTS].sum(axis=1, min_count=1)
    pms = pms.sort_values(["kickoff_local", "player_id"])
    # one wide row per match: chelsea_* and opponent_* team stats
    wide = team.pivot(index="match_id", columns="side")
    wide.columns = [f"{side}_{col}" for col, side in wide.columns]
    matches = matches.merge(wide.reset_index(), on="match_id", how="left")
    bu = pd.read_sql("SELECT * FROM team_match_buildup", con)
    bu_units = pd.read_sql("SELECT * FROM team_match_buildup_units", con)
    return dict(matches=matches, team=team, pms=pms, players=players, shots=shots, bu=bu, bu_units=bu_units)


def per90(df: pd.DataFrame, cols: list[str], min_minutes: int = 0) -> pd.DataFrame:
    """Sum per player and convert to per-90 values. NaNs are ignored (not zero)."""
    g = df.groupby(["player_id", "name", "position"])
    out = g[cols].sum(min_count=1)
    out["minutes"] = g["minutes"].sum()
    out["apps"] = g.size()
    out = out[out["minutes"] >= min_minutes]
    for c in cols:
        out[f"{c}_p90"] = out[c] * 90 / out["minutes"]
    return out.reset_index()


def fmt(v, nd=2):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    if isinstance(v, float) and not float(v).is_integer():
        return f"{v:.{nd}f}"
    return f"{int(v)}" if isinstance(v, (int, float)) else str(v)
