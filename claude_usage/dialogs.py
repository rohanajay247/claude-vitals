"""Small settings dialogs, so configuration never requires editing code.

These are the only windows in the app that intentionally take focus -- the user
opened them, so they should be able to type into them. Everything else in
Claude Vitals is deliberately focus-safe; see overlay.py.
"""

import tkinter as tk

from . import config, settings

SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}


def _parse_amount(text):
    """'50', '50.00', '$50', '1,234.50' -> minor units.

    An empty box means "clear the setting" and returns None. Text that contains
    something but no usable number is an error, NOT a clear -- otherwise a typo
    would silently wipe the total the user had already set.
    """
    raw = str(text).strip()
    if not raw:
        return None
    if "-" in raw:
        # Stripping the sign would silently turn "-5" into 5.00.
        raise ValueError("Enter a positive amount")

    cleaned = "".join(ch for ch in raw if ch.isdigit() or ch in ".,")
    cleaned = cleaned.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        raise ValueError("Enter a number, for example 50 or 50.00")
    if value <= 0:
        raise ValueError("Enter an amount greater than zero")
    return int(round(value * 100))


SETUP_HELP = {
    "missing": (
        "Claude Vitals can't find your Claude login",
        "It reads your usage using the login stored at\n"
        "%USERPROFILE%\\.claude\\.credentials.json — and that file isn't there.\n\n"
        "If you're on a paid plan, sign in once. Open PowerShell and run:\n\n"
        "        claude setup-token\n\n"
        "If that says 'claude' is not recognised — which it will if you only\n"
        "use the Claude desktop app — the app ships its own copy. Run this\n"
        "instead (it finds whichever version you have):\n\n"
        "        & (Get-ChildItem \"$env:APPDATA\\Claude\\claude-code\\*\\claude.exe\"\n"
        "          | Sort-Object FullName -Descending\n"
        "          | Select-Object -First 1).FullName setup-token\n\n"
        "Then start Claude Vitals again. You don't have to use Claude Code\n"
        "afterwards — that's just where the login gets stored.\n\n"
        "On the free plan this won't work: signing in this way needs a\n"
        "subscription, and so does Claude Vitals. Sorry!"
    ),
    "expired": (
        "Your Claude login has expired",
        "Claude Vitals found your login but Anthropic rejected it, and renewing\n"
        "it automatically didn't work either.\n\n"
        "This happens if the login hasn't been renewed for a few weeks. The\n"
        "Claude desktop app signs in separately and doesn't refresh this file.\n\n"
        "To fix it, open PowerShell and run:\n\n"
        "        claude setup-token\n\n"
        "If 'claude' is not recognised, use the copy the desktop app ships:\n\n"
        "        & (Get-ChildItem \"$env:APPDATA\\Claude\\claude-code\\*\\claude.exe\"\n"
        "          | Sort-Object FullName -Descending\n"
        "          | Select-Object -First 1).FullName setup-token\n\n"
        "Claude Vitals will pick up the new login by itself — no restart needed."
    ),
}


def show_setup_help(root, kind="missing"):
    """Explain, in plain language, why there are no numbers to show."""
    title, body = SETUP_HELP.get(kind, SETUP_HELP["missing"])

    win = tk.Toplevel(root)
    win.title("Claude Vitals")
    win.configure(bg=config.COL_BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)

    wrap = tk.Frame(win, bg=config.COL_BG, padx=20, pady=18)
    wrap.pack(fill="both", expand=True)

    tk.Label(wrap, text=title, bg=config.COL_BG, fg=config.COL_VALUE,
             font=("Segoe UI", 12, "bold"), justify="left").pack(anchor="w")
    tk.Label(wrap, text=body, bg=config.COL_BG, fg=config.COL_LABEL,
             font=("Segoe UI", 9), justify="left").pack(anchor="w", pady=(10, 16))

    tk.Button(wrap, text="OK", command=win.destroy, relief="flat", bd=0,
              padx=20, pady=5, cursor="hand2", bg=config.COL_ACCENT, fg="#ffffff",
              activebackground=config.COL_ACCENT, activeforeground="#ffffff",
              font=("Segoe UI", 9, "bold")).pack(anchor="e")

    win.bind("<Return>", lambda _e: win.destroy())
    win.bind("<Escape>", lambda _e: win.destroy())

    win.update_idletasks()
    win.geometry(f"+{(win.winfo_screenwidth() - win.winfo_width()) // 2}"
                 f"+{(win.winfo_screenheight() - win.winfo_height()) // 3}")
    win.grab_set()
    root.wait_window(win)


