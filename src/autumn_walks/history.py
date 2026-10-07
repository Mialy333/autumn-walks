"""Walk history: which trees were used recently, so the next walk is different.

Stored in data/history.sqlite (not committed). WALK_HISTORY_DB overrides the path, e.g. for tests.
"""

import json
import os
import sqlite3
from datetime import date
from pathlib import Path

from autumn_walks.load_trees import ROOT

DEFAULT_PATH = ROOT / "data" / "history.sqlite"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(Path(os.environ.get("WALK_HISTORY_DB", DEFAULT_PATH)))
    con.execute(
        """CREATE TABLE IF NOT EXISTS walks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            start_lat REAL NOT NULL,
            start_lon REAL NOT NULL,
            tree_ids TEXT NOT NULL,
            loop_m INTEGER NOT NULL
        )"""
    )
    return con


def record_walk(walk: dict) -> None:
    con = _connect()
    con.execute(
        "INSERT INTO walks (date, start_lat, start_lon, tree_ids, loop_m) VALUES (?, ?, ?, ?, ?)",
        (
            date.today().isoformat(),
            walk["start"][0],
            walk["start"][1],
            json.dumps([s["id"] for s in walk["stops"]]),
            walk["total_loop_m"],
        ),
    )
    con.commit()
    con.close()


def recent_tree_ids(walks: int) -> set[int]:
    """Ids of the trees used in the last `walks` walks."""
    con = _connect()
    rows = con.execute("SELECT tree_ids FROM walks ORDER BY id DESC LIMIT ?", (walks,)).fetchall()
    con.close()
    return {i for (ids,) in rows for i in json.loads(ids)}
