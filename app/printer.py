# ------------------------------------------------------------------
# labelprinter - send a rendered label to the Brother QL-810W
# Date: 2026-11-07 18:10 GMT
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# Uses brother_ql_next (a maintained fork of brother_ql) to turn an
# image into the printer's raster commands and send them over the
# network to port 9100.
# ------------------------------------------------------------------
import os
import socket
import threading

from brother_ql.backends.helpers import send
from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster

# Settings come from docker-compose environment variables
PRINTER = os.environ.get("PRINTER", "tcp://192.168.1.20:9100")
MODEL = os.environ.get("MODEL", "QL-810W")
LABEL = os.environ.get("LABEL", "62")          # 62mm continuous roll

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


def print_image(image, copies=1):
    """Send an image to the printer. Returns (ok, message)."""
    try:
        instructions = build(image, copies)
    except Exception as exc:  # bad image size etc.
        return False, f"Couldn't prepare the label: {exc}"
    with _lock:
        # The library opens its socket with no time limit, so a firewall that
        # silently drops traffic would hang for minutes. Cap it at 10 seconds.
        previous = socket.getdefaulttimeout()
        socket.setdefaulttimeout(10)
        try:
            result = send(instructions=instructions, printer_identifier=PRINTER,
                          backend_identifier="network", blocking=True)
        except OSError as exc:
            return False, (f"Couldn't reach the printer at {PRINTER} ({exc}). "
                           "Check it's switched on and the firewall allows port 9100.")
        except Exception as exc:
            return False, f"Printing failed: {exc}"
        finally:
            socket.setdefaulttimeout(previous)
    # The network backend can't read printer status, so 'sent' is the best we know
    if isinstance(result, dict) and result.get("outcome") in ("error",):
        return False, "The printer reported an error. Check the roll and cover."
    return True, "Sent to printer"
