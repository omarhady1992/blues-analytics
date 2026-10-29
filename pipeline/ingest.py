"""Turn raw source JSON into rows in the SQLite database.

Flow for one match:
  FotMob fixture (master list, all competitions)
    -> FotMob match details  (lineups, ratings, physical, cup player stats, shots)
    -> Premier League API    (Opta player + team stats, PL matches only)
    -> Understat             (own-model xG + shots, PL matches only)
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import db
from .config import EXCLUDED_COMPETITIONS, FOTMOB_TEAM_ID, LOCAL_TZ, PL_TEAM_ID, SEASON_START
from .sources import fotmob, premier_league as pl, understat

FOTMOB_POSITIONS = {0: "Goalkeeper", 1: "Defender", 2: "Midfielder", 3: "Forward"}


# ---------------------------------------------------------------- helpers
def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


def to_utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def first_int(v):
    """'329 (81%)' -> 329 ; 7 -> 7 ; None -> None"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m and "." in m.group(1) else (int(m.group(1)) if m else None)


# ---------------------------------------------------------------- fixtures
def competitive_fixtures(team_json) -> list[dict]:
    out = []
    for f in team_json["fixtures"]["allFixtures"]["fixtures"]:
        st = f["status"]
        if f["tournament"]["name"] in EXCLUDED_COMPETITIONS or st.get("cancelled"):
            continue
        if st["utcTime"][:10] < SEASON_START:
            continue
        out.append(f)
    return out