def ask_credits_total(root, currency=None):
    """Ask for the total granted usage credits. Runs on the Tk thread."""
    current = settings.credits_total_minor()
    symbol = SYMBOLS.get(currency or settings.credits_currency() or "", "")

    win = tk.Toplevel(root)
    win.title("Usage credits")
    win.configure(bg=config.COL_BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)

    wrap = tk.Frame(win, bg=config.COL_BG, padx=18, pady=16)
    wrap.pack(fill="both", expand=True)

    def label(text, size, colour, pady=(0, 0), bold=False):
        tk.Label(wrap, text=text, bg=config.COL_BG, fg=colour, justify="left",
                 wraplength=340,
                 font=("Segoe UI", size, "bold" if bold else "normal")).pack(
            anchor="w", pady=pady)

    label("Total usage credits", 11, config.COL_VALUE, bold=True)
    label("Claude does not report your credit balance, so enter the total you "
          "were granted. Find it in Claude under Settings → Usage: add the "
          "amount spent to your current balance.", 9, config.COL_LABEL, (6, 10))

    row = tk.Frame(wrap, bg=config.COL_BG)
    row.pack(fill="x")
    if symbol:
        tk.Label(row, text=symbol, bg=config.COL_BG, fg=config.COL_VALUE,
                 font=("Segoe UI", 12)).pack(side="left", padx=(0, 6))

    var = tk.StringVar(value=f"{current / 100:.2f}" if current else "")
    entry = tk.Entry(row, textvariable=var, width=14, justify="left",
                     bg="#2e2d2b", fg=config.COL_VALUE, insertbackground=config.COL_VALUE,
                     relief="flat", font=("Segoe UI", 12))
    entry.pack(side="left", ipady=4, fill="x", expand=True)

    error = tk.Label(wrap, text="", bg=config.COL_BG, fg=config.COL_RED,
                     font=("Segoe UI", 9))
    error.pack(anchor="w", pady=(6, 0))

    label("Leave blank to just show the amount spent, with no bar.",
          8, config.COL_LABEL, (4, 12))

    result = {"saved": False}

    def on_save(_event=None):
        try:
            minor = _parse_amount(var.get())
        except ValueError as exc:
            error.configure(text=str(exc))
            return
        settings.save({
            "credits_total_minor": minor,
            "credits_currency": currency or settings.credits_currency(),
        })
        result["saved"] = True
        win.destroy()

    buttons = tk.Frame(wrap, bg=config.COL_BG)
    buttons.pack(fill="x")

    def button(parent, text, command, accent=False):
        b = tk.Button(parent, text=text, command=command, relief="flat", bd=0,
                      padx=16, pady=5, cursor="hand2",
                      bg=config.COL_ACCENT if accent else "#2e2d2b",
                      fg="#ffffff" if accent else config.COL_VALUE,
                      activebackground=config.COL_ACCENT if accent else "#3a3936",
                      activeforeground="#ffffff",
                      font=("Segoe UI", 9, "bold" if accent else "normal"))
        return b

    button(buttons, "Save", on_save, accent=True).pack(side="right")
    button(buttons, "Cancel", win.destroy).pack(side="right", padx=(0, 8))

    win.bind("<Return>", on_save)
    win.bind("<Escape>", lambda _e: win.destroy())

    # Centre on screen, then hand focus to the field.
    win.update_idletasks()
    x = (win.winfo_screenwidth() - win.winfo_width()) // 2
    y = (win.winfo_screenheight() - win.winfo_height()) // 3
    win.geometry(f"+{x}+{y}")
    entry.focus_set()
    entry.select_range(0, "end")

    win.grab_set()
    root.wait_window(win)
    return result["saved"]
