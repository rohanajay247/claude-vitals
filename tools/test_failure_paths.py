"""Failure-path tests: stale fallback, backoff, and 401 recovery ordering.

    .venv\\Scripts\\python.exe tools\\test_failure_paths.py

Uses fake HTTP sessions and a stubbed refresh, so it never touches the real
credentials file or the network.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_usage import cache, config, credentials, poller as poller_mod, state as state_mod, usage  # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{'  -- ' + detail if detail else ''}")


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Returns a scripted sequence of responses, recording the calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return self.responses.pop(0) if self.responses else FakeResponse(500)


# Prefer a real captured response if you have one; otherwise use the sanitised
# fixture that ships with the repo, so this runs on a fresh clone.
_live = config.STATE_DIR / "sample_response.json"
_fixture = Path(__file__).resolve().parent / "sample_response.json"
SAMPLE = json.loads((_live if _live.exists() else _fixture).read_text(encoding="utf-8"))

print("=== 1. network failure falls back to cache, flagged stale ===")
cache.save(SAMPLE)   # ensure a good cache exists


class ExplodingSession:
    def get(self, *_a, **_k):
        raise ConnectionError("simulated network outage")


st = state_mod.State()
p = poller_mod.Poller(st)
original_fetch = usage.fetch
usage.fetch = lambda **kw: original_fetch(session=ExplodingSession(), **kw)
try:
    snap = p.poll_once()
finally:
    usage.fetch = original_fetch

check("snapshot still has rows", bool(snap.limits), f"{len(snap.limits)} rows")
check("flagged stale", snap.stale is True)
check("carries an error", bool(snap.error), (snap.error or "")[:60])
check("backoff armed", p.backoff == config.BACKOFF_START, f"backoff={p.backoff}")
check("no token in error text", "Bearer" not in (snap.error or ""))

print("\n=== 2. no cache + failure = empty snapshot, still no crash ===")
saved_cache = config.CACHE_FILE.read_text(encoding="utf-8")
cache.clear()
st2 = state_mod.State()
p2 = poller_mod.Poller(st2)
usage.fetch = lambda **kw: original_fetch(session=ExplodingSession(), **kw)
try:
    snap2 = p2.poll_once()
finally:
    usage.fetch = original_fetch
    config.CACHE_FILE.write_text(saved_cache, encoding="utf-8")  # restore

check("no rows", snap2.limits == [])
check("has error", bool(snap2.error))
check("headline is None", snap2.headline is None)

print("\n=== 3. 401 -> re-read credentials -> refresh, in that order ===")
refresh_calls = []


def fake_refresh():
    refresh_calls.append(1)
    return credentials.Credentials(access_token="new", expires_at=None,
                                   subscription_type="pro")


real_refresh = credentials.refresh
credentials.refresh = fake_refresh
try:
    # 401, 401, then success -> should re-read once, refresh once, succeed.
    session = FakeSession([
        FakeResponse(401, text='{"error":"expired"}'),
        FakeResponse(401, text='{"error":"expired"}'),
        FakeResponse(200, SAMPLE),
    ])
    snap3 = usage.fetch(session=session)
    check("recovered after refresh", snap3.ok, f"{len(snap3.limits)} rows")
    check("made exactly 3 requests", session.calls == 3, f"calls={session.calls}")
    check("refreshed exactly once", len(refresh_calls) == 1)

    # 401 then success on re-read alone -> must NOT refresh.
    refresh_calls.clear()
    session2 = FakeSession([FakeResponse(401), FakeResponse(200, SAMPLE)])
    snap4 = usage.fetch(session=session2)
    check("re-read alone was enough", snap4.ok)
    check("did NOT refresh unnecessarily", len(refresh_calls) == 0)
finally:
    credentials.refresh = real_refresh

print("\n=== 4. redaction ===")
# Deliberately NOT shaped like a real Anthropic key prefix: a realistic-looking
# literal here would trip GitHub's secret scanning and block a push. Still long
# enough to exercise redact()'s length rule.
fake_token = "NOT-A-REAL-TOKEN-" + "A1b2C3d4" * 12
check("token-shaped string is scrubbed",
      "<redacted>" in credentials.redact(f"failed with {fake_token}"),
      credentials.redact(f"failed with {fake_token}")[:60])
check("long bearer blob scrubbed",
      fake_token not in credentials.redact(f"Authorization: Bearer {fake_token}"))
creds = credentials.Credentials(access_token=fake_token, expires_at=None,
                                subscription_type="pro")
check("repr never exposes the token", fake_token not in repr(creds), repr(creds))

print("\n=== 5. non-200, non-401 surfaces cleanly ===")
session5 = FakeSession([FakeResponse(503, text="upstream unavailable")])
try:
    usage.fetch(session=session5)
    check("raised UsageError", False)
except usage.UsageError as exc:
    check("raised UsageError", True, str(exc)[:50])
except Exception as exc:
    check("raised UsageError", False, f"got {type(exc).__name__}")

print("\n" + ("ALL PASSED" if all(results) else f"{results.count(False)} FAILED"))
sys.exit(0 if all(results) else 1)
