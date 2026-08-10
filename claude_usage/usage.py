"""Fetching and normalising the usage endpoint response.

The endpoint is UNOFFICIAL (see config.USAGE_URL). Everything here is written to
survive it changing shape: every field is optional, every access is guarded, and
an unrecognised payload degrades to "no rows" rather than an exception.

Observed shape (Pro account, 2026-08-10):

    five_hour   {utilization: float, resets_at: ISO8601, limit_dollars: null, ...}
    seven_day   {utilization: float, resets_at: ISO8601, ...}
    limits      [{kind, group, percent, severity, resets_at, is_active}, ...]
                kind is 'session' | 'weekly_all'
    spend       {used: {amount_minor, currency, exponent}, limit, percent, enabled, ...}
    extra_usage {used_credits, currency, decimal_places, is_enabled, ...}
    seven_day_opus / seven_day_sonnet   per-model caps, null on Pro

`limits` and the five_hour/seven_day objects carry the same numbers. We prefer
`limits` because it is the display-oriented view (it carries severity and
ordering), and fall back to the flat objects when it is absent.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import cache, config, credentials, settings

# kind -> (display label, sort order). Anything unknown still renders, using a
# prettified version of its kind, so a new bucket appears rather than vanishing.
KNOWN_KINDS = {
    "session": ("5-hour limit", 0),
    "weekly_all": ("Weekly · all models", 1),
    "weekly_opus": ("Weekly · Opus", 2),
    "weekly_sonnet": ("Weekly · Sonnet", 3),
}

# Flat keys to fall back on when `limits` is missing, in display order.
FALLBACK_KEYS = [
    ("five_hour", "5-hour limit"),
    ("seven_day", "Weekly · all models"),
    ("seven_day_opus", "Weekly · Opus"),
    ("seven_day_sonnet", "Weekly · Sonnet"),
]


class UsageError(Exception):
    """Fetch failed. Message is always redacted."""


class AuthError(UsageError):
    """401/403 -- caller should re-read credentials and try refreshing."""


class RateLimited(UsageError):
    """429 -- the endpoint is fine, it just wants us to wait.

    Deliberately distinct from a real failure: the numbers we already hold are
    still valid, so the caller should keep showing them rather than falling
    back and flagging everything stale.
    """

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class Limit:
    key: str
    label: str
    percent: float
    resets_at: datetime | None = None
    severity: str = "normal"

    def resets_in(self):
        """Seconds until reset, or None."""
        if self.resets_at is None:
            return None
        return (self.resets_at - datetime.now(timezone.utc)).total_seconds()

    def reset_clock(self):
        """Local wall-clock reset time, e.g. '7:29 PM'. Empty if unknown."""
        if self.resets_at is None:
            return ""
        local = self.resets_at.astimezone()
        # %#I is the Windows equivalent of %-I (no zero padding).
        try:
            return local.strftime("%#I:%M %p").lower().replace("am", "am").replace("pm", "pm")
        except ValueError:
            return local.strftime("%H:%M")

    def reset_hint(self):
        """Compact reset text for the overlay.

        A wall-clock time is only useful for a window resetting today; for the
        weekly window a countdown reads far better than 'Fri 5:59 pm'.
        """
        remaining = self.resets_in()
        if remaining is None:
            return ""
        if remaining <= 0:
            return "resetting"
        if remaining < 24 * 3600:
            return f"resets {self.reset_clock()}"
        return f"resets in {self.countdown()}"

    def countdown(self):
        """'2h 41m' / '3d 4h' / 'now'. Used in the tray tooltip."""
        remaining = self.resets_in()
        if remaining is None:
            return ""
        if remaining <= 0:
            return "now"
        minutes = int(remaining) // 60
        if minutes >= 24 * 60:
            hours = minutes // 60
            return f"{hours // 24}d {hours % 24}h"
        if minutes >= 60:
            return f"{minutes // 60}h {minutes % 60}m"
        return f"{minutes}m"


@dataclass
class Snapshot:
    limits: list = field(default_factory=list)
    credits_label: str | None = None    # e.g. '$12.40 / $50.00'
    credits_percent: float | None = None
    fetched_at: float = 0.0
    stale: bool = False
    error: str | None = None

    @property
    def session(self):
        return self.find("session")

    @property
    def weekly(self):
        return self.find("weekly_all")

    def find(self, key):
        for limit in self.limits:
            if limit.key == key:
                return limit
        return None

    @property
    def headline(self):
        """The percentage the tray icon shows -- session usage."""
        limit = self.session or (self.limits[0] if self.limits else None)
        return limit.percent if limit else None

    @property
    def ok(self):
        return bool(self.limits) and not self.error


# --- parsing -------------------------------------------------------------

def _parse_time(value):
    """ISO 8601 -> aware datetime, or None. Tolerates 'Z' and missing offsets."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _num(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _label_for(kind):
    if kind in KNOWN_KINDS:
        return KNOWN_KINDS[kind][0]
    return str(kind).replace("_", " ").capitalize()


