# Development guide – LabelPrinter

Read this before changing the code. It explains what we're building, the decisions already made
and the constraints that aren't obvious from the code.

_Last updated: 2026-11-08 22:45 GMT · Owner: Ash @ Distant Galaxy (@distantgalaxy-net)_

---

## What this is

A small self-hosted service that prints labels on a network-connected
**Brother QL** printer (developed on a QL-810W) from a phone (primary use)
and from Home Assistant. It replaces the Brother iPrint&Label app for
everyday label types, and is intended to be published for others to use.

**This repo may become public. Never commit personal data** – no real
names, addresses, phone numbers, IP addresses, host names, network names or
domain names, including in placeholders, examples, docs and commit
messages. Use generic examples ("Alex Example", "1 High Street, Anytown,
AB1 2CD", `192.168.1.20`, `labels.home.example`).

## Current state

**Built:**
- Flask web page + JSON API, rendered with Pillow, printed with `brother_ql_next`.
- Label types: `address` (optional icon; custom icons uploaded/deleted in
  the page), `food` (freezer/fridge/cupboard, use-by in days or months,
  cooking instructions, notes, presets; `freezer` is an API alias),
  `travel` (saved details shown locked with Edit/Clear; flights built one
  by one or pasted, sorted, split into journeys; saved trips), `battery`
  (tiny), `network` (name/IP/VLAN/MAC).
- **Settings tab** holds everything install-specific: printer model, IP
  address and port, time zone, temperature unit (°C/°F), optional
  password. Saved in `/data` (git-ignored and Docker-ignored).
  `docker-compose.yml` only holds the web port.
- **User data** (details, food presets, trips, custom icons) lives only in
  `/data`. Never put any of it in the repo or the image.
- **Print** sits directly under the label preview (no fixed bottom bar),
  so what you see and the button are together.
- **Messages** appear next to the button that caused them (`say()` in
  `index.html`, one `.msg` box per action).
- New installs are locked to Settings until **Test and save** connects to
  the printer (`printer.verified`) and a time zone is chosen; `/api/print`
  returns 409 until then. Later saves re-test only if the address changes.
- **Optional password** (off by default): scrypt hash in `/data/auth.json`,
  signed session cookie (30 days) for browsers, HTTP Basic auth for scripts.

**Ideas, not started yet:**
- Address lookup from Google Contacts (People API).
- Guest Wi-Fi: per-guest UniFi hotspot vouchers printed as QR/code labels.
- Pick network devices and battery devices from Home Assistant (battery
  labels must still work for devices not in HA).

## Hard constraints

- **Roll:** 62mm **continuous** black/white (DK-22205) is the **only**
  supported roll; layouts are drawn 696 dots wide.
- **Models:** network-capable Brother QL models only (`printer.NETWORK_MODELS`),
  chosen in Settings. Only the QL-810W is tested on hardware. Minimum label
  length comes from the model (150 dots on most, ~300 on QL-1060N/QL-11xx).
- **Orientation:** label width is always the roll width; length grows with
  content. **Never landscape.** Images are **696 dots wide** (300 dpi), `rotate="0"`.
- **Minimum length:** printers reject continuous labels shorter than their
  minimum (QL-810W: **150 dots / 12.7mm**). `labels.render()` pads short
  labels to `printer.min_length(model)`; keep that.
- **Temperatures:** the unit comes from Settings (`temp_unit`), passed to
  `labels.render()`. Presets store the unit they were saved in and the page
  converts them (rounded to 5°) if the setting has changed.
- **Custom icons:** uploads are converted server-side to a 512-dot 1-bit
  square PNG in `/data/icons`; names are restricted (`clean_icon_name`) so
  they can't escape that folder. Uploads are capped at 10 MB / 40 MP.
- **Dates:** "today" uses the IANA time zone from Settings (`zoneinfo` +
  the image's `tzdata`), so DST is automatic. No `TZ` env var.
- **Black/white only** (`red=False`). Red would need DK-22251 rolls.
- **Printer** is reached over raw TCP (port **9100** by default). Its address
  lives only in Settings (`settings.json` → `printer`), never in code, Docker
  files or examples. Editor Lite must be off on the printer.
- `brother_ql`'s socket has no connect timeout; `printer.py` caps it at 10 s so
  a firewall drop returns an error instead of hanging. Keep that.

## Security model

- With no password the page is open to anyone who can reach it, so the
  defaults keep it narrow: the container port is bound to **`127.0.0.1`**
  (host-only), and the README recommends a reverse proxy with an access
  profile allowing only trusted subnets. Don't loosen these defaults.
- The password is **optional and off by default** (fine for installs only
  reachable from a trusted network).
- Never return or log the password hash; `GET /api/settings` only exposes
  `password_set`. `auth.json` and `secret.key` are written with mode 600
  and are git-ignored. Changing/removing the password needs the current one.
- `RESET_PASSWORD=true` (env) removes the password at start-up – the
  documented recovery path.

## Where it runs

- Docker. Published image: **`distantgalaxy/ql-label-printer`** on Docker Hub
  (amd64 + arm64), built by `.github/workflows/docker-publish.yml` when a
  `v*.*.*` tag is pushed (tags `x.y.z`, `x.y`, `latest`) or by hand (tag =
  branch name). `docker-compose.yml` uses the published image; developers
  swap `image:` for `build: .`. Documented for Synology Container Manager.
- Home Assistant (container, host networking) on the same host can call
  `http://127.0.0.1:8013/api/print/<type>`.

## Code layout

```
app/main.py        Flask routes, settings load/save (atomic write), login gate
app/auth.py        Optional password: hash storage, cookie key, reset
app/labels.py      All label layouts + built-in icons (drawn with Pillow)
app/printer.py     Image -> QL raster -> send to printer; models; address checks
app/static/index.html  Phone-first page (vanilla JS, no build step)
app/static/login.html  Password page (only used when a password is set)
Dockerfile, .dockerignore, docker-compose.yml, requirements.txt (pinned)
.github/workflows/docker-publish.yml   Docker Hub build (multi-arch)
```

Flights: `labels.clean_legs` / `format_legs` / `parse_flight`. Pasting
fills the flight boxes for the user to check (one flight at a time);
`parse_flight` looks for each part separately (date, flight number,
bracketed airport codes, "Departure"/"Arrival" times), so booking emails
in any layout work. The label
template is `1 Mar 0900-1130, XX 0123, AAA-BBB` (`+1` after a next-day
arrival); a gap of more than a day between landing and the next take-off
starts a new journey. The page mirrors this for its list.

Adding a label type = a function in `labels.py` registered in `RENDERERS`,
plus a `<form data-kind="...">` and tab in `index.html`. The API picks it up
automatically.

## Coding conventions

- **Comments:** every function gets a short comment/docstring; comment enough
  that a programmer can follow options and logic.
- **Header block** at the top of every code file: date and time written,
  `Developer: Ash @ Distant Galaxy (@distantgalaxy-net)`. **Update the date**
  whenever you change a file.
- **UK English**, UK date format on labels (`7 Nov 2026`), °C.
- Keep dependencies pinned; prefer the standard library and small libraries.
- **Licence:** GPL v3 (`LICENSE`), because `brother_ql_next` is GPL-3.0.
  New dependencies must have a GPL-compatible licence (e.g. MIT, BSD,
  Apache-2.0, LGPL); check before adding one.
- Work on a branch and open a pull request; don't commit straight to `main`.

## Testing without the printer

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cd app && DATA_DIR=/tmp/dd PORT=8013 ../.venv/bin/python main.py
# open http://127.0.0.1:8013 - Settings needs a reachable printer to save;
# a tiny TCP listener on a spare local port works as a stand-in.
```

`printer.build(image, model)` converts without sending – use it to prove an
image is valid for a model (it raises if the size is wrong).

## Decisions log

- 2026-11-07 – Own service instead of `pklaus/brother_ql_web` (text-only API,
  unmaintained) so labels can have layouts, icons, dates and later QR codes.
- 2026-11-07 – Use `brother_ql_next` (maintained fork) + Pillow 10.
- 2026-11-07 – Built-in icons drawn as bold line art (emoji converted to
  black/white looked poor). Custom PNGs in `/data/icons` override them.
- 2026-11-07 – Phone first: the page shows the preview at the top.
- 2026-11-07 – Printer address moved from an env var to the Settings tab, so
  the code holds no network details. Success message is "Label sent to
  printer" because the network backend can't confirm a label came out.
- 2026-11-08 – Printer model and time zone also in Settings; `MODEL`,
  `LABEL` and `TZ` removed from docker-compose. No built-in VLAN list; the
  Network label's VLAN is free text.
- 2026-11-08 – New installs locked to Settings until the printer connection
  is tested on save.
- 2026-11-08 – Optional password (Settings tab, scrypt hash, off by default).
  Project renamed from its original host-name to `labelprinter`; history
  rewritten to remove personal details before any public release.
- 2026-11-08 – Licensed under GPL v3: the printing library `brother_ql_next`
  is GPL-3.0, so the published image is bound by it anyway.
- 2026-11-08 – Removed the "This server" IP box from Settings: inside
  Docker only the container's internal address is visible, which misled.
- 2026-11-08 – Freezer label widened to a Food label (freezer / fridge /
  cupboard); `freezer` kept as an API alias and old presets migrate to
  `food_presets` automatically. Temperature unit chosen in Settings.
- 2026-11-08 – Feedback messages shown beside the button pressed, not at
  the foot of the page; first-time setup stays on Settings.
- 2026-11-08 – Custom icons can be uploaded and deleted from the page.
- 2026-11-08 – Travel flights entered as structured legs (or pasted text)
  and formatted by the server; trips saved in settings, the current
  flights also kept in the browser's localStorage as a draft.
- 2026-11-08 – Print button moved directly under the preview. Pasted
  flight text no longer has to be one-per-line: any booking layout is
  read into the flight boxes for checking, then added.
- 2026-11-08 – Distributed as a Docker Hub image built by GitHub Actions,
  so installs and updates are a download instead of copying code. `data/`
  is excluded from the build context (`.dockerignore`).
