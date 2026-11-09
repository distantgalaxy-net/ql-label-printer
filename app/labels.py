# ------------------------------------------------------------------
# labelprinter - label layouts
# Date: 2026-11-09 12:40 GMT (updated; first written 2026-11-07 18:10 GMT)
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# Turns form data into a black-and-white image the exact width of the
# 62mm continuous roll (696 dots at 300 dpi). The label's LENGTH grows
# with its content, so nothing is ever printed landscape.
#
# Label types: address, food (freezer / fridge / cupboard), travel,
# battery, network. "freezer" is kept as another name for "food" so older
# Home Assistant calls still work.
#
# "Today" (default dates on labels) uses the time zone chosen in the
# Settings tab, so daylight saving is handled by the tz database. The
# temperature unit (°C or °F) also comes from the Settings tab.
#
# Also here: custom icon upload/delete (pictures are converted to
# black-and-white squares and saved in /data/icons, never in the image),
# and the flight helpers for travel labels (format, sort, split into
# journeys, and pick a flight out of pasted booking text).
# ------------------------------------------------------------------
import contextvars
import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
# Built-in icons are simple bold line drawings, drawn by the code below at
# 512 dots and then scaled down (no image files, so no third-party artwork).
# Custom icons are uploaded from the Address tab (or copied into
# /data/icons as black-on-white PNGs); they take priority over built-ins
# with the same name. /data is never part of the repo or the image.
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
    """Two wedding rings, linked (one in front at each crossing), with a diamond."""
    import math
    r = 120                                   # ring radius
    ax, bx, cy = 186, 326, 330                # ring centres (left, right) and height
    ra = (ax - r, cy - r, ax + r, cy + r)
    rb = (bx - r, cy - r, bx + r, cy + r)
    # Diamond sitting on top of the left ring: solid, with a white girdle line
    top = cy - r - 138
    gem = [(ax - 68, top + 50), (ax - 36, top), (ax + 36, top), (ax + 68, top + 50), (ax, top + 140)]
    d.polygon(gem, fill=0)
    d.line([(ax - 50, top + 50), (ax + 50, top + 50)], fill=255, width=12)
    d.ellipse(ra, outline=0, width=LW)
    d.ellipse(rb, outline=0, width=LW)
    # Where the rings cross (worked out, so it stays right if sizes change).
    # PIL angles: 0 = 3 o'clock, increasing clockwise.
    half = (bx - ax) / 2
    dy = math.sqrt(r * r - half * half)
    a_top = math.degrees(math.atan2(-dy, half)) % 360      # top crossing, on the left ring
    b_top = math.degrees(math.atan2(-dy, -half)) % 360     # top crossing, on the right ring
    a_bot, b_bot = (360 - a_top) % 360, (360 - b_top) % 360

    def crossing(behind, front, behind_deg, front_deg):
        """Break the ring behind just wider than the front ring, then redraw the front."""
        d.arc((behind[0] - 6, behind[1] - 6, behind[2] + 6, behind[3] + 6),
              behind_deg - 10, behind_deg + 10, fill=255, width=LW + 12)
        d.arc(front, front_deg - 16, front_deg + 16, fill=0, width=LW)
    crossing(rb, ra, b_top, a_top)            # top: left ring in front
    crossing(ra, rb, a_bot, b_bot)            # bottom: right ring in front


def _rotate(points, cx, cy, degrees):
    """Turn (x, y) points about (cx, cy) by an angle (clockwise on screen)."""
    import math
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in points]


def _rounded_bar(cx, cy, length, height):
    """Outline points of a bar with round ends, centred on (cx, cy)."""
    import math
    r = height / 2
    left, right = cx - length / 2 + r, cx + length / 2 - r
    pts = [(right + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 91, 6)]
    pts += [(left + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(90, 271, 6)]
    return pts


def _heart_points(cx, cy, scale, point_to):
    """Heart outline centred on (cx, cy) with its point aimed at an angle (0 = right, 90 = down)."""
    import math
    pts = []
    for i in range(0, 361, 4):
        t = math.radians(i)
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * scale, cy + y * scale))
    return _rotate(pts, cx, cy, point_to - 90)      # drawn pointing down; turn it


