"""Process wiring.

Threading model, which is dictated by the libraries:

  main thread   Tk mainloop -- tkinter is not thread-safe and must own it.
                Also runs the 500ms visibility tick.
  tray thread   pystray's own message loop.
  poll thread   the single usage poll loop.

The poller writes into State; the Tk tick reads it. No widget is ever touched
from a non-Tk thread.
"""

import ctypes
import sys
import threading

import tkinter as tk

from . import (config, credentials, dialogs, overlay as overlay_mod,
               poller as poller_mod, state as state_mod, tray as tray_mod,
               usage as usage_mod, win32)


def _enable_dpi_awareness():
    """Per-monitor DPI awareness, or the overlay text renders blurry."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class App:
    def __init__(self):
        config.ensure_state_dir()
        _enable_dpi_awareness()
        # Must happen before any window exists, or Windows has already decided
        # we are generic "Python".
        win32.set_app_user_model_id()

        self.state = state_mod.State()

        # Whoever had the foreground before we created any window. Creating our
        # first window can take it (a launching process is granted foreground
        # rights), so we hand it straight back once the UI exists -- otherwise
        # starting the app while you are typing swallows a keystroke.
        self._prev_foreground = win32.foreground_hwnd()
        self._explained = False       # setup help is shown at most once per run

        self.root = tk.Tk()
        self.root.withdraw()             # no root window, only the overlay
        self.overlay = overlay_mod.Overlay(
            self.root, self.state,
            on_quit=self.quit,           # the overlay's ✕ stops everything
            on_refresh=self.refresh_now,
        )

        self.tray = tray_mod.Tray(
            self.state,
            on_refresh=self.refresh_now,
            on_quit=self.quit,
            on_toggle_overlay=lambda _enabled: None,
            on_toggle_always=lambda _always: self.state.persist_always_visible(),
            restart_args=f'"{config.PROJECT_DIR / "run.pyw"}"',
            # These touch Tk widgets, so they are marshalled onto the Tk thread
            # rather than run directly on pystray's thread.
            on_bring_to_front=lambda: self._on_tk(self.overlay.bring_to_front),
            on_toggle_pin=lambda: self._on_tk(self.overlay.toggle_pin),
            is_pinned=lambda: self.overlay.pinned,
            on_set_credits=lambda: self._on_tk(self.edit_credits),
        )

        self.poller = poller_mod.Poller(
            self.state,
            on_update=self.tray.update,
            notify=self.tray.notify,
        )

        self._tray_thread = threading.Thread(
            target=self.tray.run, name="tray", daemon=True
        )

        # Listens for a second launch (a click on the pinned icon, say) and
        # surfaces this instance instead of letting another one start.
        self._show_event = win32.create_show_event()
        self._show_thread = threading.Thread(
            target=self._watch_show_requests, name="show-watch", daemon=True
        )

    # --- visibility ------------------------------------------------------

    def _should_show(self):
        if not self.state.overlay_enabled:
            return False
        if self.state.always_visible:
            return True
        # Our own window counts as Claude, so dragging the strip does not make
        # it disappear mid-drag.
        own = self.overlay._resolve_hwnd()
        return win32.is_claude_foreground(extra_hwnds=(own,) if own else ())

    def tick(self):
        """500ms: reconcile visibility and repaint if the data changed."""
        try:
            snapshot = self.state.snapshot
            # Release a temporary on-top once the user has switched windows.
            self.overlay.update_peek(win32.foreground_hwnd())
            if self._should_show():
                self.overlay.render(snapshot)
                self.overlay.show()
            else:
                self.overlay.hide()
        except Exception:
            # A UI hiccup must never kill the loop.
            pass
        if not self.state.stop_event.is_set():
            self.root.after(int(config.FOREGROUND_INTERVAL * 1000), self.tick)

    # --- actions ---------------------------------------------------------

    def _on_tk(self, fn):
        """Run a callback on the Tk thread. tkinter is not thread-safe, and the
        tray menu callbacks arrive on pystray's thread."""
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def _watch_show_requests(self):
        """Another launch asked us to appear -- surface, don't duplicate."""
        if not self._show_event:
            return
        while not self.state.stop_event.is_set():
            if win32.wait_show_event(self._show_event, 500):
                self._on_tk(self.overlay.bring_to_front)

    def _give_back_foreground(self):
        """If starting up displaced someone, put them back."""
        own = self.overlay._resolve_hwnd()
        current = win32.foreground_hwnd()
        if current and own and current == own and self._prev_foreground != own:
            win32.restore_foreground(self._prev_foreground)

    def _check_setup(self):
        """Once per run, explain why there are no numbers -- rather than just
        showing a grey dash and leaving the user to guess."""
        if self._explained:
            return
        snapshot = self.state.snapshot
        if snapshot is not None and snapshot.limits:
            return                      # working fine, nothing to explain

        try:
            credentials.load()
        except credentials.CredentialsUnavailable:
            self._explained = True
            try:
                dialogs.show_setup_help(self.root, "missing")
            except Exception:
                pass
            return

        # Credentials exist but we still have no rows: only speak up if the
        # failure was an auth one. A network blip should stay quiet.
        error = (snapshot.error or "") if snapshot else ""
        if "refresh failed" in error or "401" in error or "403" in error:
            self._explained = True
            try:
                dialogs.show_setup_help(self.root, "expired")
            except Exception:
                pass

    def edit_credits(self):
        """Open the credits-total dialog, then repaint with the new figure."""
        snapshot = self.state.snapshot
        currency = None
        if snapshot and snapshot.credits_label:
            for code, symbol in dialogs.SYMBOLS.items():
                if symbol in snapshot.credits_label:
                    currency = code
                    break
        try:
            saved = dialogs.ask_credits_total(self.root, currency=currency)
        except Exception:
            return
        if saved:
            # Re-parse the cached payload so the row updates immediately rather
            # than at the next poll.
            refreshed = usage_mod.from_cache()
            if refreshed is not None:
                refreshed.stale = bool(snapshot and snapshot.stale)
                self.state.snapshot = refreshed
                self.tray.update(refreshed)
            self.overlay._sig = None      # force a full repaint
            self.refresh_now()

    def refresh_now(self):
        self.state.refresh_now.set()

    def quit(self):
        self.state.stop_event.set()
        try:
            self.root.after(0, self.root.quit)
        except Exception:
            pass

    # --- lifecycle -------------------------------------------------------

    def run(self):
        self._tray_thread.start()
        self._show_thread.start()
        self.poller.start()
        self.root.after(200, self.tick)
        # After the first paint has settled, return the foreground if we took it.
        self.root.after(600, self._give_back_foreground)
        # Give the first poll a chance, then explain if there is nothing to show.
        self.root.after(4000, self._check_setup)
        try:
            self.root.mainloop()
        finally:
            self.state.stop_event.set()
            self.tray.stop()


def main():
    # Refuse to start a second copy. Clicking a pinned taskbar icon repeatedly
    # would otherwise stack up instances, each with its own tray icon and poll
    # loop. Instead, wake the one already running and exit quietly.
    lock = win32.acquire_single_instance()
    if lock is None:
        win32.signal_existing_instance()
        return 0

    try:
        app = App()
        app.run()
    finally:
        win32.release_single_instance(lock)
    return 0


if __name__ == "__main__":
    sys.exit(main())
