# LabelPrinter
Prints helpful labels on Brother QL-810W

_Updated: 2026-11-08 09:38 GMT · Developer: Ash @ Distant Galaxy (@distantgalaxy-net)_

A small self-hosted label service (container **labelprinter** on the Synology NAS
**the NAS**) that prints on a Brother QL-810W from a phone-friendly web page or
from Home Assistant. Labels are always the full width of the 62mm continuous
black/white roll; their length grows with the content.

It replaces the Brother iPrint&Label app for everyday labels, and will later
fill labels from data Ash already has (Google Contacts, UniFi, Home Assistant).

> Working on the code? Read [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) first – it has the goals,
> constraints, network/security set-up and conventions.

## How it fits together

```
Phone / laptop (Trusted VLAN or VPN)
   │  http://labels.home.example
   ▼
DSM reverse proxy (access profile "Trusted only")
   │  localhost:8013
   ▼
labelprinter container ──── tcp 9100 ────►  QL-810W (IoT; IP set in the Settings tab)
   ▲
   │  http://127.0.0.1:8013/api/print/<type>
Home Assistant "homeassistant" (host network)
```

## Status

| Phase | What | State |
|---|---|---|
| 1 | Address, freezer, travel, battery, network labels; web page; HA API | **Done** |
| 2 | Google Contacts lookup · per-guest Wi-Fi vouchers · pick devices from HA | Planned |

**Label types:** Address (optional icon) · Freezer (presets, use-by, cooking) ·
Travel (your saved details + flights) · Battery (smallest label the printer
allows, ~13mm) · Network device (name, IP, VLAN, MAC).

Web page: **http://labels.home.example** (Trusted + VPN only). The old
`/labeldesigner` link still works.

## Supported printers and labels

- **Roll:** the **62mm continuous** roll (DK-22205) only, black on white.
  Every label layout is drawn for that width.
- **Printers:** Brother QL models that print over the network. Choose yours
  in the **Settings** tab:

  | Model | Shortest label |
  |---|---|
  | QL-580N, QL-710W, QL-720NW, QL-810W, QL-820NWB | 12.7mm |
  | QL-1060N | 25mm |
  | QL-1100NWB, QL-1110NWB, QL-1115NWB | 25.5mm |

  Only the **QL-810W** has been tested on real hardware; the others use the
  same commands via `brother_ql_next`. USB-only models (QL-700, QL-800 …)
  can't be reached from a container.

---

## Install on the NAS

The NAS needs internet access while it builds (it downloads Python and the
packages once).

1. **Stop the old project.** Container Manager → **Project** → `labelprinter` →
   **Action → Stop**, then **Delete**. If it asks, do **not** delete the folder.
2. **Copy the files in.** On GitHub use **Code → Download ZIP**, then in File
   Station open `docker/labelprinter` and upload the contents so the folder looks
   like this (keep any existing `data/` folder – it holds your saved settings):
   ```
   docker/labelprinter/
     docker-compose.yml   (replaces the old one)
     Dockerfile
     requirements.txt
     README.md
     app/  main.py  labels.py  printer.py  static/index.html
     data/ icons/
   ```
3. **Create the project again.** Container Manager → **Project** → **Create**:
   name `labelprinter`, path `docker/labelprinter`, Source → **Use existing
   docker-compose.yml** → Next → Done. The first build takes a few minutes.
4. **Check it.** The container should show **healthy**. Open
   http://labels.home.example from a Trusted device or the VPN.
5. **Tidy up (optional).** Container Manager → **Image** → delete
   `pklaus/brother_ql_web`.

Nothing changes in the reverse proxy, the access profile or the UniFi rule:
the port is still `127.0.0.1:8013`. The printer and time zone are no longer in
`docker-compose.yml`: set them once in the page's **Settings** tab (see below).

**Web port.** The only setting left in `docker-compose.yml` is the port line
`"127.0.0.1:8013:8013"` (listen address : port on the NAS : port in the
container). If 8013 is already used on your NAS, change the middle number
(e.g. `127.0.0.1:8020:8013`) and point the reverse proxy at the new port.
`127.0.0.1` keeps it reachable only from the NAS itself. **The page has no
login**, so don't open it wider unless your home network is trusted, and
never forward it from the internet.