# ---------------------------------------------------------------- players
def sync_pl_squad(con, squad_json) -> None:
    con.execute("UPDATE players SET in_pl_squad = 0")
    for p in squad_json["players"]:
        pid = db.entity_for(con, "player", "premier_league", p["id"])
        row = dict(name=p["name"]["display"], first_name=p["name"].get("first"), last_name=p["name"].get("last"),
                   position=p.get("position"), shirt_number=p.get("shirtNum"), birth_date=p["dates"].get("birth"),
                   nationality=p["country"].get("country"), height_cm=p.get("height"),
                   preferred_foot=p.get("preferredFoot"), joined_club=p["dates"].get("joinedClub"), in_pl_squad=1)
        if pid is None:
            cur = con.execute(f"INSERT INTO players ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                              list(row.values()))
            pid = cur.lastrowid
            db.link(con, "player", pid, "premier_league", p["id"])
        else:
            con.execute(f"UPDATE players SET {', '.join(f'{k}=?' for k in row)} WHERE player_id=?",
                        [*row.values(), pid])


def player_from_fotmob(con, fm_player: dict, lineup_entry: dict | None) -> int:
    """Find (or create) our player for a FotMob player. Opta id links to the PL API."""
    fm_id = str(fm_player["id"])
    pid = db.entity_for(con, "player", "fotmob", fm_id)
    if pid:
        return pid
    opta = fm_player.get("optaId")
    if opta:
        pid = db.entity_for(con, "player", "premier_league", opta)
    if pid is None:  # e.g. an academy player only used in a cup game
        le = lineup_entry or {}
        cur = con.execute(
            "INSERT INTO players (name, first_name, last_name, position, shirt_number, nationality) VALUES (?,?,?,?,?,?)",
            (fm_player["name"], le.get("firstName"), le.get("lastName"),
             FOTMOB_POSITIONS.get(fm_player.get("usualPosition")),
             first_int(fm_player.get("shirtNumber")), le.get("countryName")))
        pid = cur.lastrowid
        if opta:
            db.link(con, "player", pid, "premier_league", opta)
    db.link(con, "player", pid, "fotmob", fm_id)
    return pid


# ---------------------------------------------------------------- stat mappings
# unified column -> FotMob stat key ("key.value" / "key.total" for fraction stats)
FOTMOB_MAP = {
    "minutes": "minutes_played", "goals": "goals", "assists": "assists",
    "xg": "expected_goals", "xa": "expected_assists", "xgot": "expected_goals_on_target_variant",
    "shots": "total_shots", "shots_on_target": "ShotsOnTarget", "chances_created": "chances_created",
    "big_chances_created": "big_chance_created_team_title", "touches": "touches",
    "touches_opp_box": "touches_opp_box", "passes": "accurate_passes.total",
    "passes_accurate": "accurate_passes.value", "final_third_entries": "passes_into_final_third",
    "line_breaking_passes": "line_breaking_passes", "long_balls": "long_balls_accurate.total",
    "long_balls_accurate": "long_balls_accurate.value", "crosses": "accurate_crosses.total",
    "crosses_accurate": "accurate_crosses.value", "dribbles": "dribbles_succeeded.total",
    "dribbles_won": "dribbles_succeeded.value", "tackles": "matchstats.headers.tackles",
    "interceptions": "interceptions", "recoveries": "recoveries", "clearances": "clearances",
    "blocks": "shot_blocks", "duels_won": "duel_won", "duels_lost": "duel_lost",
    "aerials_won": "aerials_won.value", "aerials_total": "aerials_won.total", "fouls": "fouls",
    "was_fouled": "was_fouled", "dispossessed": "dispossessed", "saves": "saves",
    "goals_conceded": "goals_conceded", "goals_prevented": "goals_prevented", "rating": "rating_title",
    "distance_m": "physical_metrics_distance_covered", "sprints": "physical_metrics_number_of_sprints",
    "top_speed_kmh": "physical_metrics_topspeed",
}
# FotMob-only fields we add on top of Opta numbers for PL matches
FOTMOB_EXTRAS = ["line_breaking_passes", "goals_conceded", "goals_prevented", "rating",
                 "distance_m", "sprints", "top_speed_kmh"]

# unified column -> Opta key(s) in the PL API (Opta omits zero values, so missing = 0)
OPTA_MAP = {
    "minutes": "minsPlayed", "goals": "goals", "assists": "goalAssist", "xg": "expectedGoals",
    "xa": "expectedAssists", "xgot": "expectedGoalsOnTarget", "shots": "totalScoringAtt",
    "shots_on_target": "ontargetScoringAtt", "chances_created": "totalAttAssist",
    "big_chances_created": "bigChanceCreated", "touches": "touches", "touches_opp_box": "touchesInOppBox",
    "passes": "totalPass", "passes_accurate": "accuratePass", "final_third_entries": "finalThirdEntries",
    "pen_area_entries": "penAreaEntries", "long_balls": "totalLongBalls",
    "long_balls_accurate": "accurateLongBalls", "crosses": "totalCross", "crosses_accurate": "accurateCross",
    "dribbles": "totalContest", "dribbles_won": "wonContest", "tackles": "totalTackle",
    "interceptions": "interception", "recoveries": "ballRecovery", "clearances": "totalClearance",
    "blocks": "outfielderBlock", "duels_won": "duelWon", "duels_lost": "duelLost",
    "aerials_won": "aerialWon", "aerials_lost": "aerialLost", "fouls": "fouls", "was_fouled": "wasFouled",
    "dispossessed": "dispossessed", "yellow_cards": "yellowCard", "red_cards": "redCard", "saves": "saves",
}


def flatten_fotmob_player(ps: dict) -> dict:
    flat = {}
    for block in ps.get("stats", []):
        for title, item in block.get("stats", {}).items():
            key = item.get("key") or title
            stat = item.get("stat", {})
            if key in flat or "value" not in stat:
                continue
            flat[key] = stat.get("value")
            if stat.get("total") is not None:
                flat[f"{key}.value"] = stat.get("value")
                flat[f"{key}.total"] = stat.get("total")
    return flat


# FotMob leaves out many zero values (e.g. no "xA" line for a player with no xA).
# A stat counts as "covered" in a match if FotMob gives it for any player in that
# match; then a missing value for one player means 0. These are never zero-filled:
NO_ZERO_FILL = {"rating", "distance_m", "sprints", "top_speed_kmh", "goals_prevented", "goals_conceded", "saves"}


def from_fotmob(flat: dict, covered: set[str]) -> dict:
    row = {}
    for col, key in FOTMOB_MAP.items():
        v = flat.get(key)
        if v is None and col not in NO_ZERO_FILL and key in covered:
            v = 0
        row[col] = v
    if row.get("aerials_total") is not None and row.get("aerials_won") is not None:
        row["aerials_lost"] = row["aerials_total"] - row["aerials_won"]
    row.pop("aerials_total", None)
    for k in ("goals", "assists"):
        row[k] = row[k] or 0
    return row


def from_opta(stats: dict) -> dict:
    return {col: stats.get(key, 0) for col, key in OPTA_MAP.items()}


# ---------------------------------------------------------------- match ingest
def find_pl_match(pl_matches, kickoff: datetime):
    for m in pl_matches:
        if m["period"] == "FullTime":
            ko = datetime.strptime(m["kickoff"], "%Y-%m-%d %H:%M:%S")
            if ko.date() == kickoff.date():  # PL gives UK local time; same calendar day is enough
                return m
    return None


def find_understat_match(us_team, kickoff: datetime):
    for m in us_team["dates"]:
        if m.get("isResult") and m["datetime"][:10] == kickoff.strftime("%Y-%m-%d"):
            return m
    return None


def ingest_match(con, fixture: dict, pl_matches, us_team, refresh=False) -> int:
    fm_id = fixture["id"]
    fm = fotmob.match(fm_id, refresh=refresh)
    kickoff = to_utc(fixture["status"]["utcTime"])
    home = fixture["home"]["id"] == FOTMOB_TEAM_ID
    us, them = (fixture["home"], fixture["away"]) if home else (fixture["away"], fixture["home"])
    # The fixture-list score includes penalty shoot-out kicks (e.g. 7-6 for a 1-1 draw won 6-5 on pens),
    # so take the score after play from scoreStr and the shoot-out score separately.
    sc = re.match(r"\s*(\d+)\s*-\s*(\d+)", (fixture.get("status") or {}).get("scoreStr") or "")
    hs, as_ = (int(sc[1]), int(sc[2])) if sc else (fixture["home"]["score"], fixture["away"]["score"])
    gf, ga = (hs, as_) if home else (as_, hs)
    competition = fixture["tournament"]["name"]
    info = fm["content"]["matchFacts"].get("infoBox", {})
    lineup = fm["content"]["lineup"]
    pens = ((fm.get("header") or {}).get("status") or {}).get("reason", {}).get("penalties")
    pf, pa = ((pens[0], pens[1]) if home else (pens[1], pens[0])) if pens else (None, None)
    our_lu, opp_lu = (lineup["homeTeam"], lineup["awayTeam"]) if home else (lineup["awayTeam"], lineup["homeTeam"])

    plm = find_pl_match(pl_matches, kickoff) if competition == "Premier League" else None
    usm = find_understat_match(us_team, kickoff) if competition == "Premier League" else None

    match_id = db.entity_for(con, "match", "fotmob", fm_id)
    row = dict(
        kickoff_utc=kickoff.isoformat(), kickoff_local=kickoff.astimezone(ZoneInfo(LOCAL_TZ)).isoformat(),
        competition=competition, round=(info.get("Tournament") or {}).get("roundName"),
        venue="H" if home else "A", opponent=them["name"], goals_for=gf, goals_against=ga,
        result="W" if gf > ga else ("D" if gf == ga else "L"),
        ground=(plm or {}).get("ground") or (info.get("Stadium") or {}).get("name"),
        attendance=(plm or {}).get("attendance") or info.get("Attendance"),
        formation=our_lu.get("formation"), opp_formation=opp_lu.get("formation"),
        player_stats_source="premier_league" if plm else "fotmob",
        xg_understat_for=float(usm["xG"]["h" if home else "a"]) if usm else None,
        xg_understat_against=float(usm["xG"]["a" if home else "h"]) if usm else None,
        pens_for=pf, pens_against=pa,
    )
    if match_id is None:
        cur = con.execute(f"INSERT INTO matches ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                          list(row.values()))
        match_id = cur.lastrowid
        db.link(con, "match", match_id, "fotmob", fm_id)
    else:
        con.execute(f"UPDATE matches SET {', '.join(f'{k}=?' for k in row)} WHERE match_id=?", [*row.values(), match_id])
    if plm:
        db.link(con, "match", match_id, "premier_league", plm["matchId"])
    if usm:
        db.link(con, "match", match_id, "understat", usm["id"])

    for t in ("player_match_stats", "player_match_stats_long", "shots", "team_match_stats"):
        con.execute(f"DELETE FROM {t} WHERE match_id=?", (match_id,))

    _ingest_players(con, match_id, fm, our_lu, plm, refresh)
    _ingest_team_stats(con, match_id, fm, home, plm, refresh)
    _ingest_shots(con, match_id, fm, home, usm, refresh)
    return match_id


def _ingest_players(con, match_id, fm, our_lu, plm, refresh):
    lineup_by_fm = {str(p["id"]): p for p in our_lu.get("starters", []) + our_lu.get("subs", [])}
    starters = {str(p["id"]) for p in our_lu.get("starters", [])}
    fm_rows = {}
    all_ps = (fm["content"].get("playerStats") or {})
    covered = set().union(*(flatten_fotmob_player(ps).keys() for ps in all_ps.values())) if all_ps else set()
    for fm_pid, ps in all_ps.items():
        if ps.get("teamId") != FOTMOB_TEAM_ID:
            continue
        pid = player_from_fotmob(con, ps, lineup_by_fm.get(str(fm_pid)))
        flat = flatten_fotmob_player(ps)
        fm_rows[pid] = (from_fotmob(flat, covered), str(fm_pid) in starters, flat)

    # cards for FotMob-sourced matches come from the match events
    cards = {}
    for e in fm["content"]["matchFacts"].get("events", {}).get("events", []):
        if e.get("type") == "Card" and e.get("player"):
            pid = db.entity_for(con, "player", "fotmob", e["player"]["id"])
            if pid:
                c = cards.setdefault(pid, {"yellow_cards": 0, "red_cards": 0})
                kind = (e.get("card") or "").lower()
                if "red" in kind:
                    c["red_cards"] += 1
                else:
                    c["yellow_cards"] += 1

    rows = {}
    if plm:  # Opta numbers from the Premier League API are the primary source
        lu = pl.lineups(plm["matchId"], refresh=refresh)
        side = lu["home_team"] if lu["home_team"]["teamId"] == PL_TEAM_ID else lu["away_team"]
        for p in side["players"]:
            st = pl.player_stats(plm["matchId"], p["id"], refresh=refresh).get("stats", {})
            if not st.get("minsPlayed"):
                continue
            pid = db.entity_for(con, "player", "premier_league", p["id"])
            if pid is None:
                cur = con.execute("INSERT INTO players (name, first_name, last_name, position, shirt_number) VALUES (?,?,?,?,?)",
                                  (f"{p['firstName']} {p['lastName']}".strip(), p["firstName"], p["lastName"],
                                   p.get("position"), first_int(p.get("shirtNum"))))
                pid = cur.lastrowid
                db.link(con, "player", pid, "premier_league", p["id"])
            row = from_opta(st)
            row.update(stats_source="premier_league", started=int(st.get("gameStarted", 0)))
            fmr = fm_rows.get(pid)
            for k in FOTMOB_EXTRAS:
                row[k] = fmr[0].get(k) if fmr else None
            rows[pid] = row
            for k, v in st.items():
                if isinstance(v, (int, float)):
                    con.execute("INSERT OR REPLACE INTO player_match_stats_long VALUES (?,?,?,?,?)",
                                (match_id, pid, "premier_league", k, v))
    else:
        for pid, (r, started, _) in fm_rows.items():
            if not r.get("minutes"):
                continue
            r = dict(r)
            r.update(stats_source="fotmob", started=int(started), **cards.get(pid, {"yellow_cards": 0, "red_cards": 0}))
            rows[pid] = r
    for pid, (_, _, flat) in fm_rows.items():
        for k, v in flat.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                con.execute("INSERT OR REPLACE INTO player_match_stats_long VALUES (?,?,?,?,?)",
                            (match_id, pid, "fotmob", k, v))
    for pid, r in rows.items():
        db.upsert(con, "player_match_stats", {"match_id": match_id, "player_id": pid, **r}, ["match_id", "player_id"])


def _ingest_team_stats(con, match_id, fm, home, plm, refresh):
    if plm:
        for t in pl.team_stats(plm["matchId"], refresh=refresh):
            s = t["stats"]
            side = "chelsea" if str(t["teamId"]) == PL_TEAM_ID else "opponent"
            g = lambda k: s.get(k, 0)
            db.upsert(con, "team_match_stats", dict(
                match_id=match_id, side=side, source="premier_league", possession=s.get("possessionPercentage"),
                xg=g("expectedGoals"), xgot=g("expectedGoalsOnTarget"), shots=g("totalScoringAtt"),
                shots_on_target=g("ontargetScoringAtt"),
                big_chances=g("bigChanceCreated"), touches_opp_box=g("touchesInOppBox"), passes=g("totalPass"),
                passes_accurate=g("accuratePass"), corners=g("wonCorners"), fouls=g("fkFoulLost"),
                yellow_cards=g("totalYelCard"), red_cards=g("totalRedCard"), tackles=g("totalTackle"),
                interceptions=g("interception"), clearances=g("totalClearance"), saves=g("saves"),
                offsides=g("totalOffside")), ["match_id", "side"])
        return
    vals = {}
    for block in fm["content"]["stats"]["Periods"]["All"]["stats"]:
        for s in block["stats"]:
            if s.get("stats") and s["stats"][0] is not None and s["key"] not in vals:
                vals[s["key"]] = s["stats"]
    for idx, side in ((0, "chelsea" if home else "opponent"), (1, "opponent" if home else "chelsea")):
        v = lambda k: first_int(vals[k][idx]) if k in vals else None
        acc = v("accurate_passes")
        db.upsert(con, "team_match_stats", dict(
            match_id=match_id, side=side, source="fotmob", possession=v("BallPossesion"),
            xg=float(vals["expected_goals"][idx]) if "expected_goals" in vals else None,
            xgot=float(vals["expected_goals_on_target"][idx]) if "expected_goals_on_target" in vals else None,
            shots=v("total_shots"), shots_on_target=v("ShotsOnTarget"), big_chances=v("big_chance"),
            touches_opp_box=v("touches_opp_box"), passes=v("passes"), passes_accurate=acc, corners=v("corners"),
            fouls=v("fouls"), yellow_cards=v("yellow_cards"), red_cards=v("red_cards"),
            tackles=v("matchstats.headers.tackles"), interceptions=v("interceptions"),
            clearances=v("clearances"), saves=v("keeper_saves"), offsides=v("Offsides")), ["match_id", "side"])


US_RESULTS = {"Goal": "Goal", "SavedShot": "Saved", "MissedShots": "Missed", "BlockedShot": "Blocked",
              "ShotOnPost": "Post", "OwnGoal": "OwnGoal"}
FM_RESULTS = {"Goal": "Goal", "AttemptSaved": "Saved", "Miss": "Missed", "Post": "Post"}


def _ingest_shots(con, match_id, fm, home, usm, refresh):
    # FotMob shots (all matches)
    for s in (fm["content"].get("shotmap") or {}).get("shots", []):
        if s.get("period") == "PenaltyShootout":  # shoot-out kicks are not shots in the match
            continue
        side = "chelsea" if s["teamId"] == FOTMOB_TEAM_ID else "opponent"
        pid = db.entity_for(con, "player", "fotmob", s["playerId"]) if side == "chelsea" else None
        result = "Blocked" if s.get("isBlocked") else FM_RESULTS.get(s["eventType"], s["eventType"])
        if s.get("isOwnGoal"):
            result = "OwnGoal"
        con.execute("INSERT OR REPLACE INTO shots (match_id, source, source_shot_id, side, player_id, player_name, minute, x, y, xg, result, situation, shot_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (match_id, "fotmob", str(s["id"]), side, pid, s.get("playerName"), s.get("min"),
                     s["x"] / 105.0, s["y"] / 68.0, s.get("expectedGoals"), result, s.get("situation"), s.get("shotType")))
    if not usm:
        return
    um = understat.match(usm["id"], refresh=refresh)
    ours = "h" if home else "a"
    name_to_pid = {norm_name(r["name"]): r["player_id"] for r in con.execute("SELECT player_id, name FROM players")}
    for h_a, shots in um["shots"].items():
        side = "chelsea" if h_a == ours else "opponent"
        for s in shots:
            pid = None
            if side == "chelsea":
                pid = db.entity_for(con, "player", "understat", s["player_id"]) or name_to_pid.get(norm_name(s["player"]))
                if pid is None:  # fall back to a unique surname match
                    last = norm_name(s["player"]).split()[-1]
                    cands = [v for k, v in name_to_pid.items() if k.split() and k.split()[-1] == last]
                    pid = cands[0] if len(cands) == 1 else None
                if pid:
                    db.link(con, "player", pid, "understat", s["player_id"])
            con.execute("INSERT OR REPLACE INTO shots (match_id, source, source_shot_id, side, player_id, player_name, minute, x, y, xg, result, situation, shot_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (match_id, "understat", s["id"], side, pid, s["player"], int(s["minute"]),
                         float(s["X"]), float(s["Y"]), float(s["xG"]), US_RESULTS.get(s["result"], s["result"]),
                         s.get("situation"), s.get("shotType")))
