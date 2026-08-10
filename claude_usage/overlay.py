"""The always-on-top usage strip.

Design goal: look like Anthropic shipped it. Dark card, muted grey label on the
left, value right-aligned, thin coloured fill bar under each row -- the same
visual language as Claude Code's usage panel -- plus a header carrying the
Claude mark, a refresh control and a close control.

The hard requirement is that this window NEVER takes focus. Three things
together guarantee that:

  1. WS_EX_NOACTIVATE on the window (win32.make_no_activate) -- Windows will not
     activate it even when clicked. This is also why clicking our own buttons
     does not pull the caret out of Claude's input box.
  2. Showing/raising goes through SetWindowPos with SWP_NOACTIVATE, never
     tkinter's lift() (which activates).
  3. overrideredirect(True) removes the title bar, so there is nothing to click
     that would normally raise-and-focus.

All layout is measured from real font metrics rather than hardcoded pixels;
hardcoding breaks at 125%/150%/200% display scaling.
"""

import math
import time
import tkinter as tk
import tkinter.font as tkfont

from . import cache, config, win32

PAD_X, PAD_Y = 14, 11
ROW_GAP = 10
BAR_HEIGHT = 3
TEXT_TO_BAR = 5
LABEL_GAP = 16
HINT_GAP = 8
HEADER_GAP = 9
MIN_WIDTH = 350

MARK_RADIUS = 8
MARK_SPOKES = 8

# "Peek": how we surface an unlocked overlay that has been buried. Simply
# raising it does not work -- Windows' foreground lock stops a non-foreground
# window climbing above the active one unless it activates, and activating is
# exactly what we must never do. So we pin it briefly instead and let go once
# the user has moved on.
PEEK_MIN_SECONDS = 1.5     # ignore foreground changes before this
PEEK_MAX_SECONDS = 20.0    # release regardless after this


