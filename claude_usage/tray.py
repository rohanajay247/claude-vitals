"""System tray icon: dynamically drawn ring, tooltip, right-click menu, toasts.

The icon is redrawn from the current snapshot rather than loaded from disk, so
it always reflects live state: a coloured progress ring with the session
percentage in the middle, green/yellow/red by threshold, and a neutral grey dash
when usage is unavailable.
"""

import sys

import pystray
from PIL import Image, ImageDraw, ImageFont

from . import config, credentials, win32

# Windows renders the tray at 16-24px. Drawing at 4x and downsampling with
# LANCZOS gives clean antialiased edges; drawing at final size looks chunky and
# the digits turn to mush.
ICON_SIZE = 256
SUPERSAMPLE_TO = 64
RING_WIDTH = 26         # ~10% of size: thick enough to read at 16px
MARGIN = 6


def _font(size):
    for name in ("segoeuib.ttf", "seguisb.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fitted_font(draw, text, max_width):
    """Largest font size whose text fits the ring's inner circle."""
    for size in range(150, 60, -4):
        font = _font(size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
    return _font(60)


def draw_icon(percent, stale=False):
    """Render the tray image for a percentage (None -> unavailable)."""
    image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = MARGIN + RING_WIDTH // 2
    box = [inset, inset, ICON_SIZE - inset - 1, ICON_SIZE - inset - 1]

    # Filled disc behind the ring so the digits always have contrast, whatever
    # the taskbar colour happens to be.
    draw.ellipse([MARGIN, MARGIN, ICON_SIZE - MARGIN - 1, ICON_SIZE - MARGIN - 1],
                 fill="#1f1e1d")

    if percent is None:
        draw.ellipse(box, outline="#5a5751", width=RING_WIDTH)
        font = _font(110)
        draw.text((ICON_SIZE / 2, ICON_SIZE / 2 - 6), "–", font=font,
                  fill="#8f8b85", anchor="mm")
    else:
        draw.ellipse(box, outline=config.COL_TRACK, width=RING_WIDTH)
        colour = config.COL_STALE if stale else config.colour_for(percent)
        sweep = max(0.0, min(100.0, percent)) / 100.0 * 360.0
        if sweep > 0:
            # -90 so the ring starts at 12 o'clock and fills clockwise.
            draw.arc(box, start=-90, end=-90 + sweep, fill=colour, width=RING_WIDTH)

        text = f"{percent:.0f}"
        inner_width = ICON_SIZE - 2 * (inset + RING_WIDTH // 2) - 14
        font = _fitted_font(draw, text, inner_width)
        # anchor='mm' centres on the glyph box; nudge up slightly so the visual
        # weight sits centred inside the ring.
        draw.text((ICON_SIZE / 2, ICON_SIZE / 2 - 2), text, font=font,
                  fill="#f5f2ec", anchor="mm")

    return image.resize((SUPERSAMPLE_TO, SUPERSAMPLE_TO), Image.LANCZOS)


def draw_app_icon(size=256):
    """Static launcher/app icon: the Claude mark on a dark disc.

    Distinct from the tray icon, which shows a live percentage -- this one is
    for shortcuts, where there is no state to show.
    """
    import math

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size * 0.04
    draw.ellipse([margin, margin, size - margin, size - margin], fill="#232322")
    draw.ellipse([margin, margin, size - margin, size - margin],
                 outline=config.COL_BORDER, width=max(1, int(size * 0.02)))

    cx = cy = size / 2
    spokes, radius = 8, size * 0.30
    width = max(2, int(size * 0.055))
    for i in range(spokes):
        angle = (math.pi * 2 / spokes) * i - math.pi / 2
        inner = radius * 0.28
        outer = radius * (1.0 if i % 2 == 0 else 0.66)
        draw.line(
            [cx + math.cos(angle) * inner, cy + math.sin(angle) * inner,
             cx + math.cos(angle) * outer, cy + math.sin(angle) * outer],
            fill=config.COL_ACCENT, width=width,
        )
    return image


def write_ico(path):
    """Write a multi-resolution .ico for shortcuts. Returns the path."""
    icon = draw_app_icon(256)
    path.parent.mkdir(parents=True, exist_ok=True)
    icon.save(path, format="ICO",
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
    return path


def build_tooltip(snapshot):
    """Hover text: session % + countdown, weekly % + countdown."""
    if snapshot is None:
        return "Claude Vitals — starting…"
    if not snapshot.limits:
        return f"Claude Vitals — unavailable\n{(snapshot.error or '')[:60]}"

    lines = []
    for limit in snapshot.limits:
        countdown = limit.countdown()
        suffix = f" · resets in {countdown}" if countdown else ""
        lines.append(f"{limit.label}: {limit.percent:.0f}%{suffix}")
    if snapshot.credits_label:
        lines.append(f"Usage credits: {snapshot.credits_label}")
    if snapshot.stale:
        lines.append("(stale — last known values)")
    # Windows truncates tooltips around 127 chars; keep it tight.
    return "\n".join(lines)[:127]


class Tray:
    def __init__(self, state, on_refresh, on_quit, on_toggle_overlay,
                 on_toggle_always, restart_args=None,
                 on_bring_to_front=None, on_toggle_pin=None, is_pinned=None,
                 on_set_credits=None):
        self.state = state
        self.on_refresh = on_refresh
        self.on_quit = on_quit
        self.on_toggle_overlay = on_toggle_overlay
        self.on_toggle_always = on_toggle_always
        self.on_bring_to_front = on_bring_to_front
        self.on_toggle_pin = on_toggle_pin
        self.is_pinned = is_pinned or (lambda: True)
        self.on_set_credits = on_set_credits
        self.restart_args = restart_args or ""

        self.icon = pystray.Icon(
            "claude-vitals",
            icon=draw_icon(None),
            title="Claude Vitals — starting…",
            menu=self._menu(),
        )

    # --- menu ------------------------------------------------------------

    def _menu(self):
        return pystray.Menu(
            # default=True makes this the left-click action on the tray icon,
            # which is how you recover the overlay when it is unlocked and has
            # been buried under a fullscreen window.
            pystray.MenuItem("Bring overlay to front", self._bring_to_front,
                             default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Refresh now", self._refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Lock on top",
                self._toggle_pin,
                checked=lambda _: self.is_pinned(),
            ),
            pystray.MenuItem(
                "Show overlay",
                self._toggle_overlay,
                checked=lambda _: self.state.overlay_enabled,
            ),
            pystray.MenuItem(
                "Usage alerts (80% / 95%)",
                self._toggle_notifications,
                checked=lambda _: self.state.notifications_enabled,
            ),
            pystray.MenuItem(
                "Always visible",
                self._toggle_always,
                checked=lambda _: self.state.always_visible,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Set usage credits total…", self._set_credits),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with Windows",
                self._toggle_startup,
                checked=lambda _: win32.startup_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _refresh(self, *_):
        self.on_refresh()

    def _bring_to_front(self, *_):
        if self.on_bring_to_front:
            self.on_bring_to_front()

    def _toggle_pin(self, *_):
        if self.on_toggle_pin:
            self.on_toggle_pin()

    def _set_credits(self, *_):
        if self.on_set_credits:
            self.on_set_credits()

    def _toggle_notifications(self, *_):
        self.state.notifications_enabled = not self.state.notifications_enabled
        self.state.persist_notifications()

    def _toggle_overlay(self, *_):
        self.state.overlay_enabled = not self.state.overlay_enabled
        self.on_toggle_overlay(self.state.overlay_enabled)

    def _toggle_always(self, *_):
        self.state.always_visible = not self.state.always_visible
        self.on_toggle_always(self.state.always_visible)

    def _toggle_startup(self, *_):
        enable = not win32.startup_enabled()
        # pythonw.exe + our entry script, so nothing flashes a console at login.
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        win32.set_startup(enable, target=pythonw, args=self.restart_args)

    def _quit(self, *_):
        self.on_quit()
        try:
            self.icon.stop()
        except Exception:
            pass

    # --- updates ---------------------------------------------------------

    def update(self, snapshot):
        """Redraw icon + tooltip. Called from the poll thread."""
        try:
            percent = snapshot.headline if snapshot else None
            stale = bool(snapshot and snapshot.stale)
            self.icon.icon = draw_icon(percent, stale=stale)
            self.icon.title = build_tooltip(snapshot)
        except Exception:
            pass

    def notify(self, title, message=""):
        """Windows toast via the tray icon -- no extra dependency needed."""
        try:
            self.icon.notify(message or " ", title)
        except Exception:
            pass

    def run(self):
        self.icon.run()

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass
