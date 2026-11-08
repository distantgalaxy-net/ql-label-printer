# Development guide – LabelPrinter

Read this before changing the code. It explains what we're building, the decisions already made
and the constraints that aren't obvious from the code.

_Last updated: 2026-11-08 09:38 GMT · Owner: Ash @ Distant Galaxy (@distantgalaxy-net)_

---

## What this is

A small self-hosted service that prints labels on Ash's **Brother QL-810W**
from his phone (primary) and from Home Assistant. It replaces the Brother
iPrint&Label app for the label types he uses regularly, and adds labels that
can be filled in from data he already has (Google Contacts, UniFi, HA).

The container is called **labelprinter**.

## Current state

**Phase 1 – built (this repo):**
- Flask web page + JSON API, rendered with Pillow, printed with `brother_ql_next`.
- Label types: `address` (optional icon), `freezer` (presets, use-by, cooking
  instructions), `travel` (saved details + flights), `battery` (tiny),
  `network` (name/IP/VLAN/MAC).
- Settings/presets persist in `/data/settings.json` (git-ignored), including
  the printer's model, IP address and port and the time zone, entered in the
  page's **Settings** tab. `docker-compose.yml` only holds the web port.

**Phase 2 – planned, not urgent (don't start without Ash asking):**
- Address lookup from **Google Contacts** (People API, via Ash's existing
  Google Cloud project).
- **Guest Wi-Fi**: Ash prefers **per-guest UniFi hotspot vouchers** printed as
  QR/code labels. Details still to be worked out.
- Pick **network devices** and **battery devices** from Home Assistant
  (battery labels must still work for devices not in HA).

## Hard constraints

- **Roll:** 62mm **continuous** black/white (DK-22205) is the **only**
  supported roll (Ash uses only this; layouts are drawn 696 dots wide).
- **Models:** network-capable Brother QL models only (`printer.NETWORK_MODELS`),
  chosen in Settings. Only the QL-810W is tested on hardware. Minimum label
  length comes from the model (150 dots on most, ~300 on QL-1060N/QL-11xx).
- **Orientation:** label width is always the roll width; length grows with
  content. **Never landscape.** Images are **696 dots wide** (300 dpi), `rotate="0"`.
- **Minimum length:** printers reject continuous labels shorter than their
  minimum (QL-810W: **150 dots / 12.7mm**). `labels.render()` pads short
  labels to `printer.min_length(model)`; keep that.
- **Dates:** "today" uses the IANA time zone from Settings (`zoneinfo` +
  the image's `tzdata`), so DST is automatic. No `TZ` env var.
- **Black/white only** (`red=False`). Red would need DK-22251 rolls.
- **Printer** is on the network, raw TCP port **9100**. Its IP address and
  port are set in the **Settings** tab (`settings.json` → `printer`), never in
  code, Docker files or as examples. Editor Lite must be off.
- `brother_ql`'s socket has no connect timeout; `printer.py` caps it at 10 s so
  a firewall drop returns an error instead of hanging. Keep that.

## Network & security (important)

Ash runs a segmented UniFi network:

| VLAN | Subnet | Role |
|---|---|---|
| 6 DMZ | 192.168.1.0/24 | NAS (192.168.1.10) |
| 8 Trusted | 192.168.1.0/24 | Ash's phones/laptops |
| 9 IoT | 192.168.1.0/24 | the printer |
| OpenVPN | 10.0.0.0/24 | remote access to the NAS |

Other VLANs (Surveillance, Guest, Management, Default) must **not**
reach this service.

How it's locked down – don't weaken any of this:
- The service has **no login**. It must stay home-network only.
- Container port is bound to **`127.0.0.1:8013`** (NAS-only).
- Web access is via DSM reverse proxy: `http://labels.home.example`
  → `localhost:8013`, with access profile **"Trusted only"**
  (allow 192.168.1.0/24 and 10.0.0.0/24, deny all). DNS for that name is an
  **A record to 192.168.1.10**, so it isn't reachable from the internet.
  Plain HTTP on purpose (a public cert would need internet exposure).
- UniFi policy "NAS → Printer": allow 192.168.1.10 → 192.168.1.20 TCP 9100,
  Connection State **All** (not "Return Traffic").
- Never commit personal data – including in placeholders/examples (use
  generic ones like "Alex Example", "1 High Street", `192.168.1.20`). `data/settings.json` (Ash's address/phone,
  presets) and custom icons are git-ignored.

## Where it runs

- Synology **NAS** (x86_64, DSM 7.2), **Container Manager** project
  `labelprinter` in `docker/labelprinter`, built from this repo's `Dockerfile`.
- **Home Assistant** runs as a container named **homeassistant**, *host networking*,
  so it calls the API at `http://127.0.0.1:8013/api/print/<type>`.
  HA is "Home Assistant Container" (no add-ons/Supervisor).

## Code layout

```
app/main.py        Flask routes, settings load/save (atomic write)
app/labels.py      All label layouts + built-in icons (drawn with Pillow)
app/printer.py     Image -> QL raster -> send to printer
app/static/index.html  Phone-first page (vanilla JS, no build step)
Dockerfile, docker-compose.yml, requirements.txt (pinned)
```

Adding a label type = a function in `labels.py` registered in `RENDERERS`,
plus a `<form data-kind="...">` and tab in `index.html`. The API picks it up
automatically.

## Conventions Ash wants

- **Comments:** every function gets a short comment/docstring; comment enough
  that a programmer can follow options and logic.
- **Header block** at the top of every code file: date and time written,
  `Developer: Ash @ Distant Galaxy (@distantgalaxy-net)`. **Update the date** whenever you
  change a file.
- **UK English**, UK date format on labels (`7 Nov 2026`), °C.
- Keep dependencies pinned; prefer the standard library and small libraries.
- Work on a branch and open a PR unless Ash says otherwise.

## Testing without the printer

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
DATA_DIR=/tmp/dd PORT=8013 .venv/bin/python app/main.py
# open http://127.0.0.1:8013, use Preview; /api/print returns a clear error
```

`printer.build(image)` converts without sending – use it to prove an image is
valid for the QL-810W (it raises if the size is wrong).

## Decisions log

- 2026-11-07 – Replaced `pklaus/brother_ql_web` (text-only API, unmaintained)
  with our own service so labels can have layouts, icons, dates and later QR codes.
- 2026-11-07 – Use `brother_ql_next` (maintained fork) + Pillow 10.
- 2026-11-07 – Built-in icons drawn as bold line art (emoji converted to
  black/white looked poor). Custom PNGs in `/data/icons` override them.
- 2026-11-07 – Phone is the main way Ash prints; the page shows the preview
  at the top.
- 2026-11-07 – Printer IP/port moved from the `PRINTER` env var to the
  Settings tab so the code holds no home-network details (possible public
  release). Success message is "Label sent to printer" because the network
  backend can't confirm a label actually came out.
- 2026-11-08 – Printer model and time zone moved to the Settings tab too
  (model dropdown limited to network QL models; time zone list from the tz
  database). `MODEL`, `LABEL` and `TZ` removed from docker-compose. The
  built-in VLAN list was removed (VLANs are managed in the network, not
  here); the Network label's VLAN is now a free-text field. Settings shows
  this server's detected IP to help with firewall rules.
