# ------------------------------------------------------------------
# labelprinter - label layouts
# Date: 2026-11-07 18:10 GMT
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# Turns form data into a black-and-white image the exact width of the
# 62mm continuous roll (696 dots at 300 dpi). The label's LENGTH grows
# with its content, so nothing is ever printed landscape.
#
# Label types: address, freezer, travel, battery, network.
# ------------------------------------------------------------------
import os
from datetime import date, datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps

# Printable width of the 62mm continuous roll on the QL-810W, in dots
WIDTH = 696
SIDE = 18          # extra left/right padding inside the printable width
TOP = 22           # top/bottom padding
DOTS_PER_MM = 300 / 25.4

# ---------------------------------------------------------------- fonts
# DejaVu fonts are installed in the container (fonts-dejavu-*).
# Each role lists fallbacks so a missing file never crashes a print.
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu",
             os.path.join(os.path.dirname(__file__), "fonts")]
FONT_FILES = {
    "sans":      ["DejaVuSans.ttf"],
    "sans-bold": ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"],
    "cond":      ["DejaVuSansCondensed.ttf", "DejaVuSans.ttf"],
    "cond-bold": ["DejaVuSansCondensed-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "mono":      ["DejaVuSansMono.ttf"],
    "mono-bold": ["DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"],
}
_font_cache = {}


def font(role, size):
    """Return a cached TrueType font for a role (e.g. 'cond-bold') at a pixel size."""
    key = (role, size)
    if key in _font_cache:
        return _font_cache[key]
    for name in FONT_FILES[role]:
        for d in FONT_DIRS:
            path = os.path.join(d, name)
            if os.path.exists(path):
                _font_cache[key] = ImageFont.truetype(path, size)
                return _font_cache[key]
    _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def text_width(text, role, size):
    """Width in dots of a line of text in a given font."""
    f = font(role, size)
    left, _, right, _ = f.getbbox(text or " ")
    return right - left


def fit_size(lines, role, start, max_w, minimum=14):
    """Largest font size (<= start) at which every line fits within max_w dots."""
    size = start
    while size > minimum and any(text_width(t, role, size) > max_w for t in lines if t):
        size -= 2
    return size


def line_height(role, size, spacing=1.18):
    """Vertical advance for one line, based on the font's real ascent/descent."""
    ascent, descent = font(role, size).getmetrics()
    return int((ascent + descent) * spacing)


# ---------------------------------------------------------------- icons
# Built-in icons are simple bold line drawings (drawn below at 512 dots,
# then scaled down), in the same style as the iPrint&Label icons.
# To add or replace one, drop a black-on-white PNG into /data/icons
# (e.g. wedding.png) - files there take priority over built-ins.
ICON_DIR = os.environ.get("ICON_DIR", "/data/icons")
S = 512            # drawing canvas size for built-in icons
LW = 34            # line width at that size


def _icon_gift(d):
    """Wrapped present: box, lid, ribbon and a two-loop bow."""
    d.rectangle((86, 250, 426, 470), outline=0, width=LW)            # box
    d.rectangle((60, 170, 452, 250), outline=0, width=LW)            # lid
    d.rectangle((238, 170, 274, 470), fill=0)                        # ribbon
    d.ellipse((120, 60, 262, 186), outline=0, width=LW)              # left loop
    d.ellipse((250, 60, 392, 186), outline=0, width=LW)              # right loop
    d.ellipse((226, 150, 286, 206), fill=0)                          # knot


def _icon_birthday(d):
    """Birthday cake: two layers with icing wave, three candles and flames."""
    d.rounded_rectangle((70, 300, 442, 470), radius=30, outline=0, width=LW)
    d.rounded_rectangle((110, 200, 402, 310), radius=24, outline=0, width=LW)
    for i in range(6):                                              # icing wave
        x = 70 + i * 62
        d.arc((x, 330, x + 62, 390), 0, 180, fill=0, width=LW - 10)
    for x in (170, 256, 342):                                       # candles + flames
        d.rectangle((x - 14, 110, x + 14, 205), fill=0)
        d.polygon([(x, 30), (x - 26, 80), (x, 102), (x + 26, 80)], fill=0)


def _icon_christmas(d):
    """Christmas tree: three stacked tiers, trunk and a star on top."""
    for top, bot, half in ((100, 230, 110), (180, 330, 160), (270, 420, 210)):
        d.polygon([(256, top), (256 - half, bot), (256 + half, bot)], outline=0, width=LW)
    d.rectangle((222, 420, 290, 490), fill=0)
    _star(d, 256, 70, 58, 24, fill=0)


def _icon_celebration(d):
    """Party popper: cone with streamers and confetti."""
    d.polygon([(50, 470), (150, 190), (330, 370)], outline=0, width=LW)   # cone
    d.line([(250, 240), (300, 170), (270, 110), (330, 50)], fill=0, width=LW, joint="curve")
    d.line([(300, 300), (380, 270), (420, 320), (480, 290)], fill=0, width=LW, joint="curve")
    for cx, cy in ((200, 80), (410, 120), (460, 200), (380, 420), (120, 120)):
        d.rectangle((cx - 20, cy - 20, cx + 20, cy + 20), fill=0)        # confetti


def _icon_heart(d):
    """Outline heart."""
    pts = []
    import math
    for i in range(0, 361, 3):
        t = math.radians(i)
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((256 + x * 13, 250 - y * 13))
    d.line(pts + [pts[0]], fill=0, width=LW, joint="curve")


def _star(d, cx, cy, r_out, r_in, fill=None, width=0):
    """Five-pointed star centred on (cx, cy)."""
    import math
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(-90 + i * 36)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    if fill is not None:
        d.polygon(pts, fill=fill)
    else:
        d.polygon(pts, outline=0, width=width)


def _icon_star(d):
    """Outline star."""
    _star(d, 256, 270, 220, 92, width=LW)


def _icon_balloon(d):
    """Balloon with knot and a curly string."""
    d.ellipse((120, 40, 392, 360), outline=0, width=LW)
    d.polygon([(256, 352), (226, 396), (286, 396)], fill=0)
    d.line([(256, 396), (230, 430), (282, 462), (250, 500)], fill=0, width=LW - 12, joint="curve")


def _icon_wedding(d):
    """Two interlocking rings."""
    d.ellipse((60, 160, 300, 400), outline=0, width=LW)
    d.ellipse((212, 160, 452, 400), outline=0, width=LW)


def _icon_house(d):
    """New home: house outline with a door."""
    d.polygon([(256, 60), (50, 250), (462, 250)], outline=0, width=LW)
    d.rectangle((100, 240, 412, 470), outline=0, width=LW)
    d.rectangle((216, 340, 296, 470), fill=0)


BUILTIN_ICONS = {
    "gift": _icon_gift, "birthday": _icon_birthday, "christmas": _icon_christmas,
    "celebration": _icon_celebration, "heart": _icon_heart, "star": _icon_star,
    "balloon": _icon_balloon, "wedding": _icon_wedding, "new home": _icon_house,
}


def list_icons():
    """Names of all icons available: custom PNGs first, then built-ins."""
    custom = []
    if os.path.isdir(ICON_DIR):
        custom = sorted(os.path.splitext(f)[0] for f in os.listdir(ICON_DIR)
                        if f.lower().endswith(".png"))
    return custom + [k for k in BUILTIN_ICONS if k not in custom]


def load_icon(name, size):
    """Return a square black-and-white icon of `size` dots, or None."""
    if not name or name == "none":
        return None
    # 1. A custom PNG wins
    path = os.path.join(ICON_DIR, f"{name}.png")
    if os.path.exists(path):
        img = Image.open(path).convert("RGBA")
        bg = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(bg, img).convert("L")
        img = ImageOps.contain(img, (size, size))
        return _square(img, size).point(lambda v: 0 if v < 140 else 255)
    # 2. Otherwise a built-in drawing
    draw_fn = BUILTIN_ICONS.get(name)
    if draw_fn:
        canvas = Image.new("L", (S, S), 255)
        draw_fn(ImageDraw.Draw(canvas))
        small = canvas.resize((size, size), Image.Resampling.LANCZOS)
        return small.point(lambda v: 0 if v < 140 else 255)
    return None


def _square(img, size):
    """Centre an image on a white square canvas."""
    sq = Image.new("L", (size, size), 255)
    sq.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    return sq


# ---------------------------------------------------------------- helpers
def uk_date(value=None, short=False):
    """Format a date as '7 Nov 2026' (or '7 Nov 26' when short)."""
    if not value:
        d = date.today()
    elif isinstance(value, str):
        d = datetime.strptime(value[:10], "%Y-%m-%d").date()
    else:
        d = value
    return f"{d.day} {d.strftime('%b')} {d.strftime('%y' if short else '%Y')}"


def add_months(d, months):
    """Add whole months to a date, clamping to the end of shorter months."""
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return d.replace(year=y, month=m, day=day)
        except ValueError:
            continue


def draw_lines(lines, height_pad=TOP, left=SIDE, width=WIDTH, min_height=0):
    """
    Render a list of line specs onto a new label image.
    Each spec is a dict: text, role, size, align ('left'|'center'),
    and optional 'gap' (extra dots above the line).
    """
    y = height_pad
    placed = []
    for ln in lines:
        y += ln.get("gap", 0)
        if ln.get("text") is None:
            continue
        placed.append((ln, y))
        y += line_height(ln["role"], ln["size"], ln.get("spacing", 1.18))
    h = max(y + height_pad, min_height)
    img = Image.new("L", (width, h), 255)
    d = ImageDraw.Draw(img)
    usable = width - 2 * left
    for ln, yy in placed:
        f = font(ln["role"], ln["size"])
        w = text_width(ln["text"], ln["role"], ln["size"])
        x = left + (usable - w) // 2 if ln.get("align") == "center" else left
        d.text((x, yy), ln["text"], font=f, fill=0)
    return img


# ---------------------------------------------------------------- labels
def address(data):
    """
    Address label: large condensed name, address lines underneath,
    optional icon on the left (gift, birthday cake, Christmas tree...).
    data: name, address (multi-line), icon
    """
    name = (data.get("name") or "").strip()
    addr = [l.strip() for l in (data.get("address") or "").splitlines() if l.strip()]
    icon_name = data.get("icon") or "none"

    # Provisional text block to size the icon against
    icon_size = 0
    has_icon = icon_name != "none" and load_icon(icon_name, 32) is not None
    text_left = SIDE
    if has_icon:
        icon_size = 190
        text_left = SIDE + icon_size + 22
    max_w = WIDTH - text_left - SIDE

    name_size = fit_size([name], "cond", 66, max_w)
    addr_size = fit_size(addr, "sans", 48 if len(addr) <= 4 else 42, max_w)

    lines = [{"text": name, "role": "cond", "size": name_size}]
    for i, a in enumerate(addr):
        lines.append({"text": a, "role": "sans", "size": addr_size, "gap": 6 if i == 0 else 0, "spacing": 1.12})

    text_img = draw_lines(lines, left=0, width=max_w + 2)
    h = max(text_img.height, (icon_size + 2 * TOP) if has_icon else 0)
    img = Image.new("L", (WIDTH, h), 255)
    img.paste(text_img, (text_left, (h - text_img.height) // 2))
    if has_icon:
        icon = load_icon(icon_name, icon_size)
        img.paste(icon, (SIDE, (h - icon_size) // 2))
    return img


def freezer(data):
    """
    Freezer label: food title, frozen date, use-by date (from months),
    and cooking instructions (defrost first / from frozen, time, temps).
    data: title, frozen (YYYY-MM-DD), months, method, minutes, temp_c, fan_c, notes
    """
    title = (data.get("title") or "").strip()
    frozen_d = datetime.strptime(data["frozen"], "%Y-%m-%d").date() if data.get("frozen") else date.today()
    months = int(data["months"]) if str(data.get("months") or "").strip() else 0

    usable = WIDTH - 2 * SIDE
    lines = [{"text": title, "role": "sans-bold", "size": fit_size([title], "sans-bold", 72, usable), "align": "center"}]

    dates = f"Frozen {uk_date(frozen_d)}"
    if months:
        dates += f"  ·  Use by {uk_date(add_months(frozen_d, months))}"
    lines.append({"text": dates, "role": "cond", "size": fit_size([dates], "cond", 40, usable), "align": "center", "gap": 8})

    method = {"from_frozen": "Cook from frozen", "defrost": "Defrost first"}.get(data.get("method"), "")
    parts = []
    if str(data.get("minutes") or "").strip():
        parts.append(f"{data['minutes']} min")
    temps = []
    if str(data.get("temp_c") or "").strip():
        temps.append(f"{data['temp_c']}°C")
    if str(data.get("fan_c") or "").strip():
        temps.append(f"{data['fan_c']}°C fan")
    if temps:
        parts.append("@ " + " / ".join(temps))
    cook = "  ".join(parts)
    cook_lines = [t for t in (method, cook) if t]
    if cook_lines:
        size = fit_size(cook_lines, "sans", 40, usable)
        for i, t in enumerate(cook_lines):
            lines.append({"text": t, "role": "sans-bold" if i == 0 and method else "sans",
                          "size": size, "align": "center", "gap": 14 if i == 0 else 0})
    notes = [l.strip() for l in (data.get("notes") or "").splitlines() if l.strip()]
    if notes:
        size = fit_size(notes, "cond", 34, usable)
        for i, n in enumerate(notes):
            lines.append({"text": n, "role": "cond", "size": size, "align": "center", "gap": 10 if i == 0 else 0})
    return draw_lines(lines)


def travel(data):
    """
    Travel label: name, address, phone, then the flights exactly as typed
    (blank lines between journeys are kept). Monospaced so times line up.
    data: name, address, phone, flights (multi-line)
    """
    header = [data.get("name", ""), data.get("address", ""), data.get("phone", "")]
    header = [h.strip() for h in header if h and h.strip()]
    flights = (data.get("flights") or "").rstrip().splitlines()
    every = header + [f for f in flights if f.strip()]
    size = fit_size(every, "mono", 36, WIDTH - 2 * SIDE, minimum=16)
    lh = line_height("mono", size, 1.15)

    lines = [{"text": h, "role": "mono-bold" if i == 0 else "mono", "size": size, "spacing": 1.15}
             for i, h in enumerate(header)]
    gap = lh // 2
    pending = lh // 2 if header else 0
    for f in flights:
        if not f.strip():
            pending = gap
            continue
        lines.append({"text": f.rstrip(), "role": "mono", "size": size, "spacing": 1.15, "gap": pending})
        pending = 0
    return draw_lines(lines)


def battery(data):
    """
    Battery-changed label: deliberately tiny (the printer's 12.7mm minimum).
    data: device, battery, changed (YYYY-MM-DD)
    """
    device = (data.get("device") or "").strip()
    info = " · ".join(t for t in [(data.get("battery") or "").strip(),
                                  uk_date(data.get("changed") or None, short=True)] if t)
    usable = WIDTH - 2 * SIDE
    lines = []
    if device:
        lines.append({"text": device, "role": "cond-bold", "size": fit_size([device], "cond-bold", 34, usable),
                      "align": "center", "spacing": 1.05})
    lines.append({"text": info, "role": "cond", "size": fit_size([info], "cond", 30, usable),
                  "align": "center", "spacing": 1.05})
    return draw_lines(lines, height_pad=10)


def network(data):
    """
    Network device label: device name, IP, VLAN, MAC and an optional note.
    data: name, ip, vlan, mac, notes
    """
    usable = WIDTH - 2 * SIDE
    name = (data.get("name") or "").strip()
    rows = []
    if data.get("ip"):
        rows.append(f"IP   {data['ip'].strip()}")
    if data.get("vlan"):
        rows.append(f"VLAN {data['vlan'].strip()}")
    if data.get("mac"):
        rows.append(f"MAC  {data['mac'].strip().upper()}")
    lines = [{"text": name, "role": "cond-bold", "size": fit_size([name], "cond-bold", 60, usable)}]
    if rows:
        size = fit_size(rows, "mono", 36, usable)
        for i, r in enumerate(rows):
            lines.append({"text": r, "role": "mono", "size": size, "gap": 8 if i == 0 else 0, "spacing": 1.12})
    notes = [l.strip() for l in (data.get("notes") or "").splitlines() if l.strip()]
    if notes:
        size = fit_size(notes, "cond", 32, usable)
        for i, n in enumerate(notes):
            lines.append({"text": n, "role": "cond", "size": size, "gap": 8 if i == 0 else 0})
    return draw_lines(lines)


RENDERERS = {"address": address, "freezer": freezer, "travel": travel,
             "battery": battery, "network": network}


# The QL-810W refuses continuous labels shorter than 150 dots (12.7mm),
# so short labels (e.g. battery) are padded to that, content centred.
MIN_LENGTH = 150


def render(kind, data):
    """Render a label of the given kind. Raises KeyError for an unknown kind."""
    img = RENDERERS[kind](data or {})
    if img.height < MIN_LENGTH:
        padded = Image.new("L", (img.width, MIN_LENGTH), 255)
        padded.paste(img, (0, (MIN_LENGTH - img.height) // 2))
        img = padded
    return img.convert("1", dither=Image.Dither.NONE).convert("L")
