# db.py
# Local SQLite store: maps bale_user_id ↔ wp_user_id, tracks conversation state
import sqlite3
import threading
from config import DB_PATH

_local = threading.local()

def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _init(_local.conn)
    return _local.conn

def _init(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            bale_user_id  TEXT PRIMARY KEY,
            wp_user_id    INTEGER,
            mobile        TEXT,
            display_name  TEXT,
            linked_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            bale_user_id  TEXT PRIMARY KEY,
            state         TEXT DEFAULT 'idle',
            temp_data     TEXT DEFAULT '{}',
            updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

# ── User helpers ──────────────────────────────────────────────────────

def get_user(bale_user_id: str) -> sqlite3.Row | None:
    return get_conn().execute(
        "SELECT * FROM users WHERE bale_user_id = ?", (str(bale_user_id),)
    ).fetchone()

def save_user(bale_user_id: str, wp_user_id: int, mobile: str, display_name: str):
    get_conn().execute("""
        INSERT INTO users (bale_user_id, wp_user_id, mobile, display_name)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(bale_user_id) DO UPDATE SET
            wp_user_id   = excluded.wp_user_id,
            mobile       = excluded.mobile,
            display_name = excluded.display_name,
            linked_at    = CURRENT_TIMESTAMP
    """, (str(bale_user_id), wp_user_id, mobile, display_name))
    get_conn().commit()

def is_linked(bale_user_id: str) -> bool:
    row = get_user(bale_user_id)
    return row is not None and row["wp_user_id"] is not None

# ── Session / state helpers ───────────────────────────────────────────

import json

def get_state(bale_user_id: str) -> tuple[str, dict]:
    row = get_conn().execute(
        "SELECT state, temp_data FROM sessions WHERE bale_user_id = ?", (str(bale_user_id),)
    ).fetchone()
    if not row:
        return "idle", {}
    return row["state"], json.loads(row["temp_data"] or "{}")

def set_state(bale_user_id: str, state: str, temp_data: dict = {}):
    get_conn().execute("""
        INSERT INTO sessions (bale_user_id, state, temp_data, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(bale_user_id) DO UPDATE SET
            state      = excluded.state,
            temp_data  = excluded.temp_data,
            updated_at = CURRENT_TIMESTAMP
    """, (str(bale_user_id), state, json.dumps(temp_data, ensure_ascii=False)))
    get_conn().commit()

def clear_state(bale_user_id: str):
    set_state(bale_user_id, "idle", {})
