"""Tests for user settings and the dialogs that edit them.

    .venv\\Scripts\\python.exe tools\\test_settings.py

Backs up and restores state/settings.json, so running it never disturbs your
configured credit total.
"""

import shutil
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_usage import config, dialogs, settings, usage  # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{'  -- ' + detail if detail else ''}")


path = config.STATE_DIR / "settings.json"
backup = path.with_suffix(".json.testbak") if path.exists() else None
if backup:
    shutil.copy2(path, backup)

try:
    print("=== 1. amount parsing ===")
    cases = [("50", 5000), ("50.00", 5000), ("$50", 5000), ("1,234.50", 123450),
             ("0.99", 99), ("", None), ("   ", None)]
    for text, expected in cases:
        got = dialogs._parse_amount(text)
        check(f"{text!r} -> {expected}", got == expected, f"got {got}")

    # A typo must NOT be treated as "clear the setting".
    for junk in ("abc", "!!", "-5", "0"):
        raised = False
        try:
            dialogs._parse_amount(junk)
        except ValueError:
            raised = True
        check(f"{junk!r} raises rather than silently clearing", raised)

    print("\n=== 2. round-trip through settings.json ===")
    settings.save({"credits_total_minor": 5000, "credits_currency": "USD"})
    check("total persisted", settings.credits_total_minor() == 5000)
    check("currency persisted", settings.credits_currency() == "USD")

    settings.save({"credits_total_minor": None})
    check("cleared total reads as None", settings.credits_total_minor() is None)

    print("\n=== 3. unknown keys are preserved ===")
    settings.save({"some_future_key": 42})
    settings.save({"credits_total_minor": 7000})
    import json
    raw = json.loads(path.read_text(encoding="utf-8"))
    check("unrelated key survives a later write", raw.get("some_future_key") == 42)

    print("\n=== 4. corrupt settings file degrades to defaults ===")
    path.write_text("{ not json", encoding="utf-8")
    check("no crash on corrupt file", settings.load() == settings.DEFAULTS,
          str(settings.load()))

    print("\n=== 5. credits row reflects settings ===")
    payload = {
        "limits": [{"kind": "session", "percent": 10,
                    "resets_at": "2026-08-11T00:00:00+00:00"}],
        "spend": {"enabled": True,
                  "used": {"amount_minor": 1200, "currency": "USD", "exponent": 2}},
    }
    settings.save({"credits_total_minor": None, "credits_currency": None})
    check("no total -> 'used' only", usage.parse(payload).credits_label == "$12.00 used",
          usage.parse(payload).credits_label)

    settings.save({"credits_total_minor": 5000})
    snap = usage.parse(payload)
    check("with total -> 'used / total'", snap.credits_label == "$12.00 / $50.00",
          snap.credits_label)
    check("bar percent computed", round(snap.credits_percent, 1) == 24.0,
          str(snap.credits_percent))

    print("\n=== 6. an API-provided cap wins over the local setting ===")
    with_cap = dict(payload)
    with_cap["spend"] = dict(payload["spend"])
    with_cap["spend"]["limit"] = {"amount_minor": 9000, "currency": "USD", "exponent": 2}
    check("uses the API's cap", usage.parse(with_cap).credits_label == "$12.00 / $90.00",
          usage.parse(with_cap).credits_label)

    print("\n=== 7. dialogs build without error ===")
    root = tk.Tk()
    root.withdraw()
    built = {"credits": False, "help": False}

    def build_and_close(fn, key):
        # Open on a timer, then close it immediately -- proves the widget tree
        # constructs on a real Tk root without blocking the test.
        root.after(300, lambda: [w.destroy() for w in root.winfo_children()
                                 if isinstance(w, tk.Toplevel)])
        try:
            fn()
            built[key] = True
        except Exception as exc:
            print(f"      error: {type(exc).__name__}: {exc}")

    build_and_close(lambda: dialogs.ask_credits_total(root, currency="USD"), "credits")
    check("credits dialog builds", built["credits"])

    build_and_close(lambda: dialogs.show_setup_help(root, "missing"), "help")
    check("setup-help dialog builds", built["help"])

    missing = dialogs.SETUP_HELP["missing"][1]
    expired = dialogs.SETUP_HELP["expired"][1]
    check("missing-login help says Anthropic's free tier can't work",
          "free Claude tier" in missing)
    # People were reading "paid plan" as "Claude Vitals costs money" and
    # bouncing. Every mention must name whose plan it is, and say this is free.
    check("missing-login help states the app itself is free",
          "Claude Vitals — this app is free" in missing or "this app is free" in missing)
    # `auth login` writes the credentials file. `setup-token` does NOT -- it
    # prints a long-lived token for use as an env var, so people who ran it
    # were left with the "can't find your login" dialog and no idea why.
    check("missing-login help gives the auth login command", "auth login" in missing)
    check("missing-login help warns against setup-token", "setup-token" in missing)
    # Anyone who only uses the desktop app has no `claude` on PATH, so the bare
    # command on its own would be a dead end for exactly the people who need it.
    check("missing-login help covers 'claude not recognised'",
          "not recognised" in missing and "claude-code" in missing)
    check("expired help gives the auth login command", "auth login" in expired)
    check("expired help covers 'claude not recognised'",
          "not recognised" in expired and "claude-code" in expired)

    root.destroy()

finally:
    if backup and backup.exists():
        shutil.copy2(backup, path)
        backup.unlink()
        print("\n(restored your settings.json)")
    elif backup is None and path.exists():
        path.unlink()

print("\n" + ("ALL PASSED" if all(results) else f"{results.count(False)} FAILED"))
sys.exit(0 if all(results) else 1)
