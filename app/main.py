# ------------------------------------------------------------------
# labelprinter - label print service (web page + API)
# Date: 2026-11-08 09:38 GMT (updated; first written 2026-11-07 18:10 GMT)
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# Serves the phone-friendly web page and a small JSON API:
#   GET  /                      web page
#   GET  /api/settings          saved details, presets, lists
#   PUT  /api/settings          save them (whole object)
#   GET  /api/icons             icon names for address labels
#   POST /api/preview/<kind>    PNG preview of a label
#   POST /api/print/<kind>      print it  -> {"ok": bool, "message": str}
#   POST /api/printer/test      check the printer can be reached (no print)
#   GET  /api/options           printer models, time zones, this server's IP
# <kind> is address | freezer | travel | battery | network.
# Home Assistant can call /api/print/<kind> with the same JSON.
#
# No login: keep it on the home network (NAS-only port + trusted-only
# reverse proxy).
#
# The printer (model, IP address, port) and the time zone are saved from
# the Settings tab (settings.json), not hard-coded, so each install sets
# its own.
# ------------------------------------------------------------------
import io
import json
import os
import threading
from zoneinfo import available_timezones

from flask import Flask, jsonify, request, send_file, send_from_directory
from waitress import serve

import labels
import printer

DATA_DIR = os.environ.get("DATA_DIR", "/data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
STATIC = os.path.join(os.path.dirname(__file__), "static")

# Starting settings, written on first run; everything is editable in the page
DEFAULT_SETTINGS = {
    "me": {"name": "", "address": "", "phone": ""},
    # Printer: blank address until set in the Settings tab.
    # 9100 is Brother's standard raw printing port.
    "printer": {"host": "", "port": printer.DEFAULT_PORT, "model": printer.DEFAULT_MODEL},
    # IANA time zone name (e.g. "Europe/London"); blank until set. Used for
    # "today" on labels; daylight saving changes are applied automatically.
    "timezone": "",
    "freezer_presets": [],
    "battery_types": ["CR2032", "CR2450", "CR2", "CR123A", "AA", "AAA", "9V"],
}

# Every time zone the container's tz database knows, sorted for the dropdown
TIMEZONES = sorted(available_timezones())

app = Flask(__name__, static_folder=None)
_settings_lock = threading.Lock()


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
    return merged


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


@app.get("/labeldesigner")
def old_link():
    """Keep the old bookmark working."""
    return send_from_directory(STATIC, "index.html")


@app.get("/api/settings")
def get_settings():
    """Return all saved settings (details, presets, lists, printer address)."""
    return jsonify(load_settings())


@app.put("/api/settings")
def put_settings():
    """Save the settings sent in the body; only known keys are kept.

    "printer" and "timezone" entries are checked first, so a bad IP
    address, port, model or time zone is refused with a message instead
    of being saved.
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
        body["printer"] = {"host": host, "port": port, "model": model}
    if "timezone" in body and body["timezone"] not in TIMEZONES:
        return jsonify({"ok": False, "message": f"'{body['timezone']}' isn't a known time zone."}), 400
    with _settings_lock:
        merged = load_settings()
        merged.update({k: v for k, v in body.items() if k in DEFAULT_SETTINGS})
        save_settings(merged)
    return jsonify({"ok": True})


@app.get("/api/options")
def options():
    """Choices for the Settings tab, plus what we can tell about this server.

    server.ip is this machine's address as seen from inside; when running in
    Docker (bridge network) that's the container's internal address, and the
    printer will see connections from the NAS's own IP instead.
    """
    host = load_settings()["printer"].get("host") or None
    return jsonify({
        "models": printer.supported_models(),
        "timezones": TIMEZONES,
        "server": {**printer.local_address(host), "port": int(os.environ.get("PORT", "8013"))},
    })


@app.get("/api/icons")
def icons():
    """List the icon names available for address labels."""
    return jsonify(labels.list_icons())


def _render_from_request(kind):
    """Render the label described by the request body, or return an error response."""
    if kind not in labels.RENDERERS:
        return None, (jsonify({"ok": False, "message": f"Unknown label type '{kind}'"}), 404)
    data = request.get_json(silent=True) or {}
    s = load_settings()
    try:
        # Time zone for "today", and the shortest label the chosen model accepts
        return labels.render(kind, data, tz=s.get("timezone") or "UTC",
                             min_length=printer.min_length(s["printer"].get("model"))), None
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
    """Render a label and send it to the printer saved in settings."""
    img, err = _render_from_request(kind)
    if err:
        return err
    copies = (request.get_json(silent=True) or {}).get("copies", 1)
    try:
        copies = max(1, min(20, int(copies)))
    except (TypeError, ValueError):
        copies = 1
    target = load_settings()["printer"]
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


@app.get("/health")
def health():
    """Health check used by the Docker HEALTHCHECK."""
    return jsonify({"ok": True})


if __name__ == "__main__":
    os.makedirs(os.path.join(DATA_DIR, "icons"), exist_ok=True)
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8013")))
