"""Behaviour snapshots: compare a JSON-able value with a file recorded earlier.

Snapshots record what the code did when they were taken (they are not a specification).
Re-record deliberately, after checking the diff, with:  UPDATE_SNAPSHOTS=1 python -m pytest ...
"""

import json
import os
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def check_snapshot(name: str, actual) -> None:
    path = SNAPSHOT_DIR / f"{name}.json"
    if os.getenv("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert path.exists(), f"No snapshot {path.name}; record it with UPDATE_SNAPSHOTS=1"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(actual)) == expected