class Overlay:
    def __init__(self, root, state, on_quit=None, on_refresh=None):
        self.root = root
        self.state = state
        self.on_quit = on_quit
        self.on_refresh = on_refresh

        self.hwnd = None
        self.visible = False
        self._drag_origin = None
        self._dragged = False
        self._hover = None
        self._phase = 0.0            # rotation of the Claude mark
        self._shown_pct = {}         # key -> animated value, eased toward target
        self._spin_until = 0.0       # extra-fast spin right after a refresh
        self._snapshot = None
        self._anim_job = None
        # Item handles for incremental animation. Rebuilding the whole canvas
        # every frame costs ~6% of a core; moving existing items costs almost
        # nothing, so a full _paint() only happens when the layout changes.
        self._sig = None
        self._mark_items = []
        self._mark_centre = (0.0, 0.0)
        self._bar_items = {}

        # Locked = always on top. Unlocked = normal z-order, so a fullscreen
        # video can cover it. Persisted, because it is a working preference.
        self.pinned = bool(cache.load_ui_state().get("pinned", True))
        self._peek_started = 0.0        # temporary on-top while unlocked
        self._peek_foreground = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)          # frameless
        self.win.attributes("-topmost", self.pinned)
        self.win.configure(bg=config.COL_BORDER)
        self.win.withdraw()                      # never flash on startup

        self.f_label = tkfont.Font(family="Segoe UI", size=9)
        self.f_value = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.f_hint = tkfont.Font(family="Segoe UI", size=8)
        self.f_title = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        self.f_btn = tkfont.Font(family="Segoe UI", size=11)
        self.line_height = max(
            self.f_label.metrics("linespace"),
            self.f_value.metrics("linespace"),
            self.f_hint.metrics("linespace"),
        )
        self.header_height = max(self.f_title.metrics("linespace"), MARK_RADIUS * 2 + 2)

        self.canvas = tk.Canvas(
            self.win, bg=config.COL_BG, highlightthickness=1,
            highlightbackground=config.COL_BORDER, bd=0,
            width=MIN_WIDTH, height=140,
        )
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)

        self._restore_position()
        self.win.update_idletasks()
        self._apply_no_activate()

    # --- window handle ---------------------------------------------------

    def _resolve_hwnd(self):
        """Top-level HWND for the Toplevel.

        For an overrideredirect window winfo_id() is usually already the
        top-level; when Tk has wrapped it, the real one is the parent.
        """
        if self.hwnd:
            return self.hwnd
        try:
            child = self.win.winfo_id()
            parent = win32.user32.GetParent(child)
            self.hwnd = parent if parent else child
        except Exception:
            self.hwnd = None
        return self.hwnd

    def _apply_no_activate(self):
        hwnd = self._resolve_hwnd()
        if hwnd:
            win32.make_no_activate(hwnd)

    # --- position --------------------------------------------------------

    def _restore_position(self):
        ui = cache.load_ui_state()
        x, y = ui.get("overlay_x"), ui.get("overlay_y")
        if isinstance(x, int) and isinstance(y, int) and self._on_screen(x, y):
            self.win.geometry(f"+{x}+{y}")
        else:
            screen_w = self.win.winfo_screenwidth()
            screen_h = self.win.winfo_screenheight()
            self.win.geometry(f"+{(screen_w - MIN_WIDTH) // 2}+{screen_h - 240}")

    def _on_screen(self, x, y):
        """Guard against a saved position on a monitor that no longer exists."""
        try:
            return (
                -3000 < x < self.win.winfo_screenwidth() + 3000
                and -3000 < y < self.win.winfo_screenheight() + 3000
            )
        except Exception:
            return False

    def _save_position(self):
        ui = cache.load_ui_state()
        ui["overlay_x"] = self.win.winfo_x()
        ui["overlay_y"] = self.win.winfo_y()
        cache.save_ui_state(ui)

    # --- interaction -----------------------------------------------------

    BUTTONS = ("btn_close", "btn_refresh", "btn_pin")

    def _hit(self, x, y):
        """Which control is under the cursor, if any."""
        for item in self.canvas.find_overlapping(x - 1, y - 1, x + 1, y + 1):
            for tag in self.canvas.gettags(item):
                if tag in self.BUTTONS:
                    return tag
        return None

    def _on_motion(self, event):
        hit = self._hit(event.x, event.y)
        if hit != self._hover:
            self._hover = hit
            self._paint()

    def _on_leave(self, _event):
        if self._hover is not None:
            self._hover = None
            self._paint()

    def _drag_start(self, event):
        # A press on a control is a click, not the start of a drag.
        if self._hit(event.x, event.y):
            self._drag_origin = None
            return
        self._dragged = False
        self._drag_origin = (event.x_root - self.win.winfo_x(),
                             event.y_root - self.win.winfo_y())

    def _drag_move(self, event):
        if not self._drag_origin:
            return
        self._dragged = True
        dx, dy = self._drag_origin
        self.win.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _drag_end(self, event):
        if self._drag_origin and self._dragged:
            self._drag_origin = None
            self._save_position()
            return
        self._drag_origin = None

        hit = self._hit(event.x, event.y)
        if hit == "btn_close" and self.on_quit:
            self.on_quit()
        elif hit == "btn_refresh" and self.on_refresh:
            self._spin_until = time.time() + 1.2   # visual feedback
            self.on_refresh()
        elif hit == "btn_pin":
            self.toggle_pin()

    # --- pinning ---------------------------------------------------------

    def toggle_pin(self):
        self.set_pinned(not self.pinned)

    def set_pinned(self, pinned):
        """Lock (always on top) or unlock (normal z-order)."""
        self.pinned = bool(pinned)
        # An explicit choice supersedes any peek in progress.
        self._peek_started = 0.0
        self._peek_foreground = None
        ui = cache.load_ui_state()
        ui["pinned"] = self.pinned
        cache.save_ui_state(ui)

        self._set_topmost(self.pinned)
        self._paint()

    def bring_to_front(self):
        """Surface the overlay when it has been buried while unlocked.

        Also un-hides it if the tray toggle had hidden it, so this single action
        always ends with the overlay on screen and visible.
        """
        self.state.overlay_enabled = True
        if not self.visible:
            self.show()
        hwnd = self._resolve_hwnd()
        if not hwnd:
            return
        if self.pinned:
            win32.show_no_activate(hwnd)
            return

        # Unlocked: start a peek. Promote-then-demote does not survive the
        # foreground lock, so hold it on top until the user moves on.
        # Tk's own -topmost attribute has to move too: it re-asserts itself on
        # the next geometry change and would quietly undo a bare SetWindowPos.
        self._set_topmost(True)
        self._peek_started = time.time()
        self._peek_foreground = win32.foreground_hwnd()

    def _set_topmost(self, on):
        """Apply topmost through both Tk and Win32 so they cannot disagree."""
        try:
            self.win.attributes("-topmost", bool(on))
        except Exception:
            pass
        hwnd = self._resolve_hwnd()
        if hwnd:
            win32.set_topmost(hwnd, bool(on))

    def update_peek(self, foreground_hwnd):
        """End a peek once the user switches windows, or after the cap.

        Called from the visibility tick, which already reads the foreground
        window, so this costs nothing extra.
        """
        if not self._peek_started or self.pinned:
            return
        elapsed = time.time() - self._peek_started
        moved_on = (foreground_hwnd and self._peek_foreground
                    and foreground_hwnd != self._peek_foreground)
        if (moved_on and elapsed >= PEEK_MIN_SECONDS) or elapsed >= PEEK_MAX_SECONDS:
            self._end_peek()

    def _end_peek(self):
        """Drop back to the normal z-order, leaving the lock setting alone."""
        was_peeking = bool(self._peek_started)
        self._peek_started = 0.0
        self._peek_foreground = None
        if was_peeking and not self.pinned:
            self._set_topmost(False)

    # --- visibility ------------------------------------------------------

    def show(self):
        """Show without stealing focus. Safe to call repeatedly."""
        hwnd = self._resolve_hwnd()
        first_show = not self.visible
        if first_show:
            self.win.deiconify()
            self._apply_no_activate()
            self.visible = True
            self._start_animation()
        if not hwnd:
            return
        if self.pinned:
            # Re-assert topmost every tick: another app going topmost can
            # otherwise cover us. SWP_NOACTIVATE keeps focus where it is.
            win32.show_no_activate(hwnd)
        elif first_show:
            # Unlocked: make it visible once, then leave the z-order alone so
            # other windows are free to cover it.
            win32.user32.ShowWindow(hwnd, win32.SW_SHOWNOACTIVATE)
            win32.set_topmost(hwnd, False)

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False
            self._stop_animation()

    # --- animation -------------------------------------------------------

    def _start_animation(self):
        if self._anim_job is None:
            self._animate()

    def _stop_animation(self):
        if self._anim_job is not None:
            try:
                self.root.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

    def _animate(self):
        """Advance the mark's rotation and ease the bars toward their targets."""
        self._anim_job = None
        if not self.visible or self.state.stop_event.is_set():
            return

        spinning = time.time() < self._spin_until
        speed = 3.0 if spinning else 0.45
        self._phase = (self._phase + speed * (1.0 / config.ANIM_FPS)) % (math.pi * 2)

        # Ease each bar toward its real value so changes glide rather than jump.
        moving = False
        for key, target in self._targets().items():
            current = self._shown_pct.get(key, 0.0)
            if abs(target - current) < 0.15:
                self._shown_pct[key] = target
            else:
                self._shown_pct[key] = current + (target - current) * config.BAR_EASING
                moving = True

        if self._layout_signature() != self._sig:
            self._paint()            # text or row set changed: full rebuild
        else:
            self._update_mark()      # cheap: move 8 lines
            if moving:
                self._update_bars()  # cheap: resize N rectangles

        rate = config.ANIM_FPS if (moving or spinning) else config.IDLE_FPS
        self._anim_job = self.root.after(int(1000 / rate), self._animate)

    def _targets(self):
        rows = self._row_specs(self._snapshot)
        return {row["key"]: (row["percent"] or 0.0) for row in rows}

    def _layout_signature(self):
        """Everything that would change the drawn text or the row set."""
        snapshot = self._snapshot
        if snapshot is None:
            return ("loading", self._hover, self.pinned)
        return (
            tuple((r["key"], r["label"], r["value"], r["hint"])
                  for r in self._row_specs(snapshot)),
            snapshot.stale,
            snapshot.error,
            self._hover,
            self.pinned,
        )

    def _update_mark(self):
        """Reposition the mark's spokes without rebuilding the canvas."""
        cx, cy = self._mark_centre
        for i, item in enumerate(self._mark_items):
            angle = self._phase + (math.pi * 2 / MARK_SPOKES) * i
            inner = MARK_RADIUS * 0.30
            outer = MARK_RADIUS * (1.0 if i % 2 == 0 else 0.66)
            try:
                self.canvas.coords(
                    item,
                    cx + math.cos(angle) * inner, cy + math.sin(angle) * inner,
                    cx + math.cos(angle) * outer, cy + math.sin(angle) * outer,
                )
            except Exception:
                return

    def _update_bars(self):
        for key, (item, x0, y0, x_max, y1) in self._bar_items.items():
            shown = self._shown_pct.get(key, 0.0)
            fraction = max(0.0, min(1.0, shown / 100.0))
            try:
                self.canvas.coords(item, x0, y0, x0 + (x_max - x0) * fraction, y1)
                self.canvas.itemconfigure(item, fill=config.colour_for(shown))
            except Exception:
                return

    # --- rendering -------------------------------------------------------

    def render(self, snapshot):
        """Take new data. Painting happens on the animation tick."""
        self._snapshot = snapshot
        if not self.visible:
            # Keep bars in sync while hidden so they do not animate from zero
            # every time the overlay is shown again.
            self._shown_pct.update(self._targets())
            self._paint()

    def _row_specs(self, snapshot):
        """Flatten a snapshot into the rows we draw, in order."""
        if not snapshot or not snapshot.limits:
            return []
        rows = [
            {
                "key": limit.key,
                "label": limit.label,
                "value": f"{limit.percent:.0f}%",
                "hint": limit.reset_hint(),
                "percent": limit.percent,
            }
            for limit in snapshot.limits
        ]
        if snapshot.credits_label:
            rows.append({
                "key": "credits",
                "label": "Usage credits",
                "value": snapshot.credits_label,
                "hint": "",
                "percent": snapshot.credits_percent,
            })
        return rows

    def _required_width(self, rows):
        """Widest row wins, so the hint can never overlap the label.

        Measured from real font metrics, which is what keeps this correct at
        125%/150%/200% display scaling.
        """
        widest = 0
        for row in rows:
            label_w = self.f_label.measure(row["label"])
            value_w = self.f_value.measure(row["value"])
            hint_w = self.f_hint.measure(row["hint"]) + HINT_GAP if row["hint"] else 0
            widest = max(widest, label_w + LABEL_GAP + hint_w + value_w)
        return max(MIN_WIDTH, widest + PAD_X * 2)

    def _paint(self):
        snapshot = self._snapshot
        canvas = self.canvas
        canvas.delete("all")
        self._mark_items = []
        self._bar_items = {}
        self._sig = self._layout_signature()

        rows = self._row_specs(snapshot)
        width = self._required_width(rows)
        y = PAD_Y

        y = self._draw_header(canvas, width, y, snapshot)
        y += HEADER_GAP

        if not rows:
            message = "Usage unavailable"
            if snapshot and snapshot.error:
                message = snapshot.error[:52]
            elif snapshot is None:
                message = "Loading…"
            canvas.create_text(PAD_X, y, anchor="nw", text=message,
                               fill=config.COL_LABEL, font=self.f_label)
            y += self.line_height
        else:
            for row in rows:
                y = self._draw_row(canvas, width, y, row)
                y += ROW_GAP
            y -= ROW_GAP

        if snapshot and snapshot.stale:
            y += 7
            canvas.create_text(
                PAD_X, y, anchor="nw",
                text=f"stale · {self._age(snapshot.fetched_at)} · retrying",
                fill=config.COL_STALE, font=self.f_hint,
            )
            y += self.f_hint.metrics("linespace")

        canvas.configure(width=width, height=y + PAD_Y)

    def _draw_header(self, canvas, width, y, snapshot):
        centre_y = y + self.header_height / 2
        right = width - PAD_X

        self._draw_mark(canvas, PAD_X + MARK_RADIUS, centre_y, snapshot)

        canvas.create_text(PAD_X + MARK_RADIUS * 2 + 8, centre_y, anchor="w",
                           text="Claude Vitals", fill=config.COL_TITLE, font=self.f_title)

        # Close, refresh, lock -- right to left. Drawn with a hover wash.
        close_x = right - 7
        self._draw_button(canvas, close_x, centre_y, "✕", "btn_close")
        self._draw_button(canvas, close_x - 23, centre_y, "⟳", "btn_refresh")
        self._draw_lock(canvas, close_x - 46, centre_y)

        y += self.header_height + 7
        canvas.create_line(PAD_X, y, right, y, fill=config.COL_BORDER)
        return y

    def _draw_button(self, canvas, cx, cy, glyph, tag):
        hovered = self._hover == tag
        if hovered:
            canvas.create_oval(cx - 10, cy - 10, cx + 10, cy + 10,
                               fill=config.COL_BG_HOVER, outline="", tags=(tag,))
        colour = config.COL_ACCENT if hovered else config.COL_LABEL
        canvas.create_text(cx, cy, text=glyph, fill=colour, font=self.f_btn, tags=(tag,))
        # Invisible generous hit area so the control is easy to click.
        canvas.create_rectangle(cx - 11, cy - 11, cx + 11, cy + 11,
                                outline="", fill="", tags=(tag,))

    def _draw_lock(self, canvas, cx, cy):
        """Padlock, drawn as vectors.

        Deliberately not an emoji or icon-font glyph: those render
        inconsistently across Windows font configurations, and a control that
        sometimes shows as a blank box is worse than a slightly plain one.
        Closed shackle = locked (always on top), open = unlocked.
        """
        tag = "btn_pin"
        hovered = self._hover == tag
        if hovered:
            canvas.create_oval(cx - 10, cy - 10, cx + 10, cy + 10,
                               fill=config.COL_BG_HOVER, outline="", tags=(tag,))

        colour = config.COL_ACCENT if self.pinned else config.COL_LABEL
        if hovered:
            colour = config.COL_ACCENT if not self.pinned else config.COL_VALUE

        # Body.
        canvas.create_rectangle(cx - 4, cy - 1, cx + 4, cy + 6,
                                outline=colour, fill=colour, tags=(tag,))
        # Shackle: centred and closed when locked, offset and open when not.
        if self.pinned:
            canvas.create_arc(cx - 3, cy - 7, cx + 3, cy + 1,
                              start=0, extent=180, style="arc",
                              outline=colour, width=1.6, tags=(tag,))
        else:
            canvas.create_arc(cx - 1, cy - 7, cx + 5, cy + 1,
                              start=20, extent=160, style="arc",
                              outline=colour, width=1.6, tags=(tag,))

        canvas.create_rectangle(cx - 11, cy - 11, cx + 11, cy + 11,
                                outline="", fill="", tags=(tag,))

    def _draw_mark(self, canvas, cx, cy, snapshot):
        """Anthropic-style radiating mark, slowly rotating.

        Doubles as a liveness indicator: it spins faster for a moment after a
        refresh, and goes grey when the data is stale.
        """
        colour = config.COL_STALE if (snapshot and snapshot.stale) else config.COL_ACCENT
        if snapshot is None:
            colour = config.COL_ACCENT_DIM

        self._mark_centre = (cx, cy)
        self._mark_items = []
        for i in range(MARK_SPOKES):
            angle = self._phase + (math.pi * 2 / MARK_SPOKES) * i
            # Alternate spoke lengths for the tapered look of the real mark.
            inner = MARK_RADIUS * 0.30
            outer = MARK_RADIUS * (1.0 if i % 2 == 0 else 0.66)
            self._mark_items.append(canvas.create_line(
                cx + math.cos(angle) * inner, cy + math.sin(angle) * inner,
                cx + math.cos(angle) * outer, cy + math.sin(angle) * outer,
                fill=colour, width=2, capstyle="round",
            ))

    def _draw_row(self, canvas, width, y, row):
        right = width - PAD_X
        # Common vertical centre so label, hint and value sit on one line
        # regardless of their differing font sizes.
        centre = y + self.line_height / 2
        percent = row["percent"]

        canvas.create_text(PAD_X, centre, anchor="w", text=row["label"],
                           fill=config.COL_LABEL, font=self.f_label)
        canvas.create_text(right, centre, anchor="e", text=row["value"],
                           fill=config.COL_VALUE, font=self.f_value)
        if row["hint"]:
            hint_right = right - self.f_value.measure(row["value"]) - HINT_GAP
            canvas.create_text(hint_right, centre + 1, anchor="e", text=row["hint"],
                               fill=config.COL_LABEL, font=self.f_hint)

        y += self.line_height + TEXT_TO_BAR

        if percent is not None:
            shown = self._shown_pct.get(row["key"], percent)
            fraction = max(0.0, min(1.0, shown / 100.0))
            canvas.create_rectangle(PAD_X, y, right, y + BAR_HEIGHT,
                                    fill=config.COL_TRACK, outline="")
            # Always create the fill rect (even at zero width) so the animation
            # tick has a stable handle to resize.
            item = canvas.create_rectangle(
                PAD_X, y, PAD_X + (right - PAD_X) * fraction, y + BAR_HEIGHT,
                fill=config.colour_for(shown), outline="",
            )
            self._bar_items[row["key"]] = (item, PAD_X, y, right, y + BAR_HEIGHT)
            y += BAR_HEIGHT
        return y

    @staticmethod
    def _age(fetched_at):
        if not fetched_at:
            return "unknown age"
        minutes = int((time.time() - fetched_at) // 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m old"
        return f"{minutes // 60}h old"
