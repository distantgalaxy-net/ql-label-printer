# ------------------------------------------------------------------
# labelprinter - is the printer ready, and what roll is loaded?
# Date: 2026-11-09 09:40 GMT
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# check(host, port) answers, without printing anything:
#   1. Can we connect to the printer's printing port (normally 9100)?
#      If not: "Printer unavailable".
#   2. Brother's own status request (ESC i S) on that connection. Over
#      USB every QL answers with a 32-byte status; over the network some
#      models do and some don't, so we wait briefly for a reply. The reply
#      says which roll is loaded and whether the cover is open, the roll
#      has run out, etc. (decoded by brother_ql's interpret_response).
#   3. If (2) gets no reply: SNMP, the standard way network printers
#      report status (UDP port 161, read-only community "public"). We ask
#      for the Printer/Host Resources MIB values for errors (no paper,
#      door open, jammed) and the loaded media's name.
#   If neither (2) nor (3) answers, the printer is reachable but its
#   status is unknown, and printing is allowed.
#
# Everything found is also returned under "detail" (raw bytes in hex,
# SNMP values), so the Settings tab can show exactly what the printer
# said - useful when trying a new model.
#
# Only the 62mm continuous roll (DK-22205) is supported, so any other
# roll is reported as "Fit 62mm continuous label".
# ------------------------------------------------------------------
import random
import re
import select
import socket
import time

from brother_ql.reader import interpret_response

CONNECT_TIMEOUT = 3      # seconds to wait for the printer to accept a connection
REPLY_TIMEOUT = 2        # seconds to wait for a status reply on that connection
SNMP_TIMEOUT = 1.5       # seconds to wait for each SNMP answer
SNMP_COMMUNITY = b"public"
SUPPORTED_WIDTH_MM = 62

# Brother status request: "invalidate" (200 zero bytes), "initialise"
# (ESC @) then "status information request" (ESC i S). Prints nothing.
STATUS_REQUEST = b"\x00" * 200 + b"\x1b\x40" + b"\x1biS"

# Messages shown under the Print button (and the state names the page uses)
MESSAGES = {
    "ready": "Printer ready",
    "unavailable": "Printer unavailable",
    "cover_open": "Printer cover open",
    "no_media": "Label spool finished",
    "wrong_media": "Fit 62mm continuous label",
    "error": "Printer error – check the printer",
}


def check(host, port):
    """Find out whether the printer can print. Returns a dict:

    ok      True if printing should be allowed
    state   ready | unavailable | cover_open | no_media | wrong_media | error
    message the text for the page (see MESSAGES)
    media   e.g. "62mm continuous", or None if the printer didn't say
    source  where the answer came from: connection | printer | snmp
    detail  what the printer actually sent back, for the Settings tab
    """
    detail = {}
    # 1 + 2: connect, then ask for Brother's status on the same connection
    try:
        with socket.create_connection((host, int(port)), timeout=CONNECT_TIMEOUT) as sock:
            raw = _brother_status(sock)
    except OSError as exc:
        detail["connection"] = str(exc)
        return _result("unavailable", source="connection", detail=detail)
    detail["connection"] = "connected"
    detail["status_reply_hex"] = raw.hex(" ") if raw else "(no reply)"
    if raw:
        try:
            return _from_brother(interpret_response(raw), detail)
        except Exception as exc:     # a reply, but not one we understand
            detail["status_reply_error"] = str(exc)

    # 3: SNMP
    snmp = _snmp_status(host)
    detail["snmp"] = snmp or "(no reply)"
    if snmp:
        return _from_snmp(snmp, detail)
    # Reachable, but it won't say more: let the user print
    return _result("ready", source="connection", detail=detail)


def _result(state, media=None, source="connection", detail=None):
    """Build the reply dict for a state."""
    return {"ok": state == "ready", "state": state, "message": MESSAGES[state],
            "media": media, "source": source, "detail": detail or {}}


