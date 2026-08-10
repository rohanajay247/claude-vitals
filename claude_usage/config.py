"""Paths, tunables and thresholds. Everything machine-specific lives here."""

from pathlib import Path

# --- locations -----------------------------------------------------------
CLAUDE_DIR = Path.home() / ".claude"
CREDENTIALS_FILE = CLAUDE_DIR / ".credentials.json"

# Runtime state lives beside the code, not in the repo proper (see .gitignore).
PROJECT_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_DIR / "state"
CACHE_FILE = STATE_DIR / "usage_cache.json"
UI_STATE_FILE = STATE_DIR / "ui_state.json"
LOG_FILE = STATE_DIR / "claude-vitals.log"

# --- endpoint ------------------------------------------------------------
# UNOFFICIAL, community-discovered, undocumented. Anthropic does not support
# this and may change or remove it without notice. See README.
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# --- polling -------------------------------------------------------------
POLL_INTERVAL = 180          # 3 minutes between successful polls

# The endpoint rate-limits hard: a second request a couple of seconds after the
# first comes back 429. So a manual refresh is only worth making when the data
# we already hold is older than this -- otherwise we would spend a 429 to
# re-fetch numbers that are seconds old.
MIN_REFRESH_INTERVAL = 30
RATE_LIMIT_BACKOFF = 60      # wait at least this long after a 429

# Only call the figures "stale" once they are genuinely out of date. A single
# failed refresh does not make three-minute-old numbers wrong, and labelling
# them "stale - just now" is worse than saying nothing.
STALE_AFTER = 420            # 7 minutes: more than two missed polls
FOREGROUND_INTERVAL = 0.5    # how often we check which window is in front
REQUEST_TIMEOUT = 20

# Exponential backoff after a failed poll: 30s, 60s, 120s ... capped.
BACKOFF_START = 30
BACKOFF_MAX = 900
BACKOFF_FACTOR = 2

# --- usage credits -------------------------------------------------------
# The usage endpoint reports what has been SPENT but not the balance or the
# granted total: spend.limit/cap/balance and extra_usage.monthly_limit all come
# back null when the monthly spend limit is "Unlimited", and the total appears
# nowhere in the payload. Accounts that DO have a spend cap set will have it
# read automatically; everyone else can set a total from the tray menu.
#
# That user-supplied figure lives in state/settings.json, never here -- see
# claude_usage/settings.py.

# --- thresholds ----------------------------------------------------------
GREEN_BELOW = 50     # < 50%  green
YELLOW_BELOW = 80    # 50-80% yellow, above red

# Windows toasts at these thresholds, once per reset window. OFF by default:
# the tray ring and the overlay already show the number continuously, so a
# popup interrupting your work adds noise rather than information. Re-enable
# from the tray menu ("Usage alerts") if you want them; the choice persists.
NOTIFY_AT = (80, 95)
NOTIFY_ENABLED_DEFAULT = False

# Process names that count as "the Claude desktop app is in front".
CLAUDE_PROCESS_NAMES = {"claude.exe"}

# --- palette (Claude-themed, mirrors Claude Code's usage panel) ----------
COL_BG = "#232322"        # dark card
COL_BG_HOVER = "#2e2d2b"  # row/button hover wash
COL_BORDER = "#3a3936"
COL_LABEL = "#8f8b85"     # muted grey label
COL_VALUE = "#e8e4dd"     # near-white value
COL_TITLE = "#c9c5be"
COL_TRACK = "#333230"     # unfilled bar
COL_GREEN = "#4a9d6d"
COL_YELLOW = "#c99a3f"
COL_RED = "#c05a4d"
COL_STALE = "#8a6d3b"     # stale-data accent
COL_ACCENT = "#d97757"    # Claude orange
COL_ACCENT_DIM = "#7d4633"

# Overlay starts visible regardless of which app is in front. The whole point is
# to have it up while you work; close it from the overlay when you are done.
ALWAYS_VISIBLE_DEFAULT = True

# Animation. ANIM_FPS applies while something is actually moving (bars easing,
# post-refresh spin); the rest of the time we drop to IDLE_FPS, because a
# permanently repainting widget is a real battery cost for no benefit.
ANIM_FPS = 15
IDLE_FPS = 6
BAR_EASING = 0.18


def colour_for(pct):
    """Severity colour for a percentage. Shared by tray, overlay and toasts."""
    if pct is None:
        return COL_LABEL
    if pct < GREEN_BELOW:
        return COL_GREEN
    if pct <= YELLOW_BELOW:
        return COL_YELLOW
    return COL_RED


def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