## Updating to a new version

1. Download the latest ZIP from GitHub and upload it over `docker/labelprinter`
   (don't overwrite `data/`).
2. Container Manager → **Project** → `labelprinter` → **Action → Build** (or Stop,
   then Start with "rebuild"). Your settings and presets are kept.

## First-time setup in the page

- **Settings tab (do this first):** pick your **printer model**, enter its
  **IP address** and **port** (Brother printers use **9100**), tap
  **Test connection**, check the **time zone** (it suggests your phone's),
  then **Save**. The page opens on this tab until both are saved.
  - Give the printer a fixed IP (a DHCP reservation in your router).
  - The time zone sets "today" on freezer and battery labels. Daylight
    saving (e.g. GMT ↔ BST) is handled automatically.
  - The box under the port shows this server's IP address, to help with
    firewall rules. In Docker that's the container's internal address; the
    printer sees connections from the NAS's own IP.
- **Travel tab:** type your name, address and phone once and tap
  **Save as my details**.
- **Freezer tab:** fill in a food you freeze often and tap **Save as preset**.
  Presets keep the use-by months and cooking instructions.
- Settings and presets are saved in `docker/labelprinter/data/settings.json`, so
  they survive rebuilds and are included in your NAS backups.

## Your own icons

Built-in icons: gift, birthday, christmas, celebration, heart, star, balloon,
wedding, new home. To add or replace one, put a **black-on-white PNG** in
`docker/labelprinter/data/icons/` (e.g. `graduation.png`, or `gift.png` to replace
the built-in). It appears in the Icon list on the next page load.

## Troubleshooting

| Message | Meaning |
|---|---|
| No printer set up yet | Enter the printer's IP address in the **Settings** tab and tap Save. |
| Couldn't reach the printer … timed out | Firewall or printer off, or the wrong IP in the Settings tab. Check the UniFi rule NAS → Printer, TCP 9100, Connection State **All**. |
| Couldn't reach the printer … refused | Printer reachable but not accepting jobs. Check Editor Lite is off. |
| Page won't load | Container not running, or you're not on Trusted/VPN. |

Container Manager → Container → `labelprinter` → **Log** shows the detail.

## Home Assistant (optional, later)

homeassistant uses host networking, so it can call the API directly. Add to
`configuration.yaml`:

```yaml
rest_command:
  labelprinter_print:
    url: "http://127.0.0.1:8013/api/print/{{ kind }}"
    method: post
    content_type: "application/json"
    payload: "{{ label | to_json }}"
    timeout: 30
```

Example action – a battery label:

```yaml
action: rest_command.labelprinter_print
data:
  kind: battery
  label:
    device: Hallway motion sensor
    battery: CR2032
```

## API

| Call | Purpose |
|---|---|
| `POST /api/preview/<type>` | PNG preview (header `X-Label-Length-mm`) |
| `POST /api/print/<type>` | Print → `{"ok": true/false, "message": "…"}` (add `"copies": n`) |
| `GET/PUT /api/settings` | Saved details, freezer presets, battery types, `printer` (`host`, `port`, `model`), `timezone` (e.g. `Europe/London`) |
| `GET /api/options` | Printer models, time zone names, this server's detected IP |
| `POST /api/printer/test` | Check the printer can be reached without printing (body `host`/`port`, or empty to test the saved one) |
| `GET /api/icons` | Icon names |

`<type>` = `address`, `freezer`, `travel`, `battery`, `network`.

Fields:
- **address:** `name`, `address` (lines separated by newlines), `icon`
- **freezer:** `title`, `frozen` (YYYY-MM-DD), `months`, `method` (`from_frozen` / `defrost` / empty), `minutes`, `temp_c`, `fan_c`, `notes`
- **travel:** `name`, `address`, `phone`, `flights` (blank line between journeys)
- **battery:** `device`, `battery`, `changed` (YYYY-MM-DD, default today)
- **network:** `name`, `ip`, `vlan`, `mac`, `notes`

## Phase 2 (not built yet)

Google Contacts lookup for addresses · Guest Wi-Fi vouchers from UniFi ·
network devices and batteries
picked from Home Assistant.
