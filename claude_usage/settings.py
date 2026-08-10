"""User settings — the things that differ from person to person.

Kept in `state/settings.json`, which is gitignored, so nobody's account details
live in the source tree. Anything here can also be set from the tray menu, so a
user never has to open a code file to configure the app.

Separate from `ui_state.json` on purpose: that holds where the window sits and
which toggles are on (machine state), while this holds what the user told us
about their account (configuration).
"""

import json
import os

from . import config

DEFAULTS = {
    # Total usage credits granted, in MINOR units (cents/pence). The usage
    # endpoint reports what has been SPENT but not the balance or the total, so
    # this cannot be discovered automatically on most accounts -- see
    # docs/README. None means "just show the amount spent, with no bar".
    "credits_total_minor": None,
    # ISO currency code. Only used when we have to render a total the API did
    # not give us; otherwise the API's own currency wins.
    "credits_currency": None,
    # Extra process names that count as "the Claude app is in front", for the
    # follow-Claude visibility mode. Merged with the built-in list, so a user on
    # a differently-named build can fix detection without editing code.
    "extra_claude_processes": [],
}


def _path():
    return config.STATE_DIR / "settings.json"


def load():
    """Read settings, filling in defaults for anything absent or invalid."""
    values = dict(DEFAULTS)
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return values
    if isinstance(raw, dict):
        for key in DEFAULTS:
            if key in raw:
                values[key] = raw[key]
    return values


def save(values):
    """Write settings atomically, preserving any keys we do not know about."""
    config.ensure_state_dir()
    current = {}
    try:
        existing = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            current = existing
    except (OSError, json.JSONDecodeError):
        pass
    current.update(values)

    tmp = _path().with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        os.replace(tmp, _path())
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return current


def get(key):
    return load().get(key, DEFAULTS.get(key))


def set_value(key, value):
    return save({key: value})


def credits_total_minor():
    """Configured credit total in minor units, or None if not set."""
    value = get("credits_total_minor")
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return value if value and value > 0 else None


def credits_currency():
    value = get("credits_currency")
    return value if isinstance(value, str) and value else None


def claude_process_names():
    """Built-in process names plus anything the user added."""
    names = set(config.CLAUDE_PROCESS_NAMES)
    extra = get("extra_claude_processes")
    if isinstance(extra, list):
        names.update(str(n).lower() for n in extra if n)
    return names
