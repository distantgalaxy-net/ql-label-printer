# ------------------------------------------------------------------
# labelprinter - send a rendered label to the Brother QL-810W
# Date: 2026-11-07 19:44 GMT (updated; first written 18:10 GMT)
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# Uses brother_ql_next (a maintained fork of brother_ql) to turn an
# image into the printer's raster commands and send them over the
# network (raw TCP, normally port 9100).
#
# The printer's IP address and port are NOT set here: they are saved
# from the web page's Settings tab (settings.json) and passed in by
# main.py, so nothing about a particular home network is in the code.
# ------------------------------------------------------------------
import ipaddress
import os
import re
import socket
import threading

from brother_ql.backends.helpers import send
from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster

# Printer model and roll come from docker-compose environment variables
# (they describe the hardware, not the network, so they have safe defaults)
MODEL = os.environ.get("MODEL", "QL-810W")
LABEL = os.environ.get("LABEL", "62")          # 62mm continuous roll

DEFAULT_PORT = 9100        # Brother's standard raw printing port
CONNECT_TIMEOUT = 10       # seconds before we give up on the printer

# A hostname such as "printer.lan": letters, digits and hyphens per part
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")

# Only one job talks to the printer at a time
_lock = threading.Lock()


def build(image, copies=1):
    """Convert an image into QL raster instructions (bytes)."""
    qlr = BrotherQLRaster(MODEL)
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


def _unreachable(host, port, exc):
    """Friendly message for a failed connection, with the cause in brackets."""
    return (f"Couldn't reach the printer at {host}:{port} ({exc}). "
            f"Check it's switched on and the firewall allows port {port}.")


def print_image(image, host, port=DEFAULT_PORT, copies=1):
    """Send an image to the printer at host:port. Returns (ok, message).

    host/port come from the saved settings. If no printer has been set up yet
    the caller gets a message pointing at the Settings tab instead.
    """
    if not (host or "").strip():
        return False, "No printer set up yet. Add its IP address in the Settings tab."
    host, port, err = validate_address(host, port)
    if err:
        return False, f"Printer settings problem: {err}"
    try:
        instructions = build(image, copies)
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
