"""Test behaviour when the endpoint rate-limits us (HTTP 429).

    .venv\\Scripts\\python.exe tools\\test_rate_limit.py

The real endpoint refuses a second request made a couple of seconds after the
first. Pressing Refresh therefore hits a 429 routinely -- and the numbers we
already hold are still perfectly good. Showing "stale - just now" in that
situation is a bug, not information.

Uses fake HTTP responses; makes no network calls.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_usage import config, poller as poller_mod, state as state_mod, usage  # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{'  -- ' + detail if detail else ''}")


_live = config.STATE_DIR / "sample_response.json"
_fixture = Path(__file__).resolve().parent / "sample_response.json"
SAMPLE = json.loads((_live if _live.exists() else _fixture).read_text(encoding="utf-8"))


class Resp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text or json.dumps(payload or {})
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *_a, **_k):
        self.calls += 1
        return self.responses.pop(0) if self.responses else Resp(500)


RATE_LIMIT_BODY = json.dumps({"error": {"type": "rate_limit_error",
                                        "message": "Rate limited. Please try again later."}})

print("=== 1. a 429 raises RateLimited, not a generic failure ===")
try:
    usage.fetch(session=Session([Resp(429, text=RATE_LIMIT_BODY,
                                      headers={"retry-after": "0"})]))
    check("raised", False)
except usage.RateLimited as exc:
    check("raised RateLimited", True, str(exc))
    check("retry-after of 0 treated as no guidance", exc.retry_after is None)
except Exception as exc:
    check("raised RateLimited", False, f"got {type(exc).__name__}")

try:
    usage.fetch(session=Session([Resp(429, text=RATE_LIMIT_BODY,
                                      headers={"retry-after": "45"})]))
except usage.RateLimited as exc:
    check("honours a real retry-after", exc.retry_after == 45.0, str(exc.retry_after))

print("\n=== 2. a 429 must NOT discard good numbers ===")
st = state_mod.State()
p = poller_mod.Poller(st)

original = usage.fetch
usage.fetch = lambda **kw: original(session=Session([Resp(200, SAMPLE)]), **kw)
try:
    good = p.poll_once()
finally:
    usage.fetch = original
check("first poll succeeded", good.ok, f"{len(good.limits)} rows")
first_rows = [(l.key, l.percent) for l in good.limits]
first_time = good.fetched_at

usage.fetch = lambda **kw: original(session=Session([Resp(429, text=RATE_LIMIT_BODY)]), **kw)
try:
    after = p.poll_once()
finally:
    usage.fetch = original

check("numbers unchanged after a 429", [(l.key, l.percent) for l in after.limits] == first_rows,
      str([(l.key, l.percent) for l in after.limits]))
check("NOT flagged stale", not after.stale,
      "this is what produced 'stale - just now'")
check("timestamp preserved", after.fetched_at == first_time)
check("backoff at least the rate-limit floor", p.backoff >= config.RATE_LIMIT_BACKOFF,
      f"backoff={p.backoff}s")

print("\n=== 3. a genuine failure still falls back and flags stale ===")
st2 = state_mod.State()
p2 = poller_mod.Poller(st2)


class Boom:
    def get(self, *_a, **_k):
        raise ConnectionError("network down")


usage.fetch = lambda **kw: original(session=Boom(), **kw)
try:
    broken = p2.poll_once()
finally:
    usage.fetch = original
check("fell back to cache", bool(broken.limits), f"{len(broken.limits)} rows")
check("flagged stale", broken.stale is True)

print("\n=== 4. the overlay only warns once data is genuinely old ===")
from claude_usage import overlay as om  # noqa: E402
fresh = usage.parse(SAMPLE)
fresh.stale = True
fresh.fetched_at = time.time() - 10
check("10s old -> no stale warning", not om.Overlay._is_old(fresh.fetched_at),
      f"threshold is {config.STALE_AFTER}s")
old = time.time() - (config.STALE_AFTER + 60)
check("older than the threshold -> warns", om.Overlay._is_old(old))
check("unknown timestamp -> warns", om.Overlay._is_old(0))

print("\n" + ("ALL PASSED" if all(results) else f"{results.count(False)} FAILED"))
sys.exit(0 if all(results) else 1)
