"""Headless checks: icon drawing, tooltip, one real poll, cache/stale fallback.

    .venv\\Scripts\\python.exe tools\\smoke_test.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from claude_usage import cache, config, poller as poller_mod, state as state_mod, tray, usage  # noqa: E402

print("=== 1. icon rendering ===")
strip = Image.new("RGBA", (64 * 6, 64), (30, 30, 30, 255))
for i, pct in enumerate([None, 5, 45, 62, 88, 100]):
    img = tray.draw_icon(pct, stale=(pct == 62))
    strip.paste(img, (i * 64, 0), img)
    print(f"   drew icon for percent={pct} stale={pct == 62} -> {img.size}")
out = config.STATE_DIR / "icon_preview.png"
config.ensure_state_dir()
strip.save(out)
print(f"   preview strip saved -> {out}")

print("\n=== 2. one real poll ===")
st = state_mod.State()
notices = []
p = poller_mod.Poller(st, notify=lambda t, m: notices.append((t, m)))
started = time.time()
snap = p.poll_once()
print(f"   took {time.time() - started:.2f}s   ok={snap.ok}  error={snap.error}")
for limit in snap.limits:
    print(f"     {limit.label:<22} {limit.percent:>5.1f}%   {limit.reset_hint()}")
print(f"   credits: {snap.credits_label}")
print(f"   toasts fired: {notices}")

print("\n=== 3. tooltip ===")
print("   " + build.replace("\n", "\n   ") if (build := tray.build_tooltip(snap)) else "")

print("\n=== 4. cache written? ===")
payload, fetched = cache.load()
print(f"   cache has payload: {payload is not None}, fetched_at={fetched}")

print("\n=== 5. stale fallback (simulated outage) ===")
stale = usage.from_cache()
print(f"   stale snapshot ok={stale.ok} stale={stale.stale} headline={stale.headline}")

print("\n=== 6. threshold dedupe ===")
st2 = state_mod.State()
fired = []
p2 = poller_mod.Poller(st2, notify=lambda t, m: fired.append(t))
fake = usage.parse({"limits": [{"kind": "session", "percent": 96,
                               "resets_at": "2026-08-10T19:29:59+00:00"}]})
for _ in range(5):
    p2._check_thresholds(fake)
print(f"   5 polls at 96% -> {len(fired)} toast(s): {fired}")
newer = usage.parse({"limits": [{"kind": "session", "percent": 96,
                                 "resets_at": "2026-08-11T00:29:59+00:00"}]})
p2._check_thresholds(newer)
print(f"   after window rollover -> {len(fired)} total (should be 4)")

print("\n=== 7. backoff growth ===")
p3 = poller_mod.Poller(state_mod.State())
seq = []
for _ in range(8):
    p3._grow_backoff()
    seq.append(p3.backoff)
print(f"   {seq}  (capped at {config.BACKOFF_MAX})")

print("\nSmoke test complete.")
