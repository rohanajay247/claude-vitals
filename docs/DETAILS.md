# Claude Vitals — the longer version

Everything that didn't belong in the [README](../README.md). Read it if you're
curious, or if something has gone wrong.

---

## Why this exists

Mid-conversation I'd wonder how much of my allowance was left, and the only way
to find out was to stop, open Settings, click through to Usage, read a number,
and come back. Several times a day. Claude Code shows this in a panel right
there; the Chat tab doesn't.

Built with Claude Code — vibecoded — over a handful of sessions. The tricky
parts (never stealing focus, surviving outages, never leaking your token) were
worked through deliberately and there's a test suite you can run. But it's a
side project by one person, not production software.

---

## How it works

![Architecture](diagram-architecture.png)

One program doing three things at once: a **fetcher** that asks the endpoint for
your usage every 3 minutes, **shared memory** holding the latest numbers, and
the **tray and overlay** that draw them. The display never waits on the network.

![What happens on failure](diagram-failure.png)

When a check fails it falls back to the last cached numbers, and retries on a
widening gap (30s, 1m, 2m … capped at 15m). If your login is rejected it
re-reads the file, then renews the token automatically — backing up the original
first.

The endpoint rate-limits hard: a second request a couple of seconds after the
first returns `429`. So a manual refresh is skipped when the figures are already
under 30 seconds old, and a `429` never discards good numbers — your usage
hasn't changed just because one refresh was refused. The `stale` marker only
appears once the figures are more than 7 minutes old.

### The overlay

![Every part of the overlay, labelled](diagram-anatomy.png)

It never takes focus. Three things guarantee that: `WS_EX_NOACTIVATE` on the
window, `SetWindowPos` with `SWP_NOACTIVATE` everywhere, and never calling
tkinter's `lift()` or `focus_force()`. At startup it also hands the foreground
back if creating its first window displaced someone.

Unlocking drops it into the normal z-order. Bringing it forward then holds it on
top briefly rather than raising it outright — Windows won't let a background
window climb above the active one without activating, and activating would steal
your cursor.

### Project layout

```
run.pyw                 entry point (checks your Python version first)
setup.bat               first-time setup
uninstall.bat           complete removal
claude_usage/
  config.py             paths, thresholds, palette
  settings.py           user settings (state/settings.json)
  credentials.py        reads and renews the OAuth token; redaction
  usage.py              fetches and normalises the endpoint response
  cache.py              last-good snapshot and UI state
  poller.py             the single poll loop, backoff, alert de-duplication
  tray.py               tray icon, tooltip, menu
  overlay.py            the frameless always-on-top card
  dialogs.py            settings and first-run help
  win32.py              foreground detection, focus-safe windows, shortcuts
  app.py                thread wiring
statusline/             optional Claude Code status line
tools/                  diagnostics and tests
```

---

## Privacy and security in full

### What it changes on your machine

1. **It can rewrite `~/.claude/.credentials.json`.** Your Claude login expires
   roughly every 8 hours and the desktop app doesn't refresh that file, so
   Claude Vitals renews it using the refresh token already stored there. It
   copies the file to `.credentials.json.bak` first and writes the replacement
   atomically. Worst realistic case: renewal fails and you run
   `claude auth login` again.
2. **Shortcuts** on your Desktop, in the Start menu, and — only if you ask — in
   your Startup folder. Plain `.lnk` files you can delete.
3. **If you install the status line**, two entries under `~/.claude`. Your
   existing settings are backed up and merged, never overwritten.

Everything else stays inside the project folder.

### What leaves your machine

Two addresses, both Anthropic's, and you can grep the source to confirm it:
`api.anthropic.com/api/oauth/usage` to read your usage, and
`console.anthropic.com/v1/oauth/token` to renew your login. One request every
3 minutes. No server of ours, no analytics, no telemetry, nothing listening.

### Your token

Read from disk per request, used, discarded. Never copied into the app's own
files, never logged, never printed. Error messages are scrubbed before display
and the credential object's `repr` is overridden so it can't leak through a
stack trace. `tools/test_failure_paths.py` asserts this.

### Honest limitations

- It's a side project, not audited software. MIT licence, no warranty.
- It has dependencies — `pystray`, `Pillow`, `requests`, `pywin32`. Pinned, but
  installing from PyPI carries the usual supply-chain risk.
- The endpoint is undocumented and Anthropic hasn't endorsed polling it. Three
  minutes between requests is modest, but make your own judgement.
- Bugs are possible. The tests cover the paths I thought of; they don't prove
  absence.

---

## Performance

Measured while running with the overlay visible:

| | |
|---|---|
| CPU | ~0.3% of one core |
| RAM | ~55 MB |
| Network | one request per 3 minutes |

A full canvas repaint only happens when the text changes; the rotating mark and
easing bars just move existing items, and the frame rate drops to 6fps when
nothing is moving. Re-measure with `tools\measure_cost.py`.

---

## Usage credits

Claude reports what you've **spent** but not your **balance** or granted total —
those come back empty unless your account has a monthly spend cap. So most
people set the total once via the tray menu.

Find it in Claude under **Settings → Usage**: add the *amount spent* to your
*current balance*. The spent side stays live afterwards. Leave it blank and the
row shows spend only, with no bar.

Promotional credits expire — update the total when they lapse or you top up.

---

## Optional: the Claude Code status line

`statusline/` adds a two-line status line to Claude Code in a terminal, showing
model, context and rate limits:

```
python statusline\install.py
```

**It will not appear in the Claude desktop app** — the desktop interface has no
status-line renderer; it's a terminal feature. Remove it with `--uninstall`.

This part makes no network requests; Claude Code hands it the data directly.

---

## Running the tests

```
.venv\Scripts\python.exe tools\test_parse.py           # parsing, incl. hostile input
.venv\Scripts\python.exe tools\test_failure_paths.py   # outages, auth recovery, redaction
.venv\Scripts\python.exe tools\test_rate_limit.py      # 429 handling, stale threshold
.venv\Scripts\python.exe tools\test_settings.py        # settings, dialogs, credit totals
.venv\Scripts\python.exe tools\test_lock.py            # lock, bring-to-front, buttons
.venv\Scripts\python.exe tools\test_peek.py            # surfacing a buried overlay
.venv\Scripts\python.exe tools\test_single_instance.py # only one copy can run
.venv\Scripts\python.exe tools\test_visibility.py      # follow-Claude visibility
.venv\Scripts\python.exe tools\verify_overlay.py       # window flags and focus safety
python statusline\test_statusline.py                   # status line, mocked input
```

Regenerating the images in `docs/`:

```
.venv\Scripts\python.exe tools\make_demo_shot.py
.venv\Scripts\python.exe tools\make_demo_gif.py
.venv\Scripts\python.exe docs\make_diagrams.py
```

---

## Troubleshooting, less common cases

| Problem | What's happening |
|---|---|
| It doesn't follow my Claude window | Run `tools\probe_foreground.py 6` to see what your Claude app is called, then add it to `extra_claude_processes` in `state/settings.json`. |
| Uninstaller says it can't remove `.venv` | Run `python uninstall.py --all` with system Python — the bundled one can't delete the folder it's running from. |
| A taskbar icon lingers after uninstalling | Right-click → *Unpin from taskbar*. Windows caches pins until Explorer restarts. |

---

## Contributing

Issues and pull requests are welcome, but this is a side project maintained in
spare time. The most useful contributions would be macOS or Linux support (the
Windows-specific parts are confined to `win32.py`), or reports of what the
endpoint returns on Max and Team accounts.
