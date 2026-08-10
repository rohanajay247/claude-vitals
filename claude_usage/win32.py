"""Win32 glue: foreground detection, focus-safe windows, toasts, startup shortcut.

The focus-safe window handling here is the load-bearing part of the overlay. An
always-on-top strip that steals focus while you are typing in Claude is worse
than no strip at all, so every path that shows or raises the window goes through
`show_no_activate()` -- never `lift()`, never `focus_force()`.
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys

from . import config

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- constants -----------------------------------------------------------
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000   # window never takes foreground activation
WS_EX_TOOLWINDOW = 0x00000080   # keep it out of Alt-Tab and the taskbar
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

SW_SHOWNOACTIVATE = 4
SW_HIDE = 0

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL

# SetWindowLongPtr only exists on 64-bit; 32-bit Python exposes SetWindowLongW.
if hasattr(user32, "SetWindowLongPtrW"):
    _set_long = user32.SetWindowLongPtrW
    _get_long = user32.GetWindowLongPtrW
    _set_long.restype = ctypes.c_longlong
    _get_long.restype = ctypes.c_longlong
    _set_long.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_longlong]
    _get_long.argtypes = [wt.HWND, ctypes.c_int]
else:  # pragma: no cover - 32-bit fallback
    _set_long = user32.SetWindowLongW
    _get_long = user32.GetWindowLongW


# --- foreground detection ------------------------------------------------

def foreground_process_name():
    """Process image name of whatever window currently has focus.

    Returns a lowercase basename such as 'claude.exe', or None when the
    foreground window belongs to a process we are not allowed to open (elevated
    apps, some system UI). None is treated as 'not Claude' by callers.
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return None
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def foreground_hwnd():
    return user32.GetForegroundWindow()


def is_claude_foreground(extra_hwnds=()):
    """True when the Claude desktop app owns the foreground window.

    Our own overlay counts as 'still Claude' -- otherwise clicking or dragging
    the strip would hide the very thing being dragged.
    """
    hwnd = user32.GetForegroundWindow()
    if hwnd and hwnd in extra_hwnds:
        return True
    name = foreground_process_name()
    return name in config.CLAUDE_PROCESS_NAMES


# --- focus-safe window handling -----------------------------------------

