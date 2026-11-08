# ------------------------------------------------------------------
# labelprinter - send a rendered label to a Brother QL printer
# Date: 2026-11-08 16:01 GMT (updated; first written 2026-11-07 18:10 GMT)
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# Uses brother_ql_next (a maintained fork of brother_ql) to turn an
# image into the printer's raster commands and send them over the
# network (raw TCP, normally port 9100).
#
# The printer's model, IP address and port are NOT set here: they are
# saved from the web page's Settings tab (settings.json "printer") and
# passed in by main.py, so nothing about a particular home is in the code.
#
# Only the 62mm continuous roll (DK-22205) is supported: every label
# layout is drawn 696 dots wide to fit it.
# ------------------------------------------------------------------
import ipaddress
import os
import re
import socket
import threading

from brother_ql.backends.helpers import send
from brother_ql.conversion import convert
from brother_ql.models import ALL_MODELS
from brother_ql.raster import BrotherQLRaster

LABEL = "62"               # 62mm continuous roll - the only one supported
DEFAULT_PORT = 9100        # Brother's standard raw printing port
DEFAULT_MODEL = "QL-810W"  # the model this was built and tested on
CONNECT_TIMEOUT = 10       # seconds before we give up on the printer

# Brother QL models that can print over a network (built-in Wi-Fi or
# Ethernet). USB-only models can't be reached by this service.
NETWORK_MODELS = ["QL-580N", "QL-710W", "QL-720NW", "QL-810W", "QL-820NWB",
                  "QL-1060N", "QL-1100NWB", "QL-1110NWB", "QL-1115NWB"]

# Shortest continuous label each model accepts, in dots (from brother_ql).
# Most take 150 dots (12.7mm); some older/wide models need ~295-301 (25mm).
_MIN_LENGTH = {m.identifier: m.min_max_length_dots[0] for m in ALL_MODELS}

# A hostname such as "printer.lan": letters, digits and hyphens per part
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")

# Only one job talks to the printer at a time
_lock = threading.Lock()


def supported_models():
    """List the selectable models with their minimum label length (for the page)."""
    return [{"id": m, "min_length_mm": round(_MIN_LENGTH[m] / (300 / 25.4), 1)}
            for m in NETWORK_MODELS]


def check_model(model):
    """Return the model if it's one we support, else the default (QL-810W)."""
    return model if model in NETWORK_MODELS else DEFAULT_MODEL


def min_length(model):
    """Shortest label (in dots) the given model will accept."""
    return _MIN_LENGTH.get(check_model(model), 150)


def build(image, model=DEFAULT_MODEL, copies=1):
    """Convert an image into QL raster instructions (bytes) for the given model."""
    qlr = BrotherQLRaster(check_model(model))
    qlr.exception_on_warning = True
    return convert(
        qlr=qlr,
        images=[image] * max(1, int(copies)),
        label=LABEL,
        rotate="0",        # never landscape: image width = roll width
        threshold=70.0,
        dither=False,
        compress=False,
        red=False,         # black/white roll
        dpi_600=False,
        hq=True,
        cut=True,          # cut after each label
    )


def validate_address(host, port):
    """Check a printer host and port from the Settings tab.

    host may be an IPv4/IPv6 address or a hostname; port must be 1-65535.
    Returns (host, port, None) cleaned up, or (None, None, error message).
    """
    host = (host or "").strip()
    if not host:
        return None, None, "Enter the printer's IP address."
    try:
        ipaddress.ip_address(host)
    except ValueError:
        # Numbers and dots only (e.g. 192.168.1.300) is a mistyped IP, not a hostname
        if re.fullmatch(r"[\d.]+", host) or not _HOSTNAME.match(host):
            return None, None, f"'{host}' isn't a valid IP address or hostname."
    try:
        port = int(port if port not in (None, "") else DEFAULT_PORT)
    except (TypeError, ValueError):
        return None, None, "The port must be a number."
    if not 1 <= port <= 65535:
        return None, None, "The port must be between 1 and 65535."
    return host, port, None


def _identifier(host, port):
    """Build the 'tcp://host:port' string brother_ql expects (IPv6 in brackets)."""
    shown = f"[{host}]" if ":" in host else host
    return f"tcp://{shown}:{port}"


def _unreachable(host, port, exc):
    """Friendly message for a failed connection, with the cause in brackets."""
    return (f"Couldn't reach the printer at {host}:{port} ({exc}). "
            f"Check it's switched on and the firewall allows port {port}.")


def test_connection(host, port):
    """Open (and close) a TCP connection to the printer without printing.

    Used by the Settings tab's "Test connection" button. Returns (ok, message).
    """
    host, port, err = validate_address(host, port)
    if err:
        return False, err
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            pass
    except OSError as exc:
        return False, _unreachable(host, port, exc)
    return True, f"Connected to the printer at {host}:{port}"


def local_address(towards=None):
    """Best guess at this server's own IP address, or None.

    Asks the operating system which local address it would use to reach
    `towards` (the printer, if set). A UDP "connect" sends nothing.
    Also reports whether we're inside Docker, where this is the container's
    internal address rather than the NAS's.
    """
    target = towards or "192.0.2.1"   # a documentation-only address, never used
    try:
        family = socket.AF_INET6 if ":" in target else socket.AF_INET
        with socket.socket(family, socket.SOCK_DGRAM) as s:
            s.connect((target, 9))
            ip = s.getsockname()[0]
    except OSError:
        ip = None
    return {"ip": ip, "in_docker": os.path.exists("/.dockerenv")}


def print_image(image, host, port=DEFAULT_PORT, model=DEFAULT_MODEL, copies=1):
    """Send an image to the printer at host:port. Returns (ok, message).

    host/port/model come from the saved settings. If no printer has been set
    up yet the caller gets a message pointing at the Settings tab instead.
    """
    if not (host or "").strip():
        return False, "No printer set up yet. Add its IP address in the Settings tab."
    host, port, err = validate_address(host, port)
    if err:
        return False, f"Printer settings problem: {err}"
    try:
        instructions = build(image, model, copies)
    except Exception as exc:  # bad image size etc.
        return False, f"Couldn't prepare the label: {exc}"
    with _lock:
        # The library opens its socket with no time limit, so a firewall that
        # silently drops traffic would hang for minutes. Cap it at 10 seconds.
        previous = socket.getdefaulttimeout()
        socket.setdefaulttimeout(CONNECT_TIMEOUT)
        try:
            result = send(instructions=instructions, printer_identifier=_identifier(host, port),
                          backend_identifier="network", blocking=True)
        except OSError as exc:
            return False, _unreachable(host, port, exc)
        except Exception as exc:
            return False, f"Printing failed: {exc}"
        finally:
            socket.setdefaulttimeout(previous)
    # The network backend can't read printer status, so 'sent' is the best we know
    if isinstance(result, dict) and result.get("outcome") in ("error",):
        return False, "The printer reported an error. Check the roll and cover."
    return True, "Label sent to printer"
