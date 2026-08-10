"""Reading the Claude Code OAuth token off disk.

Rules this module exists to enforce:

  * The token is read from ~/.claude/.credentials.json at call time, every time.
    It is never copied into our own state, never written to the cache, never
    logged, and never held longer than a request needs it.
  * Nothing here may put a token into a string that could reach a log, a
    traceback or the UI. `redact()` is the only way token-adjacent text should
    ever leave this module.

The access token observed on this machine has an ~8 hour lifetime while the
refresh token lasts about four weeks, so an expired token is the normal steady
state, not an exception -- `load()` reports it rather than raising.
"""

import json
import os
import re
import shutil
import time
from dataclasses import dataclass

from . import config

# Claude Code's public OAuth client id. Public by design (it is a native-app
# client and ships in the binary); it is an identifier, not a secret.
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"


class CredentialsUnavailable(Exception):
    """No usable credentials on disk. Carries no token material."""


class RefreshFailed(Exception):
    """Refresh attempt failed. Message is always passed through redact()."""


@dataclass
class Credentials:
    access_token: str
    expires_at: float | None      # epoch seconds, or None if unknown
    subscription_type: str | None

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False  # unknown expiry: let the server be the judge
        return time.time() >= self.expires_at

    def __repr__(self):
        # Defensive: a dataclass repr would print the token in any traceback
        # that happens to include this object.
        return (
            f"Credentials(access_token=<redacted>, "
            f"expires_at={self.expires_at}, subscription_type={self.subscription_type!r})"
        )

    __str__ = __repr__


_TOKEN_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}|[A-Za-z0-9_\-]{40,}")


def redact(text):
    """Scrub anything token-shaped out of arbitrary text before it is logged.

    Applied to every error message and HTTP body we surface. Deliberately
    aggressive -- a redacted log line is recoverable, a leaked token is not.
    """
    return _TOKEN_RE.sub("<redacted>", str(text))


def load():
    """Read credentials from disk.

    Raises CredentialsUnavailable if the file is missing, unreadable, or has no
    access token. Callers re-invoke this on 401 because Claude Code rotates the
    file underneath us.
    """
    path = config.CREDENTIALS_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise CredentialsUnavailable(f"No credentials file at {path}")
    except OSError as exc:
        raise CredentialsUnavailable(f"Cannot read {path}: {exc.strerror}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Do not include the body in the message -- it contains the token.
        raise CredentialsUnavailable(f"{path} is not valid JSON")

    oauth = (data or {}).get("claudeAiOauth") or {}
    token = oauth.get("accessToken")
    if not token or not isinstance(token, str):
        raise CredentialsUnavailable("No claudeAiOauth.accessToken in credentials file")

    expires_at = oauth.get("expiresAt")
    try:
        # Stored in MILLISECONDS; we work in seconds everywhere else.
        expires_at = float(expires_at) / 1000.0 if expires_at is not None else None
    except (TypeError, ValueError):
        expires_at = None

    return Credentials(
        access_token=token,
        expires_at=expires_at,
        subscription_type=oauth.get("subscriptionType"),
    )


def refresh(session=None):
    """Exchange the stored refresh token for a fresh access token.

    The access token lives ~8 hours while the refresh token lasts ~4 weeks, and
    the desktop app does not maintain this file -- so without this the poller
    would break within a day of every manual login.

    The credentials file is backed up before it is rewritten, and the write is
    atomic: an interrupted refresh must never leave a truncated file that locks
    the user out of their CLI. Returns the new Credentials.
    """
    import requests  # local import: keeps this module importable without deps

    path = config.CREDENTIALS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RefreshFailed(f"cannot read credentials: {redact(exc)}")

    oauth = (data or {}).get("claudeAiOauth") or {}
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        raise RefreshFailed("no claudeAiOauth.refreshToken to refresh with")

    http = session or requests
    try:
        response = http.post(
            TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            },
            headers={"Content-Type": "application/json"},
            timeout=config.REQUEST_TIMEOUT,
        )
    except Exception as exc:
        raise RefreshFailed(f"network error: {redact(exc)}")

    if response.status_code != 200:
        raise RefreshFailed(
            f"HTTP {response.status_code}: {redact(response.text)[:300]}"
        )

    try:
        payload = response.json()
    except ValueError:
        raise RefreshFailed("token endpoint returned non-JSON")

    new_access = payload.get("access_token")
    if not new_access:
        # Report which keys came back, never their values.
        raise RefreshFailed(f"no access_token in response (keys: {sorted(payload)})")

    # Back up before touching the original.
    backup = path.with_suffix(".json.bak")
    try:
        shutil.copy2(path, backup)
    except OSError as exc:
        raise RefreshFailed(f"refusing to rewrite without a backup: {redact(exc)}")

    oauth["accessToken"] = new_access
    # Refresh tokens usually rotate; keep the old one if the server omits it.
    if payload.get("refresh_token"):
        oauth["refreshToken"] = payload["refresh_token"]
    if payload.get("expires_in"):
        try:
            oauth["expiresAt"] = int((time.time() + float(payload["expires_in"])) * 1000)
        except (TypeError, ValueError):
            pass
    data["claudeAiOauth"] = oauth

    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RefreshFailed(f"could not write credentials: {redact(exc)}")

    return load()


def describe():
    """Human-readable credential status for the tray/README, token-free."""
    try:
        creds = load()
    except CredentialsUnavailable as exc:
        return f"unavailable: {exc}"
    if creds.is_expired:
        ago = int(time.time() - creds.expires_at)
        return f"expired {ago // 3600}h ago -- run `claude setup-token`"
    return f"ok ({creds.subscription_type or 'unknown plan'})"