def _order_for(kind):
    return KNOWN_KINDS.get(kind, (None, 99))[1]


SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}


def _format_money(amount_minor, currency, exponent):
    """Minor units + exponent -> a display string. e.g. 1240 / 10^2 = $12.40."""
    if amount_minor is None:
        return None
    try:
        divisor = 10 ** int(exponent) if exponent is not None else 1
    except (TypeError, ValueError):
        divisor = 1
    value = amount_minor / divisor if divisor else amount_minor
    symbol = SYMBOLS.get(currency, "")
    if symbol:
        return f"{symbol}{value:,.2f}"
    return f"{value:,.2f} {currency or ''}".strip()


def _money(spend, extra):
    """Render the credits figure as (label, percent).

    Shows 'used / total' when the account actually has a spend limit. On plans
    without one every candidate field (spend.limit, spend.cap, spend.balance,
    extra_usage.monthly_limit) comes back null, so there is genuinely no total to
    divide by -- we show the used figure alone rather than inventing a ceiling.
    """
    spend = spend or {}
    extra = extra or {}

    amount = currency = exponent = None
    used = spend.get("used")
    if isinstance(used, dict):
        amount = _num(used.get("amount_minor"))
        currency = used.get("currency")
        exponent = used.get("exponent")

    if amount is None:
        amount = _num(extra.get("used_credits"))
        currency = extra.get("currency")
        exponent = extra.get("decimal_places")

    if amount is None:
        return None, None

    used_label = _format_money(amount, currency, exponent)

    # Look for a ceiling anywhere the API might put one.
    limit_minor = None
    for candidate in (spend.get("limit"), spend.get("cap"), spend.get("balance")):
        if isinstance(candidate, dict):
            limit_minor = _num(candidate.get("amount_minor"))
        else:
            limit_minor = _num(candidate)
        if limit_minor:
            break
    if not limit_minor:
        limit_minor = _num(extra.get("monthly_limit"))

    # Fall back to the total the user told us about, since most accounts do not
    # report granted credits at all (see claude_usage/settings.py).
    from_config = False
    if not limit_minor:
        configured = settings.credits_total_minor()
        if configured:
            limit_minor = configured
            currency = currency or settings.credits_currency()
            from_config = True

    if limit_minor:
        total_label = _format_money(limit_minor, currency, exponent)
        percent = None if from_config else _num(spend.get("percent"))
        if percent is None:
            percent = amount / limit_minor * 100.0
        return f"{used_label} / {total_label}", percent

    # No ceiling anywhere -- say so plainly instead of implying one.
    return f"{used_label} used", None


