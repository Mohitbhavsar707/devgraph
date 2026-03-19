"""
checkpoint.py — Tracks which GitHub artifacts have already been processed
so that re-runs only fetch new issues/PRs (cursor-based incremental ingestion).
"""

import json
import os
from pathlib import Path
from typing import Optional


CHECKPOINT_FILE = ".devgraph_checkpoint.json"


def _load(repo: str) -> dict:
    if not Path(CHECKPOINT_FILE).exists():
        return {}
    with open(CHECKPOINT_FILE) as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_last_cursor(repo: str) -> Optional[str]:
    """Return the ISO timestamp of the last successful ingest for this repo."""
    return _load(repo).get(repo, {}).get("since")


def set_cursor(repo: str, since: str) -> None:
    """Persist the cursor after a successful ingest run."""
    data = _load(repo)
    data.setdefault(repo, {})["since"] = since
    _save(data)


def clear_cursor(repo: str) -> None:
    """Force a full re-ingest on the next run."""
    data = _load(repo)
    data.pop(repo, None)
    _save(data)
