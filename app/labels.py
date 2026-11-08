# ------------------------------------------------------------------
# labelprinter - label layouts
# Date: 2026-11-08 21:55 GMT (updated; first written 2026-11-07 18:10 GMT)
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
# journeys, and read flights pasted as text).
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


def parse_flights(text, reference=None):
    """Read flights pasted as text, one per line. Returns (legs, unread lines).

    Understands the label template ('1 Mar 0900-1130, XX 0123, AAA-BBB')
    and similar: dates like '1 March', '1 Mar 2027', '01/03/2027' or
    '2027-03-01'; times '0900' or '09:00', optional '+1'; a flight number
    (two letters/digits then 1-4 digits); airports as 'AAA-BBB',
    'AAA > BBB' or 'AAA to BBB'. With no year, the next date on or after
    two months ago is used (so a trip just finished still gets this year).
    """
    reference = reference or today()
    legs, unread = [], []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        d, span = _find_date(line, reference)
        times = re.findall(r"(?<!\d)([01]?\d|2[0-3]):?([0-5]\d)(?!\d)", _strip_date(line, span))
        route = re.search(r"\b([A-Z]{3})\s*(?:-|–|>|→|to)\s*([A-Z]{3})\b", line, re.I)
        flight = re.search(r"\b([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?(\d{1,4})\b(?!\s*:)", line.upper())
        if not d or not (times or route):
            unread.append(raw)
            continue
        dep = f"{times[0][0].zfill(2)}{times[0][1]}" if times else ""
        arr = f"{times[1][0].zfill(2)}{times[1][1]}" if len(times) > 1 else ""
        legs.append({
            "date": d.isoformat(),
            "flight": f"{flight.group(1)} {flight.group(2)}" if flight else "",
            "from": route.group(1).upper() if route else "",
            "to": route.group(2).upper() if route else "",
            "dep": dep, "arr": arr,
            # "+1", or landing earlier in the day than take-off
            "plus1": bool(re.search(r"\+\s?1", line)) or bool(dep and arr and arr < dep),
        })
    return clean_legs(legs), unread


# An optional year after "1 Mar": 19xx/20xx, but not when it's really the
# start of a time range ("1 Mar 2030-2245" is a time, not the year 2030)
_YEAR = r"(?:\s+((?:19|20)\d{2})(?!\d|\s*[-–:]))?\b"


def _find_date(line, reference):
    """The first date in a line of text and where it is: (date, (start, end)).

    Returns (None, None) if there's no date (see parse_flights for formats).
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
    return None, None


def _strip_date(line, span):
    """The line without its date (and flight number), so their digits aren't read as times."""
    if span:
        line = line[:span[0]] + " " + line[span[1]:]
    return re.sub(r"\b([A-Za-z]{2}|[A-Za-z]\d|\d[A-Za-z])\s?\d{1,4}\b", " ", line)


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
