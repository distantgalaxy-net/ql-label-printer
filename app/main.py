# ------------------------------------------------------------------
# labelprinter - label print service (web page + API)
# Date: 2026-11-07 18:10 GMT
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# Serves the phone-friendly web page and a small JSON API:
#   GET  /                      web page
#   GET  /api/settings          saved details, presets, lists
#   PUT  /api/settings          save them (whole object)
#   GET  /api/icons             icon names for address labels
#   POST /api/preview/<kind>    PNG preview of a label
#   POST /api/print/<kind>      print it  -> {"ok": bool, "message": str}
# <kind> is address | freezer | travel | battery | network.
# Home Assistant can call /api/print/<kind> with the same JSON.
#
# No login: keep it on the home network (NAS-only port + trusted-only
# reverse proxy).
# ------------------------------------------------------------------
import io
import json
import os
import threading

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
    "freezer_presets": [],
    "battery_types": ["CR2032", "CR2450", "CR2", "CR123A", "AA", "AAA", "9V"],
    "vlans": [
        "1 · Default", "10 · IoT", "20 · Cameras", "30 · Management",
        "40 · Servers", "50 · Guest", "60 · Trusted", "70 · Printers",
    ],
}

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
    return jsonify(load_settings())


@app.put("/api/settings")
def put_settings():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "message": "Expected a JSON object"}), 400
    with _settings_lock:
        merged = load_settings()
        merged.update({k: v for k, v in body.items() if k in DEFAULT_SETTINGS})
        save_settings(merged)
    return jsonify({"ok": True})


@app.get("/api/icons")
def icons():
    return jsonify(labels.list_icons())


def _render_from_request(kind):
    """Render the label described by the request body, or return an error response."""
    if kind not in labels.RENDERERS:
        return None, (jsonify({"ok": False, "message": f"Unknown label type '{kind}'"}), 404)
    data = request.get_json(silent=True) or {}
    try:
        return labels.render(kind, data), None
    except Exception as exc:
        return None, (jsonify({"ok": False, "message": f"Couldn't lay out the label: {exc}"}), 400)


@app.post("/api/preview/<kind>")
def preview(kind):
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
    img, err = _render_from_request(kind)
    if err:
        return err
    copies = (request.get_json(silent=True) or {}).get("copies", 1)
    try:
        copies = max(1, min(20, int(copies)))
    except (TypeError, ValueError):
        copies = 1
    ok, message = printer.print_image(img, copies)
    return jsonify({"ok": ok, "message": message}), (200 if ok else 502)


@app.get("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    os.makedirs(os.path.join(DATA_DIR, "icons"), exist_ok=True)
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8013")))
