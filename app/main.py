# ------------------------------------------------------------------
# labelprinter - label print service (web page + API)
# Date: 2026-11-10 22:00 GMT (updated; first written 2026-11-07 18:10 GMT)
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# Serves the phone-friendly web page and a small JSON API:
#   GET  /                      web page
#   GET  /theme.css             accent colours (shared with the login page)
#   GET  /api/settings          saved details, presets, lists
#   PUT  /api/settings          save them (whole object)
#   GET  /api/icons             icons for address labels [{name, custom}]
#   GET  /api/icons/<name>      a small PNG of one icon (for the page)
#   POST /api/icons             upload a custom icon (form: name, file)
#   DELETE /api/icons/<name>    delete a custom icon
#   POST /api/travel/parse      pick a flight out of pasted text -> leg
#   GET  /api/addresses         saved address labels: [{id, name}]
#   GET  /api/addresses/<id>    one saved address label
#   PUT  /api/addresses         save (or update, by name) an address label
#   DELETE /api/addresses/<id>  delete a saved address label
#   POST /api/preview/<kind>    PNG preview of a label
#   POST /api/print/<kind>      print it  -> {"ok": bool, "message": str}
#   POST /api/printer/test      check the printer can be reached (no print)
#   GET  /api/printer/status    is it ready, and which roll is loaded? (no print)
#   GET  /api/options           printer models, time zones and the app version
#   GET  /login, POST /api/login, POST /api/logout   optional password
#   PUT  /api/password          set, change or remove the password
# <kind> is address | food | travel | battery | network
# ("freezer" still works as the old name for "food").
# Home Assistant can call /api/print/<kind> with the same JSON.
#
# Optional password (off by default, see auth.py). Without one, keep the
# page on a trusted network only (e.g. NAS-only port + reverse proxy that
# allows only your trusted subnets).
#
# The printer (model, IP address, port) and the time zone are saved from
# the Settings tab (settings.json), not hard-coded, so each install sets
# its own. A printer address is only saved once a test connection to it
# succeeds ("verified"); until then the page and print API stay locked
# to setup, so a new install can't be used before it can actually print.
# ------------------------------------------------------------------
import io
import json
import os
import threading
from zoneinfo import available_timezones

from flask import (Flask, jsonify, redirect, request, send_file,
                   send_from_directory, session)
from waitress import serve

import labels
import printer
from addressbook import AddressBook, AddressBookError
import status as printer_status
from auth import Auth, session_lifetime

