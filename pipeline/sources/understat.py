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


def league(refresh=True, league_code="EPL"):
    """League table data: per-team match history incl. PPDA (event-based, computed by Understat)."""
    return client.get_json(f"{BASE}/getLeagueData/{league_code}/{UNDERSTAT_SEASON}",
                           f"league_{league_code}_{UNDERSTAT_SEASON}", refresh=refresh)
