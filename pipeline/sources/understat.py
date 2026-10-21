"""Understat AJAX endpoints (Premier League only). Own xG model, shot-level data."""
from ..config import UNDERSTAT_SEASON, UNDERSTAT_TEAM
from ..http import CachedClient

BASE = "https://understat.com"
client = CachedClient("understat", headers={"X-Requested-With": "XMLHttpRequest"})


def team(refresh=True):
    return client.get_json(f"{BASE}/getTeamData/{UNDERSTAT_TEAM}/{UNDERSTAT_SEASON}",
                           f"team_{UNDERSTAT_TEAM}_{UNDERSTAT_SEASON}", refresh=refresh)


def match(match_id, refresh=False):
    return client.get_json(f"{BASE}/getMatchData/{match_id}", f"match_{match_id}", refresh=refresh)
