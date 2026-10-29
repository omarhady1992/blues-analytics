"""SQLite helpers."""
import sqlite3

from .config import DB_PATH, SCHEMA_PATH


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA_PATH.read_text())
    # lightweight migrations for databases created before a column existed
    cols = {r[1] for r in con.execute("PRAGMA table_info(matches)")}
    for c in ("pens_for", "pens_against"):
        if c not in cols:
            con.execute(f"ALTER TABLE matches ADD COLUMN {c} INTEGER")
    return con


def upsert(con, table: str, row: dict, keys: list[str]) -> None:
    """INSERT ... ON CONFLICT(keys) DO UPDATE for a dict row."""
    cols = list(row)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in keys) or f"{keys[0]}={keys[0]}"
    con.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {updates}",
        [row[c] for c in cols],
    )


def entity_for(con, entity_type: str, source: str, source_id) -> int | None:
    r = con.execute("SELECT entity_id FROM source_ids WHERE entity_type=? AND source=? AND source_id=?",
                    (entity_type, source, str(source_id))).fetchone()
    return r[0] if r else None


def link(con, entity_type: str, entity_id: int, source: str, source_id) -> None:
    con.execute("INSERT OR REPLACE INTO source_ids VALUES (?,?,?,?)",
                (entity_type, entity_id, source, str(source_id)))
