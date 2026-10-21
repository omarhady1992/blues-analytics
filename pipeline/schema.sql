-- Blues Analytics SQLite schema
-- Conventions: one row per real-world thing; ids are our own integers;
-- every source's own id lives in source_ids so sources can be joined.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS players (
    player_id      INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    first_name     TEXT,
    last_name      TEXT,
    position       TEXT,              -- Goalkeeper / Defender / Midfielder / Forward
    shirt_number   INTEGER,
    birth_date     TEXT,              -- ISO date
    nationality    TEXT,
    height_cm      INTEGER,
    preferred_foot TEXT,
    joined_club    TEXT,
    in_pl_squad    INTEGER NOT NULL DEFAULT 0  -- 1 = in the registered PL squad list
);

-- Maps our ids to each source's ids. source: 'premier_league' (= Opta id), 'fotmob', 'understat'
CREATE TABLE IF NOT EXISTS source_ids (
    entity_type TEXT NOT NULL CHECK (entity_type IN ('player', 'match')),
    entity_id   INTEGER NOT NULL,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    PRIMARY KEY (entity_type, source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_source_ids_entity ON source_ids(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS matches (
    match_id        INTEGER PRIMARY KEY,
    kickoff_utc     TEXT NOT NULL,     -- ISO 8601, UTC
    kickoff_local   TEXT NOT NULL,     -- ISO 8601 in Africa/Cairo
    competition     TEXT NOT NULL,
    round           TEXT,
    venue           TEXT NOT NULL CHECK (venue IN ('H', 'A')),
    opponent        TEXT NOT NULL,
    goals_for       INTEGER NOT NULL,
    goals_against   INTEGER NOT NULL,
    result          TEXT NOT NULL CHECK (result IN ('W', 'D', 'L')),
    ground          TEXT,
    attendance      INTEGER,
    formation       TEXT,
    opp_formation   TEXT,
    player_stats_source TEXT NOT NULL, -- 'premier_league' (Opta) or 'fotmob'
    xg_understat_for     REAL,         -- Understat's own xG model (PL only)
    xg_understat_against REAL
);

CREATE TABLE IF NOT EXISTS team_match_stats (
    match_id        INTEGER NOT NULL REFERENCES matches(match_id),
    side            TEXT NOT NULL CHECK (side IN ('chelsea', 'opponent')),
    source          TEXT NOT NULL,
    possession      REAL,
    xg              REAL,
    xgot            REAL,
    shots           INTEGER,
    shots_on_target INTEGER,
    big_chances     INTEGER,
    touches_opp_box INTEGER,
    passes          INTEGER,
    passes_accurate INTEGER,
    corners         INTEGER,
    fouls           INTEGER,
    yellow_cards    INTEGER,
    red_cards       INTEGER,
    tackles         INTEGER,
    interceptions   INTEGER,
    clearances      INTEGER,
    saves           INTEGER,
    offsides        INTEGER,
    PRIMARY KEY (match_id, side)
);

-- One row per Chelsea player per match he actually played (minutes > 0).
-- NULL means "not available from the source", never "zero".
CREATE TABLE IF NOT EXISTS player_match_stats (
    match_id             INTEGER NOT NULL REFERENCES matches(match_id),
    player_id            INTEGER NOT NULL REFERENCES players(player_id),
    stats_source         TEXT NOT NULL,   -- where the core numbers came from
    started              INTEGER NOT NULL,
    minutes              INTEGER NOT NULL,
    goals                INTEGER,
    assists              INTEGER,
    xg                   REAL,
    xa                   REAL,
    xgot                 REAL,
    shots                INTEGER,
    shots_on_target      INTEGER,
    chances_created      INTEGER,
    big_chances_created  INTEGER,
    touches              INTEGER,
    touches_opp_box      INTEGER,
    passes               INTEGER,
    passes_accurate      INTEGER,
    final_third_entries  INTEGER,  -- Opta finalThirdEntries / FotMob "passes into final third"
    pen_area_entries     INTEGER,  -- Opta only
    line_breaking_passes INTEGER,  -- FotMob only
    long_balls           INTEGER,
    long_balls_accurate  INTEGER,
    crosses              INTEGER,
    crosses_accurate     INTEGER,
    dribbles             INTEGER,
    dribbles_won         INTEGER,
    tackles              INTEGER,
    interceptions        INTEGER,
    recoveries           INTEGER,
    clearances           INTEGER,
    blocks               INTEGER,
    duels_won            INTEGER,
    duels_lost           INTEGER,
    aerials_won          INTEGER,
    aerials_lost         INTEGER,
    fouls                INTEGER,
    was_fouled           INTEGER,
    dispossessed         INTEGER,
    yellow_cards         INTEGER,
    red_cards            INTEGER,
    saves                INTEGER,
    goals_conceded       INTEGER,
    goals_prevented      REAL,     -- FotMob (keepers)
    rating               REAL,     -- FotMob match rating
    distance_m           REAL,     -- FotMob physical data
    sprints              INTEGER,
    top_speed_kmh        REAL,
    PRIMARY KEY (match_id, player_id)
);

-- Every numeric stat the source gave, in long format (great for SQL/Pandas practice).
-- Stays local: data/blues.db is git-ignored.
CREATE TABLE IF NOT EXISTS player_match_stats_long (
    match_id  INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    source    TEXT NOT NULL,
    stat_key  TEXT NOT NULL,
    value     REAL,
    PRIMARY KEY (match_id, player_id, source, stat_key)
);

-- Shots. x, y normalised to 0..1 with the shooting team attacking towards x = 1.
CREATE TABLE IF NOT EXISTS shots (
    shot_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id       INTEGER NOT NULL REFERENCES matches(match_id),
    source         TEXT NOT NULL,       -- 'understat' or 'fotmob'
    source_shot_id TEXT NOT NULL,
    side           TEXT NOT NULL CHECK (side IN ('chelsea', 'opponent')),
    player_id      INTEGER REFERENCES players(player_id),  -- Chelsea shooters only
    player_name    TEXT,
    minute         INTEGER,
    x              REAL,
    y              REAL,
    xg             REAL,
    result         TEXT,                -- Goal / Saved / Missed / Blocked / Post / OwnGoal
    situation      TEXT,
    shot_type      TEXT,
    UNIQUE (source, source_shot_id)
);

-- Handy view: season totals and per-90s per player (all competitions)
CREATE VIEW IF NOT EXISTS v_player_season AS
SELECT p.player_id, p.name, p.position,
       COUNT(*)                         AS apps,
       SUM(s.started)                   AS starts,
       SUM(s.minutes)                   AS minutes,
       SUM(s.goals)                     AS goals,
       SUM(s.assists)                   AS assists,
       ROUND(SUM(s.xg), 2)              AS xg,
       ROUND(SUM(s.xa), 2)              AS xa,
       ROUND(SUM(s.xg) * 90.0 / SUM(s.minutes), 2) AS xg_p90,
       ROUND(SUM(s.xa) * 90.0 / SUM(s.minutes), 2) AS xa_p90,
       ROUND(AVG(s.rating), 2)          AS avg_rating
FROM player_match_stats s JOIN players p USING (player_id)
GROUP BY p.player_id;
