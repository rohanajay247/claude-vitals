"""Generate the diagrams used in the Claude Vitals documentation.

    .venv\\Scripts\\python.exe docs\\make_diagrams.py

Writes PNGs into docs/. Drawn with Pillow (already a dependency) rather than a
charting library, so the docs need no extra tooling to rebuild.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DOCS = Path(__file__).resolve().parent
SCALE = 2                      # supersample, then downscale for crisp edges

INK = "#1f1e1d"
MUTED = "#6b6862"
LINE = "#c9c5be"
ACCENT = "#d97757"
GREEN = "#4a9d6d"
AMBER = "#c99a3f"
RED = "#c05a4d"
BG = "#ffffff"
FILL_SOFT = "#faf7f2"
FILL_ACCENT = "#fbeee7"


def font(size, bold=False):
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(name, size * SCALE)
        except OSError:
            continue
    return ImageFont.load_default()


def canvas(w, h):
    img = Image.new("RGB", (w * SCALE, h * SCALE), BG)
    return img, ImageDraw.Draw(img)


def box(d, xy, fill=FILL_SOFT, outline=LINE, width=2, radius=10):
    x0, y0, x1, y1 = [v * SCALE for v in xy]
    d.rounded_rectangle([x0, y0, x1, y1], radius=radius * SCALE,
                        fill=fill, outline=outline, width=width * SCALE)


def text(d, xy, s, size=13, bold=False, fill=INK, anchor="mm", spacing=4):
    d.multiline_text((xy[0] * SCALE, xy[1] * SCALE), s, font=font(size, bold),
                     fill=fill, anchor=anchor, align="center",
                     spacing=spacing * SCALE)


def ltext(d, xy, s, size=13, bold=False, fill=INK, spacing=4):
    d.multiline_text((xy[0] * SCALE, xy[1] * SCALE), s, font=font(size, bold),
                     fill=fill, anchor="lm", align="left", spacing=spacing * SCALE)


def arrow(d, start, end, colour=MUTED, width=2, head=7):
    import math
    x0, y0 = [v * SCALE for v in start]
    x1, y1 = [v * SCALE for v in end]
    d.line([x0, y0, x1, y1], fill=colour, width=width * SCALE)
    ang = math.atan2(y1 - y0, x1 - x0)
    h = head * SCALE
    for delta in (2.6, -2.6):
        d.line([x1, y1,
                x1 + h * math.cos(ang + delta),
                y1 + h * math.sin(ang + delta)], fill=colour, width=width * SCALE)


def save(img, name):
    img = img.resize((img.width // SCALE, img.height // SCALE), Image.LANCZOS)
    out = DOCS / name
    # These are flat-colour diagrams -- a 64-colour palette is visually
    # identical and about 70% smaller, which matters because images are the
    # bulk of what anyone clones.
    img.convert("RGB").quantize(colors=64, method=Image.MEDIANCUT).save(
        out, optimize=True)
    print(f"  wrote {out.name}  ({img.width}x{img.height}, {out.stat().st_size // 1024} KB)")
    return out


# --------------------------------------------------------------------------
# 1. User flow
# --------------------------------------------------------------------------
def diagram_user_flow():
    img, d = canvas(1000, 300)
    text(d, (500, 28), "Everyday use", 17, bold=True)

    steps = [
        ("1. Start it", "Double-click\nClaude Vitals", 90),
        ("2. It appears", "Tray ring +\noverlay on screen", 330),
        ("3. Work", "Updates itself\nevery 3 minutes", 570),
        ("4. Stop it", "Click  X  on the\noverlay", 810),
    ]
    for title, body, x in steps:
        box(d, (x, 70, x + 150, 175), fill=FILL_SOFT)
        text(d, (x + 75, 95), title, 13, bold=True, fill=ACCENT)
        text(d, (x + 75, 135), body, 12, fill=INK)

    for x in (240, 480, 720):
        arrow(d, (x, 122), (x + 85, 122))

    box(d, (90, 210, 910, 275), fill=FILL_ACCENT, outline=ACCENT)
    text(d, (500, 228), "Can't see it? Left-click the tray icon to bring it back.",
         12, bold=True, fill=INK)
    text(d, (500, 254),
         "Closing with  X  stops everything, including the tray icon — start it again from the Desktop shortcut.",
         11, fill=MUTED)
    return save(img, "diagram-user-flow.png")


# --------------------------------------------------------------------------
# 2. Architecture
# --------------------------------------------------------------------------
def diagram_architecture():
    img, d = canvas(1000, 510)
    text(d, (500, 28), "How the pieces fit together", 17, bold=True)

    # Cloud / API
    box(d, (330, 60, 670, 120), fill=FILL_ACCENT, outline=ACCENT)
    text(d, (500, 80), "Anthropic usage endpoint", 13, bold=True)
    text(d, (500, 103), "api.anthropic.com  ·  unofficial", 11, fill=MUTED)

    # Process container
    box(d, (60, 165, 940, 345), fill="#ffffff", outline=LINE)
    ltext(d, (80, 185), "Claude Vitals — one program, three parts running at once",
          12, bold=True, fill=MUTED)

    # Threads
    box(d, (90, 210, 320, 320), fill=FILL_SOFT)
    text(d, (205, 232), "Fetcher", 13, bold=True, fill=ACCENT)
    text(d, (205, 272), "Asks the endpoint\nfor your usage\nevery 3 minutes", 11)

    box(d, (385, 210, 615, 320), fill=FILL_SOFT)
    text(d, (500, 232), "Shared memory", 13, bold=True, fill=ACCENT)
    text(d, (500, 272), "Holds the latest\nnumbers everyone\nelse reads", 11)

    box(d, (680, 210, 910, 320), fill=FILL_SOFT)
    text(d, (795, 232), "Tray + overlay", 13, bold=True, fill=ACCENT)
    text(d, (795, 272), "Draws the ring icon\nand the on-screen\ncard", 11)

    arrow(d, (500, 122), (500, 163), colour=ACCENT)
    arrow(d, (320, 265), (383, 265))
    arrow(d, (615, 265), (678, 265))
    text(d, (352, 248), "writes", 10, fill=MUTED)
    text(d, (647, 248), "reads", 10, fill=MUTED)

    # Disk
    box(d, (330, 400, 670, 480), fill=FILL_SOFT)
    text(d, (500, 422), "Files on your laptop", 13, bold=True)
    text(d, (500, 452), "last known numbers  ·  window position\nyour preferences", 11, fill=MUTED)
    arrow(d, (420, 347), (420, 398))
    arrow(d, (580, 398), (580, 347))
    text(d, (386, 372), "save", 10, fill=MUTED)
    text(d, (616, 372), "load", 10, fill=MUTED)

    # Credentials note
    box(d, (60, 60, 300, 120), fill=FILL_SOFT)
    text(d, (180, 80), "Your Claude login", 12, bold=True)
    text(d, (180, 102), "read fresh each time,\nnever copied or stored", 10, fill=MUTED)
    arrow(d, (300, 90), (328, 90))
    return save(img, "diagram-architecture.png")


# --------------------------------------------------------------------------
# 3. What happens when it can't reach the endpoint
# --------------------------------------------------------------------------
def diagram_failure():
    img, d = canvas(1000, 470)
    text(d, (500, 28), "What happens if it can't get the numbers", 17, bold=True)

    box(d, (390, 65, 610, 115), fill=FILL_SOFT)
    text(d, (500, 90), "Ask for usage", 13, bold=True)

    # Success branch
    box(d, (80, 175, 330, 250), fill="#eef7f1", outline=GREEN)
    text(d, (205, 197), "Worked", 13, bold=True, fill=GREEN)
    text(d, (205, 226), "Show fresh numbers,\nsave a copy", 11)
    arrow(d, (430, 117), (250, 172), colour=GREEN)
    text(d, (300, 138), "yes", 11, fill=GREEN)

    # Login expired branch
    box(d, (375, 175, 625, 250), fill="#fdf6ea", outline=AMBER)
    text(d, (500, 197), "Login expired", 13, bold=True, fill="#9a7429")
    text(d, (500, 226), "Renew it automatically,\nthen try once more", 11)
    arrow(d, (500, 117), (500, 172), colour=AMBER)

    # Failure branch
    box(d, (670, 175, 920, 250), fill="#fbeeec", outline=RED)
    text(d, (795, 197), "Still no answer", 13, bold=True, fill=RED)
    text(d, (795, 226), "Show the last known\nnumbers, marked stale", 11)
    arrow(d, (570, 117), (750, 172), colour=RED)
    text(d, (688, 138), "no", 11, fill=RED)

    # Retry
    box(d, (670, 295, 920, 360), fill=FILL_SOFT)
    text(d, (795, 315), "Wait, then retry", 12, bold=True)
    text(d, (795, 340), "30s, 1m, 2m … up to 15m", 11, fill=MUTED)
    arrow(d, (795, 252), (795, 293), colour=RED)

    box(d, (80, 395, 920, 450), fill=FILL_ACCENT, outline=ACCENT)
    text(d, (500, 412), "It never crashes and never floods the server with requests.", 12, bold=True)
    text(d, (500, 435),
         "You always see a number — the word \"stale\" tells you it is the last known one, not a live one.",
         11, fill=MUTED)
    return save(img, "diagram-failure.png")


# --------------------------------------------------------------------------
# 4. Overlay anatomy (annotated real screenshot)
# --------------------------------------------------------------------------
def diagram_anatomy():
    shot_path = DOCS / "overlay.png"
    if not shot_path.exists():
        print("  (skipped anatomy: docs/overlay.png missing)")
        return None

    shot = Image.open(shot_path).convert("RGB")
    sw, sh = shot.size
    img, d = canvas(1000, 375)
    text(d, (500, 26), "The overlay, explained", 17, bold=True)

    ox, oy = 300, 70
    img.paste(shot.resize((sw * SCALE, sh * SCALE), Image.LANCZOS), (ox * SCALE, oy * SCALE))
    d.rectangle([ox * SCALE, oy * SCALE, (ox + sw) * SCALE, (oy + sh) * SCALE],
                outline=LINE, width=2 * SCALE)

    labels_left = [
        ("Name and spinning mark", "it turns while the app is alive", oy + 22),
        ("Your 5-hour allowance", "with the time it resets", oy + 72),
        ("Your weekly allowance", "across all models", oy + 118),
    ]
    for title, sub, y in labels_left:
        ltext(d, (40, y - 9), title, 11, bold=True)
        ltext(d, (40, y + 11), sub, 10, fill=MUTED)
        arrow(d, (270, y), (ox - 6, y))

    labels_right = [
        ("Lock  ·  Refresh  ·  Close", "lock keeps it above other windows", oy + 22),
        ("Credit spend", "against the total you set", oy + 165),
    ]
    for title, sub, y in labels_right:
        ltext(d, (ox + sw + 30, y - 9), title, 11, bold=True)
        ltext(d, (ox + sw + 30, y + 11), sub, 10, fill=MUTED)
        arrow(d, (ox + sw + 24, y), (ox + sw + 6, y))

    box(d, (40, 300, 960, 360), fill=FILL_ACCENT, outline=ACCENT)
    text(d, (500, 318), "Colours mean the same thing everywhere", 12, bold=True)
    text(d, (500, 342),
         "green: under half used     ·     amber: getting full     ·     red: nearly out",
         11, fill=MUTED)
    return save(img, "diagram-anatomy.png")


if __name__ == "__main__":
    print("Generating diagrams...")
    diagram_user_flow()
    diagram_architecture()
    diagram_failure()
    diagram_anatomy()
    print("Done.")