def make_no_activate(hwnd):
    """Mark a window as never-activate + tool-window.

    WS_EX_NOACTIVATE is what actually prevents the focus theft: Windows will not
    hand this window the foreground even when it is clicked. WS_EX_TOOLWINDOW
    additionally keeps it out of Alt-Tab and off the taskbar.
    """
    try:
        style = _get_long(hwnd, GWL_EXSTYLE)
        _set_long(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        return True
    except Exception:
        return False


def show_no_activate(hwnd):
    """Show and raise to topmost WITHOUT taking focus.

    SWP_NOACTIVATE is the critical flag. Using tkinter's lift() here instead
    would activate the window and yank the caret out of Claude's input box.
    """
    try:
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        return True
    except Exception:
        return False


def set_topmost(hwnd, enabled):
    """Pin the window above everything, or release it into the normal z-order.

    Released ("unlocked") means a fullscreen video can cover it -- which is the
    point. SWP_NOACTIVATE on both paths so neither transition touches focus.
    """
    try:
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST if enabled else HWND_NOTOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        return True
    except Exception:
        return False


def raise_without_activating(hwnd):
    """Pull a window to the top of the z-order WITHOUT making it stay there.

    Used by 'Bring to front' when the overlay is unlocked and has been buried:
    promote to topmost, then immediately demote. The window ends up drawn above
    its peers but keeps normal stacking behaviour from then on, and never takes
    focus.
    """
    try:
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        return True
    except Exception:
        return False


# Explicit application identity. Without this, Windows treats the process as
# generic "Python", which has two visible consequences: shortcuts pointing at
# pythonw.exe cannot be pinned to the taskbar as their own app, and toast
# notifications are attributed to "Python" rather than to us.
APP_USER_MODEL_ID = "ClaudeVitals.UsageOverlay"


def set_app_user_model_id(app_id=APP_USER_MODEL_ID):
    """Declare our own app identity. Call before creating any window."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        return True
    except Exception:
        return False


# --- single instance ------------------------------------------------------
# Without this, every click on a pinned taskbar icon starts another copy: more
# tray icons, more poll loops hammering the endpoint (which shows up as `stale`
# once the server starts refusing them), and -- worst case -- two instances
# renewing the same OAuth token at once. Refresh tokens rotate, so the first
# renewal invalidates the token the second is still holding, and the loser can
# write credentials that no longer work.

MUTEX_NAME = "Local\\ClaudeVitals.SingleInstance"
SHOW_EVENT_NAME = "Local\\ClaudeVitals.ShowOverlay"

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
EVENT_MODIFY_STATE = 0x0002

kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.OpenEventW.restype = wt.HANDLE
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]


def acquire_single_instance():
    """Claim the single-instance lock.

    Returns a handle when this process is the first, or None when another
    instance already holds it. Keep the handle for the lifetime of the process.
    Windows frees the mutex when the process ends -- even on a crash -- so a
    stale lock can never leave the app permanently unstartable.
    """
    try:
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return True          # cannot lock; better to run than to refuse
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception:
        return True              # never let the guard itself block startup


def release_single_instance(handle):
    try:
        if isinstance(handle, int):
            kernel32.CloseHandle(handle)
    except Exception:
        pass


def signal_existing_instance():
    """Ask the instance already running to surface its overlay."""
    try:
        handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
        if not handle:
            return False
        kernel32.SetEvent(handle)
        kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def create_show_event():
    """Auto-reset event the running instance waits on. None if unavailable."""
    try:
        return kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME) or None
    except Exception:
        return None


def wait_show_event(handle, timeout_ms=500):
    """True when another launch asked us to surface.

    Times out rather than blocking forever so the waiting thread can notice the
    app is shutting down and exit cleanly.
    """
    try:
        return kernel32.WaitForSingleObject(handle, timeout_ms) == WAIT_OBJECT_0
    except Exception:
        return False


def restore_foreground(hwnd):
    """Hand the foreground back to a window we displaced.

    WS_EX_NOACTIVATE stops the overlay being activated by a click or a show,
    but it does not stop Windows granting foreground to a freshly launched
    process when it creates its first window. So at startup we may briefly hold
    the foreground; this gives it straight back. A process that currently owns
    the foreground is always permitted to give it away.
    """
    try:
        if hwnd and user32.IsWindow(hwnd):
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def hide_window(hwnd):
    try:
        user32.ShowWindow(hwnd, SW_HIDE)
        return True
    except Exception:
        return False


# --- start with Windows --------------------------------------------------

def startup_shortcut_path():
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(
        appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
        "Claude Vitals.lnk",
    )


def startup_enabled():
    return os.path.exists(startup_shortcut_path())


def set_startup(enabled, target=None, args=""):
    """Create or remove a Startup-folder shortcut.

    A plain .lnk rather than a registry Run key or scheduled task, precisely so
    it is trivial to undo -- delete the file from shell:startup.
    """
    path = startup_shortcut_path()
    if not enabled:
        try:
            if os.path.exists(path):
                os.remove(path)
            return True
        except OSError:
            return False

    try:
        from win32com.client import Dispatch
    except ImportError:
        return False

    # pythonw.exe so no console window flashes at login.
    target = target or os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    try:
        shell = Dispatch("WScript.Shell")
        link = shell.CreateShortCut(path)
        link.Targetpath = target
        link.Arguments = args
        link.WorkingDirectory = str(config.PROJECT_DIR)
        link.Description = "Claude Vitals - Claude usage tray + overlay"
        link.save()
        return True
    except Exception:
        return False
