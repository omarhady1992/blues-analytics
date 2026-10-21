"""Premier League website API (Opta data). Undocumented: endpoints found by testing.

Base: https://sdp-prem-prod.premier-league-prod.pulselive.com/api
Covers Premier League matches only.
"""
from ..config import PL_COMPETITION_ID, PL_SEASON, PL_TEAM_ID
from ..http import CachedClient

BASE = "https://sdp-prem-prod.premier-league-prod.pulselive.com/api"
client = CachedClient("premier_league", headers={"Origin": "https://www.premierleague.com"})


def season_matches(refresh=True):
    return client.get_json(f"{BASE}/v2/matches", f"matches_{PL_SEASON}_team{PL_TEAM_ID}",
                           params={"competition": PL_COMPETITION_ID, "season": PL_SEASON,
                                   "team": PL_TEAM_ID, "_limit": 60}, refresh=refresh)["data"]


def squad(refresh=True):
    return client.get_json(f"{BASE}/v2/competitions/{PL_COMPETITION_ID}/seasons/{PL_SEASON}/teams/{PL_TEAM_ID}/squad",
                           f"squad_{PL_SEASON}_team{PL_TEAM_ID}", refresh=refresh)


def lineups(match_id, refresh=False):
    return client.get_json(f"{BASE}/v3/matches/{match_id}/lineups", f"match_{match_id}_lineups", refresh=refresh)


def events(match_id, refresh=False):
    return client.get_json(f"{BASE}/v1/matches/{match_id}/events", f"match_{match_id}_events", refresh=refresh)


def team_stats(match_id, refresh=False):
    return client.get_json(f"{BASE}/v3/matches/{match_id}/stats", f"match_{match_id}_teamstats", refresh=refresh)


def player_stats(match_id, player_id, refresh=False):
    return client.get_json(f"{BASE}/v1/matches/{match_id}/players/{player_id}/stats",
                           f"match_{match_id}_player_{player_id}", refresh=refresh)
