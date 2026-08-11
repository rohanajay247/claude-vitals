# Claude Vitals

**See how much Claude you have left, without leaving your conversation.**

<p align="center">
  <img src="docs/demo.gif" alt="The Claude Vitals overlay" width="420">
</p>

A small always-on-top card and a colour-coded tray icon showing your 5-hour
limit, weekly limit and credit spend. It never steals focus, so you can keep
typing while it updates.

**Free and open source.** "Paid plan" below means your Claude subscription with
Anthropic — not a charge for this app.

> Unofficial personal project, not affiliated with or endorsed by Anthropic. It
> reads an undocumented endpoint that could change at any time.

---

## Requirements

| | |
|---|---|
| **Price** | Free, MIT licence |
| **OS** | Windows 10 or 11 |
| **Claude plan** | A paid Anthropic plan — Pro, Max, Team, or API credits |
| **Won't work on** | Anthropic's free Claude tier |
| **Python** | 3.10 or newer |

---

## Install

**1.** Install [Python 3.10+](https://www.python.org/downloads/) — tick
**"Add python.exe to PATH"**.

**2.** Download this repo (green **Code** → **Download ZIP**) and unzip it
somewhere permanent.

**3.** Sign in to Claude once, so the app has a login to read. Open PowerShell
(from anywhere — this isn't related to the folder) and run:

```powershell
claude auth login
```

<details>
<summary>If that says <code>claude</code> is not recognised</summary>

Normal if you only use the Claude desktop app. It ships its own copy:

```powershell
& (Get-ChildItem "$env:APPDATA\Claude\claude-code\*\claude.exe" | Sort-Object FullName -Descending | Select-Object -First 1).FullName auth login
```

Check it worked with `claude auth status` — you want `"loggedIn": true`.
Don't use `claude setup-token`; it prints a token instead of saving a login.
</details>

**4.** Double-click **`setup.bat`** in the unzipped folder, then start Claude
Vitals from the Desktop icon.

If your account has usage credits, set your total once from the tray menu →
*Set usage credits total…*

---

## Using it

| Control | What it does |
|---|---|
| 🔒 **Lock** | Orange = always on top. Grey = other windows can cover it. |
| ⟳ **Refresh** | Check now instead of waiting for the 3-minute poll. |
| ✕ **Close** | Stops everything, including the tray icon. |

- **Lost it?** Left-click the tray icon to bring it forward.
- **Only one copy runs** — clicking the shortcut again surfaces the existing one.
- Drag it anywhere; it remembers where you put it.
- Right-click the tray icon for more: alerts, always-visible mode, start with
  Windows.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Can't find your Claude login" | Do step 3, or you're on the free tier (not supported). |
| "Your login expired" | Run `claude auth login` again. |
| `claude` is not recognised | Use the long command in step 3. |
| Tray shows a grey `–` | Can't reach the endpoint. Try *Refresh now*. |
| Card is off-screen | Delete `state/ui_state.json`. |

---

## Uninstall

Quit from the tray, then double-click **`uninstall.bat`** and delete the folder.
It removes shortcuts, the taskbar pin and saved state, and never touches your
Claude login.

---

## Privacy

- One request every 3 minutes, to `api.anthropic.com`. Nothing else leaves your
  machine — no server, no analytics, no third party.
- Your Claude login is read from disk per request, never copied, logged or
  printed.
- Everything it saves lives in this folder and can be deleted.

---

**[More detail →](docs/DETAILS.md)** — how it works, full privacy notes,
performance, running the tests, and the optional Claude Code status line.

[MIT](LICENSE) · unofficial, no warranty, may break without notice.
