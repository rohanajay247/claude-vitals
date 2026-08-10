"""Shared state between the poll thread, the tray thread and the Tk main thread.

One lock, small critical sections, no callbacks fired while holding it. The Tk
thread only ever reads; the poller only ever writes.
"""

import threading

from . import cache, config


class State:
    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot = None
        self.overlay_enabled = True     # tray toggle, per-session
        # Default on: the overlay is meant to be up while you work, and you
        # close it when you are done. Untick for follow-Claude behaviour.
        # Persisted, like the pin -- a working preference should survive a
        # restart rather than resetting every launch.
        self.always_visible = bool(
            cache.load_ui_state().get("always_visible", config.ALWAYS_VISIBLE_DEFAULT)
        )
        self.notifications_enabled = bool(
            cache.load_ui_state().get("notifications", config.NOTIFY_ENABLED_DEFAULT)
        )
        self.stop_event = threading.Event()
        self.refresh_now = threading.Event()

    def persist_always_visible(self):
        ui = cache.load_ui_state()
        ui["always_visible"] = self.always_visible
        cache.save_ui_state(ui)

    def persist_notifications(self):
        ui = cache.load_ui_state()
        ui["notifications"] = self.notifications_enabled
        cache.save_ui_state(ui)

    @property
    def snapshot(self):
        with self._lock:
            return self._snapshot

    @snapshot.setter
    def snapshot(self, value):
        with self._lock:
            self._snapshot = value