# ---------------------------------------------------------------- Brother status
def _brother_status(sock):
    """Send Brother's status request and return the 32-byte reply (or b"")."""
    sock.sendall(STATUS_REQUEST)
    data, deadline = b"", time.monotonic() + REPLY_TIMEOUT
    while len(data) < 32:
        wait = deadline - time.monotonic()
        if wait <= 0 or not select.select([sock], [], [], wait)[0]:
            break
        chunk = sock.recv(64)
        if not chunk:
            break
        data += chunk
    # Replies start 80 20 42; skip anything before that
    start = data.find(b"\x80\x20\x42")
    return data[start:start + 32] if start >= 0 and len(data) - start >= 32 else b""


def _from_brother(info, detail):
    """Turn brother_ql's decoded status into our state."""
    detail["printer_reports"] = {k: info.get(k) for k in
                                 ("model_name", "media_type", "media_width", "media_length", "errors", "status_type")}
    errors = " ".join(info.get("errors") or []).lower()
    width, kind = info.get("media_width") or 0, str(info.get("media_type") or "")
    media = None
    if width:
        media = f"{width}mm " + ("continuous" if kind.startswith("Continuous") else
                                 "die-cut labels" if kind.startswith("Die-cut") else kind.lower())
    if "cover" in errors:
        state = "cover_open"
    elif "no media" in errors or "end of media" in errors or "cannot be fed" in errors \
            or "replace media" in errors or kind == "No media":
        state = "no_media"
    elif errors:
        state = "error"
    elif width != SUPPORTED_WIDTH_MM or not kind.startswith("Continuous"):
        state = "wrong_media"
    else:
        state = "ready"
    return _result(state, media=media, source="printer", detail=detail)


# ---------------------------------------------------------------- SNMP
# Standard MIB objects (first row of each table, found with GET-NEXT so the
# printer's own row numbers don't matter):
OIDS = {
    # hrPrinterDetectedErrorState: bit flags (see _from_snmp)
    "error_state": "1.3.6.1.2.1.25.3.5.1.2",
    # hrDeviceStatus: 2 running, 3 warning, 4 testing, 5 down
    "device_status": "1.3.6.1.2.1.25.3.2.1.5",
    # prtInputMediaName: e.g. "62mm" or "DK-22205"
    "media_name": "1.3.6.1.2.1.43.8.2.1.12",
    # prtCoverStatus: 3 open, 4 closed (5/6 interlock open/closed)
    "cover_status": "1.3.6.1.2.1.43.6.1.1.3",
}


def _snmp_status(host):
    """Ask the printer for the OIDS over SNMP v1. Returns {name: value} or {}."""
    found = {}
    try:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.settimeout(SNMP_TIMEOUT)
            for name, oid in OIDS.items():
                answer = _snmp_getnext(sock, host, oid)
                if answer is None and not found:
                    return {}            # first question unanswered: no SNMP
                if answer is not None:
                    found[name] = answer
    except OSError:
        return found
    return found


def _snmp_getnext(sock, host, base_oid):
    """One SNMP v1 GET-NEXT. Returns the value if it's under base_oid, else None."""
    request_id = random.randint(1, 0x7FFFFFFF)
    varbind = _tlv(0x30, _tlv(0x06, _oid(base_oid)) + b"\x05\x00")
    pdu = _tlv(0xA1, _int(request_id) + _int(0) + _int(0) + _tlv(0x30, varbind))
    sock.sendto(_tlv(0x30, _int(0) + _tlv(0x04, SNMP_COMMUNITY) + pdu), (host, 161))
    try:
        data, _ = sock.recvfrom(4096)
    except (socket.timeout, OSError):
        return None
    try:
        oid, value = _parse_response(data, request_id)
    except (ValueError, IndexError):
        return None
    return value if oid.startswith(base_oid + ".") else None


def _tlv(tag, body):
    """BER tag-length-value."""
    n = len(body)
    if n < 0x80:
        length = bytes([n])
    else:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + length + body


