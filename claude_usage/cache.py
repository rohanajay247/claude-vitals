"""Disk cache for the last good usage response.

Two jobs:
  1. A restart shows real numbers immediately instead of a blank icon.
  2. A failed poll falls back to these values -- flagged stale -- instead of
     crashing or blanking the display.

Only the parsed usage payload is stored. No token material ever reaches this
file (see credentials.py).
"""

import json
import os
import time

from . import config


def save(payload):
    """Write atomically: a half-written cache is worse than a missing one."""
    config.ensure_state_dir()
    record = {"fetched_at": time.time(), "payload": payload}
    tmp = config.CACHE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, config.CACHE_FILE)  # atomic on Windows and POSIX
    except OSError:
        # A cache we cannot write is a degraded experience, never a crash.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def load():
    """Return (payload, fetched_at) or (None, None) if there is nothing usable."""
    try:
        record = json.loads(config.CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(record, dict):
        return None, None
    payload = record.get("payload")
    if payload is None:
        return None, None
    try:
        fetched_at = float(record.get("fetched_at"))
    except (TypeError, ValueError):
        fetched_at = None
    return payload, fetched_at


def clear():
    try:
        config.CACHE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# --- small key/value store for UI state (overlay position, toast dedupe) ---

def load_ui_state():
    try:
        data = json.loads(config.UI_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_ui_state(state):
    config.ensure_state_dir()
    tmp = config.UI_STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, config.UI_STATE_FILE)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