def _icon_get_well(d):
    """Get well: a sticking plaster at 45 degrees with a pad and air holes."""
    cx = cy = 256
    strip = _rotate(_rounded_bar(cx, cy, 470, 170), cx, cy, -45)
    d.line(strip + strip[:2], fill=0, width=LW, joint="curve")
    pad = _rotate([(cx - 80, cy - 85), (cx + 80, cy - 85), (cx + 80, cy + 85), (cx - 80, cy + 85)], cx, cy, -45)
    d.line(pad + pad[:2], fill=0, width=LW - 6, joint="curve")
    for dx in (-160, -125, 125, 160):                # air holes at both ends
        for dy in (-30, 30):
            (x, y), = _rotate([(cx + dx, cy + dy)], cx, cy, -45)
            d.ellipse((x - 11, y - 11, x + 11, y + 11), fill=0)


def _curve(p0, p1, p2, steps=24):
    """Points along a smooth curve from p0 to p2, pulled towards p1."""
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in (i / steps for i in range(steps + 1))]


def _icon_good_luck(d):
    """Good luck: a four-leaf clover - four solid heart leaves, stem out of the bottom."""
    import math
    cx, cy = 256, 200
    # Stem first, so the bottom leaf covers its top end
    d.line(_curve((cx, cy + 120), (cx - 6, cy + 250), (cx + 80, cy + 300)), fill=0, width=30, joint="curve")
    for out in (-90, 0, 90, 180):                                  # up, right, down, left
        a = math.radians(out)
        hx, hy = cx + 100 * math.cos(a), cy + 100 * math.sin(a)
        d.polygon(_heart_points(hx, hy, 6.0, out + 180), fill=0)  # point to the middle
    for diag in (45, 135, 225, 315):                               # thin gaps between leaves
        a = math.radians(diag)
        d.line([(cx, cy), (cx + 200 * math.cos(a), cy + 200 * math.sin(a))], fill=255, width=16)


def _icon_horseshoe(d):
    """Horseshoe, open end up (so the luck doesn't run out), with nail holes."""
    import math
    box = (100, 56, 412, 456)                          # taller than wide
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    thick = 84
    d.arc(box, 296, 604, fill=0, width=thick)          # from upper right, under, to upper left
    mid_rx = (box[2] - box[0]) / 2 - thick / 2         # middle of the band
    mid_ry = (box[3] - box[1]) / 2 - thick / 2
    for ang in (318, 350, 22, 158, 190, 222):          # nail holes
        a = math.radians(ang)
        x, y = cx + mid_rx * math.cos(a), cy + mid_ry * math.sin(a)
        d.ellipse((x - 12, y - 12, x + 12, y + 12), fill=255)


def _leaf(d, base, tip, width):
    """A solid pointed leaf from base to tip, widest in the middle."""
    import math
    (bx, by), (tx, ty) = base, tip
    length = math.hypot(tx - bx, ty - by)
    nx, ny = -(ty - by) / length, (tx - bx) / length   # sideways direction
    side1, side2 = [], []
    for i in range(21):
        t = i / 20
        x, y = bx + (tx - bx) * t, by + (ty - by) * t
        off = math.sin(math.pi * t) * width / 2
        side1.append((x + nx * off, y + ny * off))
        side2.append((x - nx * off, y - ny * off))
    d.polygon(side1 + side2[::-1], fill=0)


def _tulip(d, x, y, w, h):
    """A solid tulip head with its base at (x, y): three points on top, round cup below."""
    import math
    pts = [(x - w / 2, y - h), (x - w / 4, y - h * 0.62), (x, y - h * 1.08),
           (x + w / 4, y - h * 0.62), (x + w / 2, y - h)]
    for i in range(0, 181, 10):
        a = math.radians(i)
        pts.append((x + (w / 2) * math.cos(a), y - h * 0.45 + h * 0.45 * math.sin(a)))
    d.polygon(pts, fill=0)


