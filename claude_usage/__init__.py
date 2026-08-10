"""Claude Vitals -- tray icon + always-on-top overlay for Claude Pro usage.

Module map:
    config       paths, thresholds, palette
    credentials  reads the OAuth token from ~/.claude/.credentials.json
    usage        fetches and normalises the usage endpoint response
    cache        last-good snapshot + UI state on disk
    poller       the single background poll loop
    tray         pystray icon, tooltip, menu, toasts
    overlay      frameless always-on-top tkinter strip
    win32        foreground detection, no-activate windows, startup shortcut
    app          wires it together
"""

__version__ = "0.1.0"
