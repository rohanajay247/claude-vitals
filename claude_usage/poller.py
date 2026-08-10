"""The single background poll loop.

One loop feeds both the tray and the overlay -- there is deliberately no second
request path anywhere in the app.

Failure behaviour, in order of preference:
  1. Success            -> fresh snapshot, cached to disk, backoff reset.
  2. Failure w/ cache   -> last good values, flagged stale, exponential backoff.
  3. Failure w/o cache  -> empty snapshot carrying the (redacted) error.

It never raises out of the loop and never tightens its retry interval on
repeated failure, so a broken endpoint costs one request every 15 minutes at
worst rather than a hot loop.
"""

import threading
import time

from . import cache, config, usage


class Poller(threading.Thread):
    def __init__(self, state, on_update=None, notify=None):
        super().__init__(name="usage-poller", daemon=True)
        self.state = state
        self.on_update = on_update
        self.notify = notify
        self.backoff = None
        self._notified = {}   # threshold -> reset timestamp it last fired for

    # --- notifications ---------------------------------------------------

    def _check_thresholds(self, snapshot):
        """Fire a toast when session usage crosses a threshold.

        Deduped per reset window: we record which window each threshold fired
        for, so it fires at most once per 5-hour window however often we poll,
        and naturally re-arms when the window rolls over to a new resets_at.
        """
        session = snapshot.session if snapshot else None
        if not session or self.notify is None:
            return
        if not self.state.notifications_enabled:
            # Still record which windows we have passed, so switching alerts on
            # mid-window does not immediately fire for thresholds long crossed.
            window = session.resets_at.isoformat() if session.resets_at else "unknown"
            for threshold in config.NOTIFY_AT:
                if session.percent >= threshold:
                    self._notified[threshold] = window
            return
        window = session.resets_at.isoformat() if session.resets_at else "unknown"

        for threshold in config.NOTIFY_AT:
            if session.percent < threshold:
                continue
            if self._notified.get(threshold) == window:
                continue
            self._notified[threshold] = window
            hint = session.reset_hint()
            self.notify(
                f"Claude session usage at {session.percent:.0f}%",
                hint[0].upper() + hint[1:] if hint else "",
            )

    # --- main loop -------------------------------------------------------

    def poll_once(self):
        try:
            snapshot = usage.fetch()
            self.backoff = None
            self.state.snapshot = snapshot
            self._check_thresholds(snapshot)
        except usage.UsageError as exc:
            # Includes AuthError. usage.fetch() has already re-read the
            # credentials file and tried a refresh before giving up.
            fallback = usage.from_cache()
            if fallback is not None:
                fallback.error = str(exc)
                self.state.snapshot = fallback
            else:
                empty = usage.Snapshot(fetched_at=time.time(), error=str(exc))
                self.state.snapshot = empty
            self._grow_backoff()
        except Exception as exc:  # pragma: no cover - belt and braces
            self.state.snapshot = usage.Snapshot(
                fetched_at=time.time(), error=f"{type(exc).__name__}"
            )
            self._grow_backoff()

        if self.on_update:
            try:
                self.on_update(self.state.snapshot)
            except Exception:
                pass
        return self.state.snapshot

    def _grow_backoff(self):
        if self.backoff is None:
            self.backoff = config.BACKOFF_START
        else:
            self.backoff = min(self.backoff * config.BACKOFF_FACTOR, config.BACKOFF_MAX)

    def _wait(self):
        """Sleep until the next poll, waking early on a manual refresh."""
        delay = self.backoff if self.backoff else config.POLL_INTERVAL
        if self.state.refresh_now.wait(timeout=delay):
            self.state.refresh_now.clear()

    def run(self):
        # Show cached numbers immediately so a restart is never blank.
        cached = usage.from_cache()
        if cached is not None:
            self.state.snapshot = cached
            if self.on_update:
                try:
                    self.on_update(cached)
                except Exception:
                    pass

        while not self.state.stop_event.is_set():
            self.poll_once()
            if self.state.stop_event.is_set():
                break
            self._wait()