def _icon_flowers(d):
    """Flowers: a bunch of three tulips with two leaves, tied with a band."""
    tie = (256, 380)                                   # where the stems are tied
    heads = [(146, 220, 104, 112), (256, 160, 112, 122), (366, 220, 104, 112)]
    for hx, hy, _, _ in heads:                         # stems curve in to the tie
        d.line(_curve((hx, hy), ((hx + tie[0]) / 2, hy + 90), tie), fill=0, width=18, joint="curve")
    for dx in (-26, 0, 26):                            # stem ends below the tie
        d.line([(tie[0] + dx * 0.6, tie[1]), (tie[0] + dx, 490)], fill=0, width=16)
    _leaf(d, (240, 370), (92, 300), 52)
    _leaf(d, (272, 370), (420, 300), 52)
    for hx, hy, w, h in heads:
        _tulip(d, hx, hy + 6, w, h)
    d.rounded_rectangle((218, 372, 294, 412), radius=10, fill=0)   # the band


def _icon_house(d):
    """New home: house outline with a door."""
    d.polygon([(256, 60), (50, 250), (462, 250)], outline=0, width=LW)
    d.rectangle((100, 240, 412, 470), outline=0, width=LW)
    d.rectangle((216, 340, 296, 470), fill=0)


BUILTIN_ICONS = {
    "gift": _icon_gift, "birthday": _icon_birthday, "christmas": _icon_christmas,
    "celebration": _icon_celebration, "heart": _icon_heart, "star": _icon_star,
    "balloon": _icon_balloon, "wedding": _icon_wedding, "new home": _icon_house,
    "get well": _icon_get_well, "good luck": _icon_good_luck, "horseshoe": _icon_horseshoe,
    "flowers": _icon_flowers,
}


# Custom icon names: letters, digits, spaces, hyphens and underscores only,
# so a name can never point outside ICON_DIR (e.g. "../something").
_ICON_NAME = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,29}$")
# Picture formats accepted for upload, and the largest picture we'll open
UPLOAD_FORMATS = {"PNG", "JPEG", "GIF", "WEBP", "BMP"}
MAX_UPLOAD_PIXELS = 40_000_000
THRESHOLD = 140    # grey levels darker than this become black


def clean_icon_name(name):
    """Return a safe, lower-case icon name, or None if it isn't allowed."""
    name = re.sub(r"\s+", " ", (name or "").strip().lower())
    return name if _ICON_NAME.match(name) else None


def _custom_names():
    """Names of the custom PNG icons in ICON_DIR (uploaded or copied in)."""
    if not os.path.isdir(ICON_DIR):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(ICON_DIR)
                  if f.lower().endswith(".png") and clean_icon_name(os.path.splitext(f)[0]))


def list_icons():
    """All icons for the page: custom ones first, then built-ins.

    Each entry is {"name", "custom"}. A custom icon with a built-in's name
    replaces that built-in; deleting it brings the built-in back.
    """
    custom = _custom_names()
    return ([{"name": n, "custom": True} for n in custom] +
            [{"name": k, "custom": False} for k in BUILTIN_ICONS if k not in custom])


def load_icon(name, size):
    """Return a square black-and-white icon of `size` dots, or None."""
    name = clean_icon_name(name)
    if not name or name == "none":
        return None
    # 1. A custom PNG wins
    path = os.path.join(ICON_DIR, f"{name}.png")
    if os.path.exists(path):
        img = Image.open(path).convert("RGBA")
        bg = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(bg, img).convert("L")
        img = ImageOps.contain(img, (size, size))
        return _square(img, size).point(lambda v: 0 if v < THRESHOLD else 255)
    # 2. Otherwise a built-in drawing
    draw_fn = BUILTIN_ICONS.get(name)
    if draw_fn:
        canvas = Image.new("L", (S, S), 255)
        draw_fn(ImageDraw.Draw(canvas))
        small = canvas.resize((size, size), Image.Resampling.LANCZOS)
        return small.point(lambda v: 0 if v < THRESHOLD else 255)
    return None


