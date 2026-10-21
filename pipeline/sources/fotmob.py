"""FotMob internal JSON API (needs a browser-like TLS fingerprint -> curl_cffi).

Used for: the full fixture list (all competitions), cup-match player stats,
ratings and physical data for every match, and shot maps for cup matches.
"""
from ..config import FOTMOB_TEAM_ID
from ..http import CachedClient

BASE = "https://www.fotmob.com/api/data"
client = CachedClient("fotmob", impersonate=True)


def team(refresh=True):
    return client.get_json(f"{BASE}/teams", f"team_{FOTMOB_TEAM_ID}",
                           params={"id": FOTMOB_TEAM_ID, "ccode3": "EGY"}, refresh=refresh)


def match(match_id, refresh=False):
    return client.get_json(f"{BASE}/matchDetails", f"match_{match_id}",
                           params={"matchId": match_id}, refresh=refresh)
