# Development guide – LabelPrinter

Read this before changing the code. It explains what we're building, the decisions already made
and the constraints that aren't obvious from the code.

_Last updated: 2026-11-09 15:30 GMT · Owner: Ash @ Distant Galaxy (@distantgalaxy-net)_

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
  address and port, time zone, temperature unit (°C/°F), accent colour,
  optional password. Saved in `/data` (git-ignored and Docker-ignored).
  `docker-compose.yml` only holds the web port.
- **User data** (details, food presets, trips, custom icons) lives only in
  `/data`. Never put any of it in the repo or the image.
- **Accent colours** live in `app/static/theme.css` (served at
  `/theme.css`, open without login so the login page matches). Each has a
  light and a dark shade, checked for WCAG AA contrast (≥ 4.5:1) both as
  button background and as text on the card. The choice is saved in
  settings (`accent`, validated against `ACCENTS` in `main.py`) and cached
  in the browser's localStorage so the page and login page colour
  themselves before settings load. Success/error colours stay green/red
  whatever the accent.
- **Contact cards** (Address tab): "Import contact card" reads a `.vcf`
  in the browser (`parseVCards` in `index.html`: vCard 2.1/3.0/4.0,
  folded lines, quoted-printable, Apple `itemN.X-ABLabel` labels). Never
  uploaded or stored. Works on every device; computers can drop the file
  on the Address tab. Several contacts → name list (search when > 8).
- **Contact picker** (Address tab, Android only): the browser's Contact Picker API
  (`navigator.contacts.select(["name","address"])`), all in the page – no
  server code, nothing stored. Shown only when the API exists, the page is
  a secure context (HTTPS or localhost) and `address` is supported;
  otherwise a note chosen by device type: Android over HTTP → needs a
  secure connection; Android without a picker → needs Chrome; iPhone →
  how to save a contact card; computer → how to export one. Safari's
  picker only returns name/email/tel (WebKit `ContactsManager`), never
  addresses, so iPhones use contact cards; if Apple adds addresses the
  feature check shows the button automatically. The browser sees the HTTPS hop to the reverse proxy, so
  the plain-HTTP hop inside the NAS doesn't matter. Several
  addresses → the user picks one (no default). Tested with a stand-in
  picker only; Android Chrome is the target, iPhone untested.
- **Printer status** (`app/status.py`, `GET /api/printer/status`): TCP
  connect (3 s) → "Printer unavailable" if it fails; then Brother's status
  request (`ESC i S`) on that connection, decoded with brother_ql's
  `interpret_response`; if no reply in 2 s, SNMP v1 GET-NEXT (stdlib
  only, community `public`) for hrPrinterDetectedErrorState,
  hrDeviceStatus, prtInputMediaName and prtCoverStatus. No answer to
  either → treated as ready (reachable, status unknown). Status checks take
  the printer job lock, so they never overlap a print. The page checks on
  load, after printing, on becoming visible, and every 30 s while not
  ready; Print stays disabled until a check says ready. Home Assistant
  printing isn't blocked by it. **Unverified on hardware:** whether the
  QL-810W answers `ESC i S` or SNMP over Wi-Fi – use Settings → Check
  printer, whose details show the raw reply.
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
- Address lookup from Google Contacts (People API) for computers, where
  the browser contact picker isn't available.
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
app/status.py      Printer ready? Roll loaded? (connection, ESC i S, SNMP)
app/static/index.html  Phone-first page (vanilla JS, no build step)
app/static/login.html  Password page (only used when a password is set)
app/static/theme.css   Accent colour shades (light + dark) and swatches
app/VERSION        The version number (see Versions)
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

## Versions

- The version lives in **`app/VERSION`** (one line, e.g. `1.1.1`). It's
  shown at the top of the Settings tab, in `/health` and in the log at
  start-up.
- **Test builds:** every set of changes pushed for testing adds one to the
  last number (1.1.1 → 1.1.2 …). Bump it in the same commit as the change.
- **Releases:** the owner decides minor or major. Set `app/VERSION` to the
  release number (e.g. `1.2.0`) in the pull request, then publish a GitHub
  release tagged `v1.2.0`. The publish workflow refuses a tag that doesn't
  match `app/VERSION`. The next test build after `1.2.0` is `1.2.1`.
- Released so far: v1.0.0, v1.1.0.

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

**Test copy on a Synology NAS (no command line):** download the branch
as a ZIP (`https://github.com/<owner>/ql-label-printer/archive/refs/heads/<branch>.zip`),
copy the *contents* of its top folder into e.g. `docker/ql-label-printer-test`,
and create a Container Manager project there with:

```yaml
services:
  labelprinter-test:
    build: .
    pull_policy: build              # rebuild from the code every time
    container_name: labelprinter-test
    ports:
      - "127.0.0.1:8014:8013"       # behind an HTTPS reverse proxy entry
    volumes:
      - ./data:/data
```

`pull_policy: build` matters: without it, Container Manager's **Build**
reuses the image it built last time and the old code keeps running. After
updating the files: Action → Stop, then Action → Build. The version at the
top of Settings (or `/health`) confirms which build is running.

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
- 2026-11-08 – Accent colour choice in Settings (green default; blue, red,
  pink, purple, orange, monochrome), each tuned for light and dark themes.
- 2026-11-09 – Address label: a name that would shrink below 56 dots
  beside the icon moves across the full width on top, with the icon
  (130–190 dots, matching the address height) beside the address only.
  A name below 52 dots on one line is split over two lines between words.
  Short names keep the original layout. Added horseshoe and flowers
  icons; clover stem now comes out of the bottom leaf. Then snowman and
  snowflake; snowman and celebration (party popper) later redrawn to be
  clearer and livelier; snowman then simplified (thin outlines, tall oval
  body, no hat), and finally a clean line style (body outline stops at
  the head, rounded lines, ground line; idea from common line-icon sets).
  Fireworks added, later as dotted bursts with a fine trail.
- 2026-11-09 – Built-in icons: wedding redrawn as linked rings with a
  diamond (two plain circles didn't read as anything); added get well
  (sticking plaster) and good luck (four-leaf clover). Drawn in code like
  the others, checked at label size (190 dots, black and white).
- 2026-11-09 – Page checks the printer and disables Print with the reason
  (unavailable / cover open / spool finished / wrong roll). brother_ql's
  network backend can't read status, so status.py asks the printer
  directly, with SNMP as the fallback; SNMP written with the standard
  library to avoid a new dependency.
- 2026-11-09 – Contact card (.vcf) import added for computers and iPhones
  (Safari's picker can't share addresses). Read in the browser only.
- 2026-11-09 – Contacts on phones via the browser's Contact Picker API
  rather than Google's People API: no Google sign-in or API keys, works
  with whatever account the phone uses, and the page only ever sees the
  one contact picked. Detection is by feature (does the picker exist?),
  not by device name; the device type only chooses the hint. Requires
  HTTPS.
- 2026-11-08 – Distributed as a Docker Hub image built by GitHub Actions,
  so installs and updates are a download instead of copying code. `data/`
  is excluded from the build context (`.dockerignore`).
