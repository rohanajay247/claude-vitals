"""Claude Vitals entry point.

    .venv\\Scripts\\pythonw.exe run.pyw     (silent, normal use)
    .venv\\Scripts\\python.exe  run.pyw     (with console, for debugging)

The version check runs before importing anything from the package: several
modules use `X | None` type annotations that are evaluated at import time, so on
Python 3.9 the app would otherwise die with a confusing TypeError instead of
telling you what is actually wrong.
"""

import sys
from pathlib import Path

MIN_PYTHON = (3, 10)

if sys.version_info < MIN_PYTHON:
    message = (
        f"Claude Vitals needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.\n"
        f"You are running {sys.version.split()[0]} from:\n  {sys.executable}\n\n"
        "Install a newer Python from python.org, then run setup.bat again."
    )
    try:                       # GUI first: launched from a shortcut there is no console
        import tkinter.messagebox as mb
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        mb.showerror("Claude Vitals", message)
    except Exception:
        print(message)
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_usage.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