def parse(payload):
    """Normalise a raw response into a Snapshot. Never raises."""
    snapshot = Snapshot(fetched_at=time.time())
    if not isinstance(payload, dict):
        return snapshot

    limits = []

    raw_limits = payload.get("limits")
    if isinstance(raw_limits, list):
        for entry in raw_limits:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind")
            percent = _num(entry.get("percent"))
            if kind is None or percent is None:
                continue
            limits.append(
                Limit(
                    key=str(kind),
                    label=_label_for(kind),
                    percent=percent,
                    resets_at=_parse_time(entry.get("resets_at")),
                    severity=str(entry.get("severity") or "normal"),
                )
            )

    if not limits:
        # Fall back to the flat per-window objects.
        for key, label in FALLBACK_KEYS:
            block = payload.get(key)
            if not isinstance(block, dict):
                continue
            percent = _num(block.get("utilization"))
            if percent is None:
                continue
            limits.append(
                Limit(
                    key={"five_hour": "session", "seven_day": "weekly_all"}.get(key, key),
                    label=label,
                    percent=percent,
                    resets_at=_parse_time(block.get("resets_at")),
                )
            )

    limits.sort(key=lambda item: _order_for(item.key))
    snapshot.limits = limits

    spend = payload.get("spend") if isinstance(payload.get("spend"), dict) else {}
    extra = payload.get("extra_usage") if isinstance(payload.get("extra_usage"), dict) else {}
    # Only show credits if the account actually has them enabled.
    if spend.get("enabled") or extra.get("is_enabled"):
        snapshot.credits_label, snapshot.credits_percent = _money(spend, extra)

    return snapshot


# --- fetching ------------------------------------------------------------

def fetch(session=None, allow_refresh=True):
    """Fetch and parse current usage.

    On 401 the credentials file is re-read (Claude Code rotates it underneath
    us) and, if that token is also rejected, a refresh is attempted once. That
    ordering matters: re-reading is free and non-destructive, refreshing mutates
    the file, so we only refresh when re-reading did not help.
    """
    import requests

    http = session or requests

    def _get(token):
        return http.get(
            config.USAGE_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=config.REQUEST_TIMEOUT,
        )

    try:
        creds = credentials.load()
    except credentials.CredentialsUnavailable as exc:
        raise AuthError(str(exc))

    try:
        response = _get(creds.access_token)

        if response.status_code in (401, 403):
            # Step 1: the file may have been rotated since we read it.
            try:
                creds = credentials.load()
            except credentials.CredentialsUnavailable as exc:
                raise AuthError(str(exc))
            response = _get(creds.access_token)

            # Step 2: still rejected -- mint a new token from the refresh token.
            if response.status_code in (401, 403) and allow_refresh:
                try:
                    creds = credentials.refresh()
                except credentials.RefreshFailed as exc:
                    raise AuthError(f"token refresh failed: {exc}")
                response = _get(creds.access_token)

        if response.status_code in (401, 403):
            raise AuthError(f"HTTP {response.status_code} after refresh")
        if response.status_code == 429:
            retry_after = None
            try:
                # Servers sometimes send 0 here; treat that as "no guidance".
                value = float(response.headers.get("retry-after", ""))
                retry_after = value if value > 0 else None
            except (TypeError, ValueError):
                pass
            raise RateLimited("rate limited by the server", retry_after)
        if response.status_code != 200:
            raise UsageError(
                f"HTTP {response.status_code}: {credentials.redact(response.text)[:200]}"
            )

        payload = response.json()
    except (AuthError, UsageError):
        raise
    except Exception as exc:
        raise UsageError(f"{type(exc).__name__}: {credentials.redact(exc)}")

    snapshot = parse(payload)
    if snapshot.ok:
        cache.save(payload)
    return snapshot


def from_cache():
    """Rebuild the last good snapshot from disk, flagged stale."""
    payload, fetched_at = cache.load()
    if payload is None:
        return None
    snapshot = parse(payload)
    snapshot.stale = True
    snapshot.fetched_at = fetched_at or 0.0
    return snapshot