DATA_DIR = os.environ.get("DATA_DIR", "/data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
STATIC = os.path.join(os.path.dirname(__file__), "static")


def read_version():
    """The app's version from the VERSION file next to this one (e.g. "1.1.1").

    Test builds add one to the last number; releases are tagged with the
    same number (the Docker Hub workflow checks they match).
    """
    try:
        with open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8") as fh:
            return fh.readline().strip() or "unknown"
    except OSError:
        return "unknown"


APP_VERSION = read_version()

# Starting settings, written on first run; everything is editable in the page
DEFAULT_SETTINGS = {
    "me": {"name": "", "address": "", "phone": ""},
    # Printer: blank address until set in the Settings tab.
    # 9100 is Brother's standard raw printing port.
    # "verified" is set by the server when a connection test passes on save.
    "printer": {"host": "", "port": printer.DEFAULT_PORT, "model": printer.DEFAULT_MODEL,
                "verified": False},
    # IANA time zone name (e.g. "Europe/London"); blank until set. Used for
    # "today" on labels; daylight saving changes are applied automatically.
    "timezone": "",
    # Cooking temperatures on food labels: "C" (°C) or "F" (°F)
    "temp_unit": "C",
    # Page accent colour, one of ACCENTS (chosen in the Settings tab)
    "accent": "green",
    # Saved foods: everything on the form except the date
    "food_presets": [],
    # Saved trips for travel labels: [{"name": ..., "legs": [...]}]
    "trips": [],
    # Reusable notes per page: delivery instructions, cooking notes.
    # Each is {"text": ..., "align": "left" | "center"} (food notes: left)
    "saved_notes": {"address": [], "food": []},
    # Saved battery labels: [{"device": ..., "battery": ...}] (no date)
    "battery_presets": [],
    "battery_types": ["CR2032", "CR2450", "CR2", "CR123A", "AA", "AAA", "9V"],
}

# Accent colours the page offers (shades are in static/theme.css)
ACCENTS = ("green", "blue", "red", "pink", "purple", "orange", "mono")

# Every time zone the container's tz database knows, sorted for the dropdown
TIMEZONES = sorted(available_timezones())

app = Flask(__name__, static_folder=None)
# Largest request accepted (icon uploads), in bytes
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
_settings_lock = threading.Lock()

# ---------------------------------------------------------------- password
auth = Auth(DATA_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
app.secret_key = auth.secret_key()          # signs the login cookie
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,          # scripts in the page can't read it
    SESSION_COOKIE_SAMESITE="Lax",         # not sent on cross-site posts
    PERMANENT_SESSION_LIFETIME=session_lifetime(),
)

# Paths that work without logging in: the login page itself, its colours,
# the login call, and the Docker health check.
OPEN_PATHS = {"/login", "/theme.css", "/api/login", "/health"}


def logged_in():
    """True if no password is set, or this request is logged in.

    A browser is logged in when its session holds the current password
    version; scripts (e.g. Home Assistant) can use HTTP Basic auth instead.
    """
    if not auth.enabled():
        return True
    if session.get("auth") == auth.version():
        return True
    basic = request.authorization
    return bool(basic and basic.password and auth.check(basic.password))


@app.before_request
def require_login():
    """Block everything except OPEN_PATHS until logged in (if a password is set)."""
    if request.path in OPEN_PATHS or logged_in():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": "Password required", "login": True}), 401
    return redirect("/login")


@app.get("/login")
def login_page():
    """The password page (goes straight to the app if no password is set)."""
    if not auth.enabled():
        return redirect("/")
    return send_from_directory(STATIC, "login.html")


@app.post("/api/login")
def login():
    """Check the password and start a 30-day session."""
    body = request.get_json(silent=True) or {}
    if not auth.enabled():
        return jsonify({"ok": True})
    if not auth.check(body.get("password")):
        return jsonify({"ok": False, "message": "Wrong password"}), 401
    session.permanent = True
    session["auth"] = auth.version()
    return jsonify({"ok": True})


@app.post("/api/logout")
def logout():
    """Forget this browser's login."""
    session.clear()
    return jsonify({"ok": True})


@app.put("/api/password")
def change_password():
    """Set, change or remove the password.

    Body: {"current": "...", "new": "..."}. When a password is already set,
    "current" must match (so an unlocked phone can't quietly change it).
    An empty "new" removes the password. This browser stays logged in.
    """
    body = request.get_json(silent=True) or {}
    if auth.enabled() and not auth.check(body.get("current")):
        return jsonify({"ok": False, "message": "Current password is wrong"}), 403
    new = body.get("new") or ""
    if not new:
        auth.remove()
        session.clear()
        return jsonify({"ok": True, "message": "Password removed", "password_set": False})
    err = auth.set_password(new)
    if err:
        return jsonify({"ok": False, "message": err}), 400
    session.permanent = True
    session["auth"] = auth.version()       # keep this browser logged in
    return jsonify({"ok": True, "message": "Password saved", "password_set": True})


def load_settings():
    """Read settings.json, filling in any keys missing from older files."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        saved = {}
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    merged.update(saved)
    # Older files may lack newer printer fields (e.g. model): fill them in
    merged["printer"] = {**DEFAULT_SETTINGS["printer"], **(saved.get("printer") or {})}
    # Older files kept freezer presets: carry them over as frozen foods
    old = merged.pop("freezer_presets", None)
    if old and not saved.get("food_presets"):
        merged["food_presets"] = [{**p, "storage": "frozen", "shelf": p.get("months", ""),
                                   "shelf_unit": "months", "temp": p.get("temp_c", ""),
                                   "fan": p.get("fan_c", ""), "temp_unit": "C"}
                                  for p in old if isinstance(p, dict)]
    merged["saved_notes"] = clean_notes(merged.get("saved_notes"))
    return merged


def clean_notes(notes):
    """Saved notes as {page: [{"text", "align"}]}: known pages only, sensible limits.

    Older saves kept plain text notes; they become left-aligned notes.
    A note saved twice keeps its last alignment.
    """
    notes = notes if isinstance(notes, dict) else {}
    out = {}
    for page in ("address", "food"):
        kept = {}
        for n in notes.get(page) or []:
            if isinstance(n, str):
                n = {"text": n}
            if not isinstance(n, dict):
                continue
            text = str(n.get("text") or "").strip()[:500]
            if text:
                kept[text] = "center" if n.get("align") == "center" else "left"
        out[page] = [{"text": t, "align": a} for t, a in list(kept.items())[:100]]
    return out


def setup_problem(s):
    """Why this install can't print yet (a message), or None if setup is done.

    Setup is done once a printer has been saved after a successful
    connection test, and a time zone has been chosen.
    """
    p = s.get("printer") or {}
    if not p.get("host") or not p.get("verified"):
        return "Setup isn't finished: add the printer in the Settings tab and save (it tests the connection)."
    if not s.get("timezone"):
        return "Setup isn't finished: choose a time zone in the Settings tab."
    return None


def save_settings(data):
    """Write settings.json atomically so a crash can't leave half a file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, SETTINGS_FILE)


@app.get("/")
def index():
    """The web page."""
    return send_from_directory(STATIC, "index.html")


@app.get("/theme.css")
def theme_css():
    """Accent colour shades, used by both the main page and the login page."""
    return send_from_directory(STATIC, "theme.css", mimetype="text/css")


@app.get("/labeldesigner")
def old_link():
    """Keep the old bookmark working."""
    return send_from_directory(STATIC, "index.html")


@app.get("/api/settings")
def get_settings():
    """Return all saved settings, plus whether a password is set (never the hash)."""
    return jsonify({**load_settings(), "password_set": auth.enabled()})


@app.put("/api/settings")
def put_settings():
    """Save the settings sent in the body; only known keys are kept.

    "printer" and "timezone" entries are checked first, so a bad IP
    address, port, model or time zone is refused with a message instead
    of being saved. A new or changed printer address is also connected to
    first: if the printer can't be reached, nothing is saved.
    Replies with the saved settings so the page can see "verified".
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "message": "Expected a JSON object"}), 400
    if "printer" in body:
        p = body["printer"] if isinstance(body["printer"], dict) else {}
        host, port, err = printer.validate_address(p.get("host"), p.get("port"))
        if err:
            return jsonify({"ok": False, "message": err}), 400
        model = p.get("model") or printer.DEFAULT_MODEL
        if model not in printer.NETWORK_MODELS:
            return jsonify({"ok": False, "message": f"'{model}' isn't a supported printer model."}), 400
        # Test the connection unless this exact address was already verified
        saved = load_settings()["printer"]
        if not (saved.get("verified") and saved.get("host") == host and saved.get("port") == port):
            ok, message = printer.test_connection(host, port)
            if not ok:
                return jsonify({"ok": False, "message": f"Not saved. {message}"}), 400
        body["printer"] = {"host": host, "port": port, "model": model, "verified": True}
    if "timezone" in body and body["timezone"] not in TIMEZONES:
        return jsonify({"ok": False, "message": f"'{body['timezone']}' isn't a known time zone."}), 400
    if "accent" in body and body["accent"] not in ACCENTS:
        return jsonify({"ok": False, "message": f"'{body['accent']}' isn't one of the colours."}), 400
    if "temp_unit" in body and body["temp_unit"] not in ("C", "F"):
        return jsonify({"ok": False, "message": "The temperature unit must be C or F."}), 400
    for key in ("food_presets", "trips", "battery_types", "battery_presets"):
        if key in body and not isinstance(body[key], list):
            return jsonify({"ok": False, "message": f"'{key}' must be a list."}), 400
    if "saved_notes" in body:
        # {page: [note, ...]}: known pages only, text notes, sensible limits
        if not isinstance(body["saved_notes"], dict):
            return jsonify({"ok": False, "message": "'saved_notes' must be an object."}), 400
        body["saved_notes"] = clean_notes(body["saved_notes"])
    if "battery_presets" in body:
        # Saved battery labels: a device name and a battery type, nothing else
        body["battery_presets"] = [{"device": str(b.get("device") or "").strip()[:100],
                                    "battery": str(b.get("battery") or "").strip()[:40]}
                                   for b in body["battery_presets"]
                                   if isinstance(b, dict) and str(b.get("device") or "").strip()][:500]
    if "trips" in body:
        # Keep saved trips tidy: a name and well-formed flights only
        body["trips"] = [{"name": str(t.get("name") or "").strip()[:60],
                          "legs": labels.clean_legs(t.get("legs"))}
                         for t in body["trips"] if isinstance(t, dict) and str(t.get("name") or "").strip()]
    with _settings_lock:
        merged = load_settings()
        merged.update({k: v for k, v in body.items() if k in DEFAULT_SETTINGS})
        save_settings(merged)
    return jsonify({"ok": True, "settings": merged})


@app.get("/api/options")
def options():
    """Choices for the Settings tab: printer models, time zone names and the version."""
    return jsonify({"models": printer.supported_models(), "timezones": TIMEZONES, "version": APP_VERSION})


@app.get("/api/icons")
def icons():
    """List the icons available for address labels: [{name, custom}]."""
    return jsonify(labels.list_icons())


@app.get("/api/icons/<name>")
def icon_image(name):
    """A 128-dot PNG of one icon, so the page can show what it looks like."""
    img = labels.load_icon(name, 128)
    if img is None:
        return jsonify({"ok": False, "message": "No such icon"}), 404
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", max_age=0)


@app.post("/api/icons")
def upload_icon():
    """Save an uploaded picture as a custom icon (multipart form: name, file).

    The picture is converted to a black-and-white square in /data/icons.
    A name already used (by your icons or a built-in one) is refused.
    """
    upload = request.files.get("file")
    if not upload:
        return jsonify({"ok": False, "message": "Choose a picture first."}), 400
    name, err = labels.save_custom_icon(request.form.get("name"), upload.stream)
    if err:
        return jsonify({"ok": False, "message": err}), 400
    return jsonify({"ok": True, "message": f"Icon “{name}” saved", "name": name,
                    "icons": labels.list_icons()})


@app.delete("/api/icons/<name>")
def delete_icon(name):
    """Delete a custom icon (built-in icons can't be deleted)."""
    if not labels.delete_custom_icon(name):
        return jsonify({"ok": False, "message": "That isn't a custom icon."}), 404
    return jsonify({"ok": True, "message": f"Icon “{name}” deleted", "icons": labels.list_icons()})


@app.errorhandler(413)
def too_large(_err):
    """Reply in JSON when an upload is bigger than MAX_CONTENT_LENGTH."""
    return jsonify({"ok": False, "message": "That file is too big (10 MB at most)."}), 413


# ---------------------------------------------------------------- saved addresses
# Encrypted on disk (see addressbook.py); behind the optional password like
# every other /api/ call. Kept out of /api/settings on purpose.
address_book = AddressBook(DATA_DIR)


def _book_error(exc):
    """Reply when the saved addresses can't be read."""
    return jsonify({"ok": False, "message": str(exc)}), 500


@app.get("/api/addresses")
def list_addresses():
    """Names of the saved address labels (no addresses), for the page's list."""
    try:
        return jsonify({"ok": True, "addresses": address_book.names()})
    except AddressBookError as exc:
        return _book_error(exc)


@app.get("/api/addresses/<entry_id>")
def get_address(entry_id):
    """One saved address label: name, address, icon, note, note_align."""
    try:
        entry = address_book.get(entry_id)
    except AddressBookError as exc:
        return _book_error(exc)
    if not entry:
        return jsonify({"ok": False, "message": "That saved address label isn't there any more."}), 404
    return jsonify({"ok": True, "address": entry})


@app.put("/api/addresses")
def save_address():
    """Save an address label under its name (updates one already saved with that name)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "message": "Expected a JSON object"}), 400
    try:
        entry, updated, err = address_book.save(body)
    except AddressBookError as exc:
        return _book_error(exc)
    if err:
        return jsonify({"ok": False, "message": err}), 400
    return jsonify({"ok": True, "id": entry["id"], "updated": updated,
                    "message": f"{'Updated' if updated else 'Saved'} the address label for “{entry['name']}”",
                    "addresses": address_book.names()})


@app.delete("/api/addresses/<entry_id>")
def delete_address(entry_id):
    """Delete a saved address label."""
    try:
        name = address_book.delete(entry_id)
    except AddressBookError as exc:
        return _book_error(exc)
    if not name:
        return jsonify({"ok": False, "message": "That saved address label isn't there any more."}), 404
    return jsonify({"ok": True, "message": f"Deleted the saved address label for “{name}”", "addresses": address_book.names()})


@app.post("/api/travel/parse")
def travel_parse():
    """Pick one flight out of pasted text (e.g. a booking confirmation).

    Body {"text": ...} -> {"ok", "leg", "missing", "more"}; the page fills
    its flight boxes with "leg" so the user can check it before adding.
    Years left out of dates are filled in using today's date in the
    Settings time zone.
    """
    text = (request.get_json(silent=True) or {}).get("text") or ""
    ref = labels.today(load_settings().get("timezone") or "UTC")
    leg, missing, more = labels.parse_flight(str(text)[:20000], reference=ref)
    if not leg:
        return jsonify({"ok": False, "message": "Couldn't find a flight in that text. Check it has a date, a flight number, airports or times."}), 400
    return jsonify({"ok": True, "leg": leg, "missing": missing, "more": more})


def _render_from_request(kind):
    """Render the label described by the request body, or return an error response."""
    if kind not in labels.RENDERERS:
        return None, (jsonify({"ok": False, "message": f"Unknown label type '{kind}'"}), 404)
    data = request.get_json(silent=True) or {}
    s = load_settings()
    try:
        # Time zone for "today", and the shortest label the chosen model accepts
        return labels.render(kind, data, tz=s.get("timezone") or "UTC",
                             min_length=printer.min_length(s["printer"].get("model")),
                             temp_unit=s.get("temp_unit") or "C"), None
    except Exception as exc:
        return None, (jsonify({"ok": False, "message": f"Couldn't lay out the label: {exc}"}), 400)


@app.post("/api/preview/<kind>")
def preview(kind):
    """Render a label and return it as a PNG for the page's preview."""
    img, err = _render_from_request(kind)
    if err:
        return err
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    resp = send_file(buf, mimetype="image/png")
    # Label length in mm, so the page can show it
    resp.headers["X-Label-Length-mm"] = f"{img.height / labels.DOTS_PER_MM:.0f}"
    return resp


@app.post("/api/print/<kind>")
def do_print(kind):
    """Render a label and send it to the printer saved in settings.

    Just before sending, the printer's status is checked (status.py). If it
    reports a problem (unavailable, cover open, no roll, wrong roll, error)
    nothing is sent: the reply is 409 with the reason and the full status
    under "printer", so the page can disable Print. A printer that can't
    report its status is printed to as before. Applies to Home Assistant too.
    """
    problem = setup_problem(load_settings())
    if problem:
        return jsonify({"ok": False, "message": problem}), 409
    img, err = _render_from_request(kind)
    if err:
        return err
    copies = (request.get_json(silent=True) or {}).get("copies", 1)
    try:
        copies = max(1, min(20, int(copies)))
    except (TypeError, ValueError):
        copies = 1
    target = load_settings()["printer"]
    # Check first, so a label isn't sent into an open or empty printer
    # (the printer can't tell us afterwards whether a label came out)
    with printer.job_lock():
        state = printer_status.check(target.get("host"), target.get("port") or printer.DEFAULT_PORT)
    if not state["ok"]:
        return jsonify({"ok": False, "message": f"Not printed: {state['message']}", "printer": state}), 409
    ok, message = printer.print_image(img, target.get("host"), target.get("port"),
                                      target.get("model"), copies)
    return jsonify({"ok": ok, "message": message}), (200 if ok else 502)


@app.post("/api/printer/test")
def test_printer():
    """Try to connect to a printer without printing anything.

    Uses the host/port in the body (so the Settings tab can test before
    saving), or the saved printer if the body has none.
    """
    body = request.get_json(silent=True) or {}
    if not body.get("host"):
        body = load_settings().get("printer") or {}
    ok, message = printer.test_connection(body.get("host"), body.get("port"))
    return jsonify({"ok": ok, "message": message}), (200 if ok else 502)


@app.get("/api/printer/status")
def get_printer_status():
    """Is the saved printer ready to print, and which roll is loaded?

    Checks the connection, then asks the printer for its status (see
    status.py). Prints nothing. The page uses this to disable Print with
    a message such as "Printer cover open"; "detail" holds what the
    printer actually said, shown in the Settings tab.
    """
    target = load_settings()["printer"]
    if not target.get("host"):
        return jsonify({"ok": False, "state": "unavailable", "message": "No printer set up yet",
                        "media": None, "source": "settings", "detail": {}})
    # Wait for any print job to finish first, so the two never overlap
    with printer.job_lock():
        result = printer_status.check(target.get("host"), target.get("port") or printer.DEFAULT_PORT)
    return jsonify(result)


@app.get("/health")
def health():
    """Health check used by the Docker HEALTHCHECK (also says which version is running)."""
    return jsonify({"ok": True, "version": APP_VERSION})


if __name__ == "__main__":
    os.makedirs(os.path.join(DATA_DIR, "icons"), exist_ok=True)
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
    if auth.reset_from_env():
        print("RESET_PASSWORD is set: the password has been removed. "
              "Take RESET_PASSWORD out of docker-compose.yml now.", flush=True)
    print(f"LabelPrinter {APP_VERSION} starting", flush=True)
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8013")))