def save_custom_icon(name, stream):
    """Convert an uploaded picture into a custom icon. Returns (name, error).

    The picture (PNG, JPEG, GIF, WebP or BMP) is flattened onto white,
    turned to greyscale, trimmed to its content, fitted into a 512-dot
    square and converted to pure black and white, then saved as
    <name>.png in ICON_DIR. On the label it prints about 16mm square.
    """
    name = clean_icon_name(name)
    if not name or name == "none":
        return None, "Give the icon a name: letters, numbers, spaces or hyphens (up to 30)."
    try:
        img = Image.open(stream)
        if img.format not in UPLOAD_FORMATS:
            return None, "Use a PNG, JPEG, GIF, WebP or BMP picture."
        if img.width * img.height > MAX_UPLOAD_PIXELS:
            return None, "That picture is too large. Try one under 40 megapixels."
        img.seek(0)                                # first frame of a GIF
        img = ImageOps.exif_transpose(img)         # phone photos: fix rotation
        rgba = img.convert("RGBA")
    except Exception:
        return None, "That file isn't a picture this can read."
    flat = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("L")
    # Trim plain white margins so the drawing fills the square
    box = flat.point(lambda v: 255 if v < THRESHOLD else 0).getbbox()
    if not box:
        return None, "The picture came out blank. Use one with dark shapes on a light background."
    flat = ImageOps.contain(flat.crop(box), (S, S), Image.Resampling.LANCZOS)
    bw = _square(flat, S).point(lambda v: 0 if v < THRESHOLD else 255).convert("1")
    os.makedirs(ICON_DIR, exist_ok=True)
    bw.save(os.path.join(ICON_DIR, f"{name}.png"))
    return name, None


def delete_custom_icon(name):
    """Delete a custom icon. Returns True if one was removed (built-ins can't be)."""
    name = clean_icon_name(name)
    path = os.path.join(ICON_DIR, f"{name}.png") if name else None
    if path and os.path.exists(path):
        os.remove(path)
        return True
    return False


def _square(img, size):
    """Centre an image on a white square canvas."""
    sq = Image.new("L", (size, size), 255)
    sq.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    return sq


# ---------------------------------------------------------------- helpers
# Time zone for the label being rendered (set by render(); requests can run
# in parallel threads, so a context variable keeps each one separate)
_tz = contextvars.ContextVar("label_tz", default="UTC")
# Temperature unit from the Settings tab: "C" or "F"
_unit = contextvars.ContextVar("label_unit", default="C")