def _int(value):
    """BER INTEGER."""
    raw = value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big", signed=True)
    return _tlv(0x02, raw)


def _oid(text):
    """BER-encode a dotted OID's body."""
    parts = [int(p) for p in text.split(".")]
    out = bytes([parts[0] * 40 + parts[1]])
    for p in parts[2:]:
        chunk = [p & 0x7F]
        p >>= 7
        while p:
            chunk.insert(0, 0x80 | (p & 0x7F))
            p >>= 7
        out += bytes(chunk)
    return out


def _read_tlv(data, pos):
    """Read one BER item at pos. Returns (tag, body, next position)."""
    tag, n = data[pos], data[pos + 1]
    pos += 2
    if n & 0x80:
        count = n & 0x7F
        n = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    return tag, data[pos:pos + n], pos + n


def _decode_oid(body):
    """Dotted text from a BER OID body."""
    parts = [str(body[0] // 40), str(body[0] % 40)]
    value = 0
    for b in body[1:]:
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(str(value))
            value = 0
    return ".".join(parts)


def _parse_response(data, request_id):
    """Pull (oid, value) out of an SNMP GetResponse; checks the request id."""
    _, message, _ = _read_tlv(data, 0)
    pos = 0
    for _ in range(2):                       # version, community
        _, _, pos = _read_tlv(message, pos)
    tag, pdu, _ = _read_tlv(message, pos)
    if tag != 0xA2:
        raise ValueError("not a response")
    items, pos = [], 0
    while pos < len(pdu):
        t, body, pos = _read_tlv(pdu, pos)
        items.append((t, body))
    if int.from_bytes(items[0][1], "big", signed=True) != request_id or items[1][1] != b"\x00":
        raise ValueError("wrong reply or SNMP error")
    _, varbind, _ = _read_tlv(items[3][1], 0)
    _, oid_body, pos = _read_tlv(varbind, 0)
    vtag, vbody, _ = _read_tlv(varbind, pos)
    if vtag == 0x02:                         # INTEGER
        value = int.from_bytes(vbody, "big", signed=True)
    elif vtag == 0x04:                       # OCTET STRING: text, or hex for bit flags
        text = vbody.decode("utf-8", "replace")
        value = text if text.isprintable() and text.strip() else vbody.hex()
    else:
        value = vbody.hex()
    return _decode_oid(oid_body), value


def _from_snmp(snmp, detail):
    """Turn SNMP values into our state.

    hrPrinterDetectedErrorState bits (first byte, most significant first):
    lowPaper, noPaper, lowToner, noToner, doorOpen, jammed, offline,
    serviceRequested.
    """
    flags = 0
    raw = snmp.get("error_state")
    if isinstance(raw, str) and re.fullmatch(r"[0-9a-f]+", raw):
        flags = int(raw[:2] or "0", 16)
    media_name = snmp.get("media_name") if isinstance(snmp.get("media_name"), str) else None
    if flags & 0x08 or snmp.get("cover_status") in (3, 5):
        state = "cover_open"
    elif flags & 0x40:
        state = "no_media"
    elif flags & 0x04 or snmp.get("device_status") == 5:
        state = "error"
    elif media_name and _wrong_media(media_name):
        state = "wrong_media"
    else:
        state = "ready"
    return _result(state, media=media_name, source="snmp", detail=detail)


def _wrong_media(name):
    """True if a media name clearly isn't the 62mm continuous roll.

    Names vary by model ("62mm", "DK-22205", "29mm x 90mm"), so only a
    name with a different width, or a die-cut size (W x H), counts as wrong.
    """
    text = name.lower()
    if "22205" in text:
        return False
    sizes = [int(n) for n in re.findall(r"(\d+)\s*mm", text)]
    if re.search(r"\d+\s*(mm)?\s*x\s*\d+", text):
        return True                          # die-cut, e.g. "29x90mm"
    return bool(sizes) and sizes[0] != SUPPORTED_WIDTH_MM
