"""Central configuration. Change season/team ids here, nowhere else."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"            # cached source JSON (git-ignored)
DB_PATH = DATA_DIR / "blues.db"       # SQLite database (git-ignored, rebuildable)
SCHEMA_PATH = ROOT / "pipeline" / "schema.sql"
SITE_DATA_DIR = ROOT / "site" / "data"  # processed JSON the website reads (committed)

SEASON_LABEL = "2026-27"
SEASON_START = "2026-07-01"           # ignore anything older than this
LOCAL_TZ = "Africa/Cairo"             # Omar's time zone; kickoffs are shown in it

# Source identifiers for Chelsea
PL_COMPETITION_ID = 8                 # Premier League in the PL "SDP" API
PL_SEASON = 2026
PL_TEAM_ID = "8"
FOTMOB_TEAM_ID = 8455
UNDERSTAT_TEAM = "Chelsea"
UNDERSTAT_SEASON = "2026"

# FotMob tournament names we do not treat as competitive matches
EXCLUDED_COMPETITIONS = {"Club Friendlies"}

# Be gentle: minimum seconds between two requests to the same host
MIN_REQUEST_INTERVAL = 1.2