def today(tz=None):
    """Today's date in the Settings time zone (or `tz`); UTC if unset/unknown."""
    try:
        zone = ZoneInfo(tz or _tz.get() or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


def uk_date(value=None, short=False):
    """Format a date as '7 Nov 2026' (or '7 Nov 26' when short)."""
    if not value:
        d = today()
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
# Address label sizes (dots)
NAME_SIZE = 66          # the name's normal font size
NAME_BESIDE_MIN = 56    # smallest the name may get beside an icon before it moves on top
ICON_SIZE = 190         # icon beside the whole block (about 16mm)
ICON_GAP = 22           # space between icon and text
NAME_WRAP_BELOW = 52    # a name that would be smaller than this on one line goes on two


def name_lines(name, width):
    """Line specs for the name: one line, or two if that lets it be bigger.

    A long name on one line can end up smaller than the address. If one
    line would be below NAME_WRAP_BELOW, try every split between words and
    use the two-line version that allows the largest size (if it's bigger).
    """
    size = fit_size([name], "cond", NAME_SIZE, width)
    words = name.split()
    if size >= NAME_WRAP_BELOW or len(words) < 2:
        return [{"text": name, "role": "cond", "size": size}]
    best, best_size = None, size
    for i in range(1, len(words)):
        pair = [" ".join(words[:i]), " ".join(words[i:])]
        s2 = fit_size(pair, "cond", NAME_SIZE, width)
        if s2 > best_size:
            best, best_size = pair, s2
    if not best:
        return [{"text": name, "role": "cond", "size": size}]
    return [{"text": t, "role": "cond", "size": best_size, "spacing": 1.05} for t in best]


def address(data):
    """
    Address label: large condensed name, address lines underneath,
    optional icon on the left (gift, birthday cake, Christmas tree...).
    data: name, address (multi-line), icon

    Two layouts when there's an icon:
      - beside: icon on the left of the name and address (short names);
      - name on top: when the name would have to shrink below
        NAME_BESIDE_MIN to fit beside the icon, it goes across the full
        width on top and the icon sits beside the address lines only,
        so long names stay big.
    A name too long for one line at a decent size goes on two lines
    (split between words), with or without an icon.
    """
    name = (data.get("name") or "").strip()
    addr = [l.strip() for l in (data.get("address") or "").splitlines() if l.strip()]
    icon_name = data.get("icon") or "none"
    has_icon = icon_name != "none" and load_icon(icon_name, 32) is not None
    full_w = WIDTH - 2 * SIDE                     # text width without an icon
    beside_w = full_w - ICON_SIZE - ICON_GAP      # text width next to an icon
    addr_start = 48 if len(addr) <= 4 else 42     # smaller text for long addresses

    def address_lines(size, first_gap):
        """Line specs for the address at a font size."""
        return [{"text": a, "role": "sans", "size": size, "gap": first_gap if i == 0 else 0, "spacing": 1.12}
                for i, a in enumerate(addr)]

    # No icon: name (on two lines if it's long) and address across the full width
    if not has_icon:
        lines = name_lines(name, full_w) + address_lines(fit_size(addr, "sans", addr_start, full_w), 6)
        return draw_lines(lines)

    name_beside = fit_size([name], "cond", NAME_SIZE, beside_w)
    addr_size = fit_size(addr, "sans", addr_start, beside_w)

    # Short name: icon beside the whole block (the original layout)
    if name_beside >= NAME_BESIDE_MIN or not addr:
        lines = [{"text": name, "role": "cond", "size": name_beside}] + address_lines(addr_size, 6)
        text_img = draw_lines(lines, left=0, width=beside_w + 2)
        h = max(text_img.height, ICON_SIZE + 2 * TOP)
        img = Image.new("L", (WIDTH, h), 255)
        img.paste(text_img, (SIDE + ICON_SIZE + ICON_GAP, (h - text_img.height) // 2))
        img.paste(load_icon(icon_name, ICON_SIZE), (SIDE, (h - ICON_SIZE) // 2))
        return img

    # Long name: name across the full width on top (on two lines if it's
    # very long), icon beside the address. The icon matches the address
    # block's height (between 130 and 190 dots).
    name_img = draw_lines(name_lines(name, full_w), height_pad=TOP)
    addr_img = draw_lines(address_lines(addr_size, 0), height_pad=0, left=0, width=beside_w + 2)
    icon_size = max(130, min(ICON_SIZE, addr_img.height))
    row_h = max(addr_img.height, icon_size)
    name_h = name_img.height - TOP // 2            # keep the name close to the address
    h = name_h + row_h + TOP
    img = Image.new("L", (WIDTH, h), 255)
    img.paste(name_img.crop((0, 0, WIDTH, name_h)), (0, 0))
    img.paste(addr_img, (SIDE + ICON_SIZE + ICON_GAP, name_h + (row_h - addr_img.height) // 2))
    # Centre the icon in the same column it uses in the other layout
    icon_x = SIDE + (ICON_SIZE - icon_size) // 2
    img.paste(load_icon(icon_name, icon_size), (icon_x, name_h + (row_h - icon_size) // 2))
    return img


# Food storage types: what the first date means, and the usual unit for
# "use within" (months in the freezer, days in the fridge or cupboard)
STORAGE = {
    "frozen":   {"date_word": "Frozen", "unit": "months"},
    "fridge":   {"date_word": "Opened", "unit": "days"},
    "cupboard": {"date_word": "Opened", "unit": "days"},
}
# Cooking method -> heading line on the label ("cook" = no heading, just
# the time and temperature; "none" = no cooking instructions at all)
METHODS = {"from_frozen": "Cook from frozen", "defrost": "Defrost first", "cook": "", "": ""}


def _number(value):
    """A whole number from a form field, or None if it's blank or not a number."""
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def food(data):
    """
    Food label: food name, the frozen/opened date, a use-by date worked out
    from "use within" days or months, optional cooking instructions and notes.
    data: title, storage (frozen | fridge | cupboard), date (YYYY-MM-DD,
          default today), shelf (number), shelf_unit (days | months),
          method (from_frozen | defrost | cook | none), minutes, temp, fan, notes.
    Temperatures are in the unit chosen in Settings (°C or °F).
    Older freezer fields still work: frozen, months, temp_c, fan_c.
    """
    title = (data.get("title") or "").strip()
    storage = data.get("storage") if data.get("storage") in STORAGE else "frozen"
    kind = STORAGE[storage]
    raw_date = data.get("date") or data.get("frozen")
    start = datetime.strptime(raw_date[:10], "%Y-%m-%d").date() if raw_date else today()

    # "Use within": new fields first, then the old freezer "months"
    amount, unit = _number(data.get("shelf")), data.get("shelf_unit")
    if amount is None and _number(data.get("months")) is not None:
        amount, unit = _number(data.get("months")), "months"
    unit = unit if unit in ("days", "months") else kind["unit"]

    usable = WIDTH - 2 * SIDE
    lines = [{"text": title, "role": "sans-bold", "size": fit_size([title], "sans-bold", 72, usable), "align": "center"}]

    dates = f"{kind['date_word']} {uk_date(start)}"
    if amount:
        use_by = add_months(start, amount) if unit == "months" else start + timedelta(days=amount)
        dates += f"  ·  Use by {uk_date(use_by)}"
    lines.append({"text": dates, "role": "cond", "size": fit_size([dates], "cond", 40, usable), "align": "center", "gap": 8})

    method = data.get("method") or ""
    if method != "none":
        heading = METHODS.get(method, "")
        # Old freezer fields were always °C; new ones use the Settings unit
        temp, fan, sym = data.get("temp"), data.get("fan"), _unit.get()
        if temp in (None, "") and fan in (None, "") and (data.get("temp_c") or data.get("fan_c")):
            temp, fan, sym = data.get("temp_c"), data.get("fan_c"), "C"
        parts = []
        if str(data.get("minutes") or "").strip():
            parts.append(f"{str(data['minutes']).strip()} min")
        temps = []
        if str(temp or "").strip():
            temps.append(f"{str(temp).strip()}°{sym}")
        if str(fan or "").strip():
            temps.append(f"{str(fan).strip()}°{sym} fan")
        if temps:
            parts.append("@ " + " / ".join(temps))
        cook_lines = [t for t in (heading, "  ".join(parts)) if t]
        if cook_lines:
            size = fit_size(cook_lines, "sans", 40, usable)
            for i, t in enumerate(cook_lines):
                lines.append({"text": t, "role": "sans-bold" if i == 0 and heading else "sans",
                              "size": size, "align": "center", "gap": 14 if i == 0 else 0})
    notes = [l.strip() for l in (data.get("notes") or "").splitlines() if l.strip()]
    if notes:
        size = fit_size(notes, "cond", 34, usable)
        for i, n in enumerate(notes):
            lines.append({"text": n, "role": "cond", "size": size, "align": "center", "gap": 10 if i == 0 else 0})
    return draw_lines(lines)


# ---------------------------------------------------------------- flights
# A flight ("leg") is a dict:
#   date "YYYY-MM-DD", flight "XX 0123", from "AAA", to "BBB",
#   dep "HH:MM", arr "HH:MM", plus1 (True if it lands the next day).
# Legs are sorted by departure, and a gap of more than a day between one
# landing and the next take-off starts a new journey (a blank line).
MAX_LEGS = 30
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _leg_date(leg):
    """The leg's departure date, or None if it's missing or invalid."""
    try:
        return datetime.strptime(str(leg.get("date") or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _hhmm(value):
    """'09:05' or '0905' -> '0905' (24-hour clock); anything else -> ''."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(4) if len(digits) in (3, 4) else ""


def clean_legs(legs):
    """Keep only well-formed legs (with a valid date), tidied, sorted by departure."""
    out = []
    for leg in (legs if isinstance(legs, list) else [])[:MAX_LEGS]:
        if not isinstance(leg, dict) or not _leg_date(leg):
            continue
        out.append({
            "date": _leg_date(leg).isoformat(),
            "flight": re.sub(r"\s+", " ", str(leg.get("flight") or "").strip().upper()),
            "from": str(leg.get("from") or "").strip().upper(),
            "to": str(leg.get("to") or "").strip().upper(),
            "dep": _hhmm(leg.get("dep")),
            "arr": _hhmm(leg.get("arr")),
            "plus1": bool(leg.get("plus1")),
        })
    return sorted(out, key=lambda l: (l["date"], l["dep"]))


def format_legs(legs):
    """Lines for the label, one per flight, with "" between journeys.

    Each line follows the template '1 Mar 0900-1130, XX 0123, AAA-BBB'
    ('+1' after the arrival time when it lands the next day).
    """
    lines, last_arrival = [], None
    for leg in clean_legs(legs):
        d = _leg_date(leg)
        if last_arrival and (d - last_arrival).days > 1:
            lines.append("")                     # a break: next journey
        when = f"{d.day} {d.strftime('%b')}"
        times = "-".join(t for t in (leg["dep"], leg["arr"]) if t)
        if times and leg["plus1"]:
            times += "+1"
        route = "-".join(t for t in (leg["from"], leg["to"]) if t)
        first = " ".join(t for t in (when, times) if t)
        lines.append(", ".join(t for t in (first, leg["flight"], route) if t))
        last_arrival = d + timedelta(days=1 if leg["plus1"] else 0)
    return lines


# Flight number: airline code (two letters, or a letter and a digit) then
# 1-4 digits, e.g. "BA 95", "U2 1234". Capitals only and not part of a
# longer word, so ordinary words and times aren't mistaken for one.
_FLIGHT = r"(?<![A-Za-z0-9])([A-Z]{2}|[A-Z][0-9]|[0-9][A-Z])\s?([0-9]{1,4})(?![0-9:.])"
# A clock time such as 18:05 or 18.05 (not part of a date like 24.08.2026)
_TIME = r"(?<![\d:.])([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d:.])"


def parse_flight(text, reference=None):
    """Pick out one flight from pasted text, e.g. a booking confirmation.

    The text can be laid out any way: the date, flight number, airports
    and times are each looked for separately, so a block copied from an
    email or a travel agent's page works as well as the label template
    ('1 Mar 0900-1130, XX 0123, AAA-BBB').
      date     first date found ('Monday, 24 August 2026', '24 Aug',
               'August 24, 2026', '24/08/2026', '2026-08-24')
      flight   after the word "Flight" if present, else the first one found
      airports codes in brackets ('London (LHR)'), else 'LHR-YUL' /
               'LHR to YUL', else codes on lines of their own
      times    after "Departure"/"Arrival" if labelled, else the first two
               clock times, else '0900-1130'
      +1       '+1' in the text, or landing at an earlier clock time
    Returns (leg, missing, more): leg is a dict (see clean_legs) or None if
    nothing useful was found; missing lists the parts not found; more is
    True when the text seems to hold more than one flight.
    """
    reference = reference or today()
    text = (text or "").replace("&nbsp;", " ").replace("&nbsp", " ").replace("\u00a0", " ")
    d, span = _find_date(text, reference)
    rest = text[:span[0]] + " " + text[span[1]:] if span else text

    # Flight number: prefer one labelled "Flight"
    codes = [f"{m.group(1)} {m.group(2)}" for m in re.finditer(_FLIGHT, rest)]
    labelled = re.search(r"flight\s*(?:no\.?|number)?\s*:?\s*" + _FLIGHT, rest, re.I)
    flight = f"{labelled.group(1)} {labelled.group(2)}" if labelled else (codes[0] if codes else "")

    # Airports
    origin = dest = ""
    bracketed = []
    for code in re.findall(r"\(([A-Z]{3})\)", rest):
        if code not in bracketed:
            bracketed.append(code)
    route = re.search(r"(?<![A-Za-z])([A-Z]{3})\s*(?:-|–|>|→|\bto\b)\s*([A-Z]{3})(?![A-Za-z])", rest)
    alone = re.findall(r"^\s*([A-Z]{3})\s*$", rest, re.M)
    if len(bracketed) >= 2:
        origin, dest = bracketed[0], bracketed[1]
    elif route:
        origin, dest = route.group(1), route.group(2)
    elif len(alone) >= 2:
        origin, dest = alone[0], alone[1]

    # Times: labelled first, then any clock times, then '0900-1130'
    def labelled_time(word):
        m = re.search(word + r"[a-z]*\b[^0-9\n]{0,25}?" + _TIME, rest, re.I)
        return f"{m.group(1).zfill(2)}{m.group(2)}" if m else ""
    dep, arr = labelled_time("depart"), labelled_time("arriv")
    if not dep and not arr:
        clock = re.findall(_TIME, rest)
        if clock:
            dep = f"{clock[0][0].zfill(2)}{clock[0][1]}"
            arr = f"{clock[1][0].zfill(2)}{clock[1][1]}" if len(clock) > 1 else ""
        else:
            m = re.search(r"(?<!\d)(\d{4})\s*[-–]\s*(\d{4})(?!\d)", rest)
            if m and int(m.group(1)[:2]) < 24 and int(m.group(2)[:2]) < 24:
                dep, arr = m.group(1), m.group(2)
    plus1 = bool(re.search(r"\+\s?1(?!\d)", rest)) or bool(dep and arr and arr < dep)

    if not (d or flight or origin or dep):
        return None, [], False
    leg = {"date": d.isoformat() if d else "", "flight": flight, "from": origin, "to": dest,
           "dep": dep, "arr": arr, "plus1": plus1}
    missing = [name for name, value in (("date", d), ("flight number", flight), ("airports", origin),
                                        ("departure time", dep), ("arrival time", arr)) if not value]
    return leg, missing, len(set(codes)) > 1


# An optional year after "1 Mar": 19xx/20xx, but not when it's really the
# start of a time range ("1 Mar 2030-2245" is a time, not the year 2030)
_YEAR = r"(?:\s+((?:19|20)\d{2})(?!\d|\s*[-–:]))?\b"


def _find_date(line, reference):
    """The first date in some text and where it is: (date, (start, end)).

    Returns (None, None) if there's no date (see parse_flight for formats).
    """
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", line)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.span()
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", line)   # UK: day/month
    if m:
        return _with_year(int(m.group(1)), int(m.group(2)), m.group(3), reference), m.span()
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?" + _YEAR, line):
        if m.group(2)[:3].lower() in _MONTHS:      # a real month name, not "LGW"
            return _with_year(int(m.group(1)), _MONTHS[m.group(2)[:3].lower()], m.group(3), reference), m.span()
    # US order: "August 24, 2026" / "Aug 24"
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b,?" + _YEAR, line):
        if m.group(1)[:3].lower() in _MONTHS:
            return _with_year(int(m.group(2)), _MONTHS[m.group(1)[:3].lower()], m.group(3), reference), m.span()
    return None, None


def _with_year(day, month, year, reference):
    """Build a date; a missing year means the next one on/after 2 months ago."""
    if year:
        y = int(year)
        return _safe_date(y + 2000 if y < 100 else y, month, day)
    for y in (reference.year, reference.year + 1):
        d = _safe_date(y, month, day)
        if d and d >= reference - timedelta(days=61):
            return d
    return None


def _safe_date(year, month, day):
    """A date, or None if the numbers don't make one (e.g. 31 Feb)."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def travel(data):
    """
    Travel label: name, address, phone, then the flights. Monospaced so
    times line up.
    data: name, address, phone, and either
          legs    - a list of flights (see above): sorted, formatted with
                    the template and split into journeys automatically, or
          flights - text exactly as typed (blank lines between journeys).
    """
    header = [data.get("name", ""), data.get("address", ""), data.get("phone", "")]
    header = [h.strip() for h in header if h and h.strip()]
    if data.get("legs"):
        flights = format_legs(data["legs"])
    else:
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


# "freezer" is the old name of the food label, kept for existing API callers
RENDERERS = {"address": address, "food": food, "freezer": food, "travel": travel,
             "battery": battery, "network": network}


# Printers refuse continuous labels shorter than their minimum: 150 dots
# (12.7mm) on most models, ~300 dots (25mm) on some (see printer.py).
# Short labels (e.g. battery) are padded to that, content centred.
MIN_LENGTH = 150


def render(kind, data, tz="UTC", min_length=MIN_LENGTH, temp_unit="C"):
    """Render a label of the given kind. Raises KeyError for an unknown kind.

    tz:         IANA time zone name (e.g. "Europe/London") used for "today".
    temp_unit:  "C" or "F", for cooking temperatures on food labels.
    min_length: shortest label the chosen printer model accepts, in dots;
                shorter labels are padded top and bottom to this length.
    """
    token = _tz.set(tz or "UTC")
    unit_token = _unit.set("F" if temp_unit == "F" else "C")
    try:
        img = RENDERERS[kind](data or {})
    finally:
        _tz.reset(token)
        _unit.reset(unit_token)
    min_length = max(MIN_LENGTH, int(min_length or MIN_LENGTH))
    if img.height < min_length:
        padded = Image.new("L", (img.width, min_length), 255)
        padded.paste(img, (0, (min_length - img.height) // 2))
        img = padded
    return img.convert("1", dither=Image.Dither.NONE).convert("L")
