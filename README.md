# LabelPrinter

Print useful labels on a Brother QL label printer from your phone or from
Home Assistant.

_Updated: 2026-11-08 18:06 GMT · Developer: Ash @ Distant Galaxy (@distantgalaxy-net)_

A small self-hosted web service, run in Docker (for example on a Synology
NAS). It prints on a network-connected Brother QL printer from a
phone-friendly web page or a simple JSON API. Labels are always the full
width of the 62mm continuous roll; their length grows with the content.

> Working on the code? Read the [development guide](docs/DEVELOPMENT.md) first – it has the goals,
> constraints and conventions.

## How it fits together

```
Phone / laptop (your trusted network or VPN)
   │  http://labels.home.example   (optional reverse proxy)
   ▼
Reverse proxy, allowing only trusted addresses (optional but recommended)
   │  localhost:8013
   ▼
labelprinter container ──── raw TCP, port 9100 ────►  Brother QL printer
   ▲
   │  http://127.0.0.1:8013/api/print/<type>
Home Assistant on the same host (optional)
```

## Label types

Address (optional icon) · Freezer (presets, use-by date, cooking
instructions) · Travel (your saved details + flights) · Battery (the
smallest label your printer allows) · Network device (name, IP, VLAN, MAC).

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
- On the printer, **Editor Lite must be off**, and the printer should have a
  fixed IP address (a DHCP reservation in your router).

---

## Install on a Synology NAS (Container Manager)

The image is published on Docker Hub as
[`distantgalaxy/ql-label-printer`](https://hub.docker.com/r/distantgalaxy/ql-label-printer)
for Intel/AMD and ARM, so there's no code to download.

1. **Make a folder.** In File Station, create `docker/ql-label-printer`
   and, inside it, an empty folder called `data`. Your settings are saved
   there.
2. **Create the project.** Container Manager → **Project** → **Create**:
   - Project name: `ql-label-printer`
   - Path: `docker/ql-label-printer`
   - Source: **Create docker-compose.yml**, and paste in the contents of
     [`docker-compose.yml`](docker-compose.yml) from this repo.
   - Next → (skip the web portal option) → **Done**.

   Container Manager downloads the image and starts it.
3. **Check it.** Container Manager → **Container** → `labelprinter` should
   show **Running**, then **healthy**.
4. **Make it reachable.** The container only listens on the NAS itself
   (`127.0.0.1:8013`). Add a reverse proxy: Control Panel → Login Portal →
   Advanced → **Reverse Proxy** → Create, source `http://<a name you choose>`
   port 80, destination `http://localhost:8013`. Attach an **Access Control
   Profile** that allows only your trusted network and VPN subnets.
5. **Open the page** and finish setup in the **Settings** tab (below).

### Other Docker hosts

Put [`docker-compose.yml`](docker-compose.yml) in a folder, then from that
folder:

```bash
docker compose up -d
```

Then open `http://<host>:8013` from the host itself, or through your own
reverse proxy. See the comments in `docker-compose.yml` for changing the port.

### Building it yourself

To run your own changes instead of the published image, clone this repo,
replace the `image:` line in `docker-compose.yml` with `build: .`, and run
`docker compose up -d --build`.

## The web port

The only setting in `docker-compose.yml` is the port line
`"127.0.0.1:8013:8013"` (listen address : port on the host : port in the
container). If 8013 is already used, change the middle number (e.g.
`127.0.0.1:8020:8013`) and point your reverse proxy at the new port.
`127.0.0.1` keeps it reachable only from the host itself. Don't open it
wider unless your network is trusted or you've set a password, and never
forward it from the internet.

## First-time setup in the page

A new install opens on the **Settings** tab with the label tabs locked:

- **Printer:** pick your **model**, enter its **IP address** and **port**
  (Brother printers use **9100**).
- **Time zone:** it suggests your phone's. It sets "today" on freezer and
  battery labels; daylight saving changes are handled automatically.
- Tap **Test and save**. It connects to the printer first and only saves if
  that works; then the label tabs unlock. (Until then the print API replies
  "Setup isn't finished".)
- The box under the port shows this server's IP address, to help with
  firewall rules. Inside Docker that's the container's internal address;
  the printer sees connections from the host's own IP.

Then, if you like:

- **Travel tab:** type your name, address and phone once and tap
  **Save as my details**.
- **Freezer tab:** fill in a food you freeze often and tap **Save as preset**.

Everything is saved in the `data/` folder, so it survives updates and is
included in your backups.

## Optional password

Off by default – fine when only your own trusted network can reach the page.
To turn it on, open **Settings → Password (optional)**, enter a new password
(at least 8 characters) twice and tap **Set password**.

- It's stored as a one-way **scrypt hash** in `data/auth.json`, so it can't
  be read back from the file, and it's never returned by the API.
- Browsers log in once and stay logged in for 30 days (**Log out** at the
  top of the page).
- Scripts and Home Assistant use **HTTP Basic auth** with any username and
  the password (see below).
- To change or remove it you must enter the current password.
- **Forgotten it?** In `docker-compose.yml` uncomment the
  `RESET_PASSWORD: "true"` lines, restart the container once (the password
  is removed), then comment them out again and restart.

## Updating to a new version

Releases are listed on the GitHub **Releases** page. Your settings in
`data/` are kept across updates.

- **Synology:** Container Manager → **Project** → `ql-label-printer` →
  **Action → Stop**, then **Action → Build**. That downloads the newest
  image and starts it again. (Alternatively: **Image** →
  `distantgalaxy/ql-label-printer` → **Update**, then restart the project.)
- **Other hosts:**
  ```bash
  docker compose pull && docker compose up -d
  ```
- **Staying on a version:** change `:latest` in `docker-compose.yml` to a
  release number, e.g. `:1.0.0`.

## Publishing a release (maintainers)

The GitHub workflow `.github/workflows/docker-publish.yml` builds the image
for amd64 and arm64 and pushes it to Docker Hub:

- **Release:** GitHub → **Releases → Draft a new release**, create a tag
  like `v1.0.0`, publish. The image is tagged `1.0.0`, `1.0` and `latest`.
- **Test build:** **Actions → Publish Docker image → Run workflow** builds
  the chosen branch and tags it with the branch name (e.g. `main`), without
  touching `latest`.

It needs a repository variable `DOCKERHUB_USERNAME` and a secret
`DOCKERHUB_TOKEN` (a Docker Hub access token with Read & Write) under
Settings → Secrets and variables → Actions.

## Your own icons

Built-in icons: gift, birthday, christmas, celebration, heart, star, balloon,
wedding, new home. To add or replace one, put a **black-on-white PNG** in
`data/icons/` (e.g. `graduation.png`, or `gift.png` to replace the
built-in). It appears in the Icon list on the next page load.

## Troubleshooting

| Message | Meaning |
|---|---|
| Setup isn't finished | Finish the **Settings** tab and tap **Test and save**. |
| Couldn't reach the printer … timed out | Printer off, wrong IP in Settings, or a firewall between the host and the printer. Allow the host to reach the printer on TCP 9100 (in UniFi, set Connection State to **All**). |
| Couldn't reach the printer … refused | Printer reachable but not accepting jobs. Check Editor Lite is off. |
| Page won't load | Container not running, or your device isn't allowed by the reverse proxy. |
| Asked for a password you don't know | See **Forgotten it?** above. |

Container Manager → Container → `labelprinter` → **Log** shows the detail.

## Home Assistant (optional)

If Home Assistant runs on the same host with host networking, it can call
the API directly. Add to `configuration.yaml`:

```yaml
rest_command:
  labelprinter_print:
    url: "http://127.0.0.1:8013/api/print/{{ kind }}"
    method: post
    content_type: "application/json"
    payload: "{{ label | to_json }}"
    timeout: 30
    # Only if you set a password:
    # username: homeassistant
    # password: !secret labelprinter_password
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
| `GET/PUT /api/settings` | Saved details, freezer presets, battery types, `printer` (`host`, `port`, `model`), `timezone` (e.g. `Europe/London`); `password_set` is read-only |
| `GET /api/options` | Printer models, time zone names, this server's detected IP |
| `POST /api/printer/test` | Check the printer can be reached without printing (body `host`/`port`, or empty to test the saved one) |
| `GET /api/icons` | Icon names |
| `POST /api/login`, `POST /api/logout`, `PUT /api/password` | Optional password: log in/out; set, change or remove (`{"current": "…", "new": "…"}`, empty `new` removes) |

If a password is set, every call except `/api/login` and `/health` needs a
login session or HTTP Basic auth, and answers `401` otherwise.

`<type>` = `address`, `freezer`, `travel`, `battery`, `network`.

Fields:
- **address:** `name`, `address` (lines separated by newlines), `icon`
- **freezer:** `title`, `frozen` (YYYY-MM-DD), `months`, `method` (`from_frozen` / `defrost` / empty), `minutes`, `temp_c`, `fan_c`, `notes`
- **travel:** `name`, `address`, `phone`, `flights` (blank line between journeys)
- **battery:** `device`, `battery`, `changed` (YYYY-MM-DD, default today)
- **network:** `name`, `ip`, `vlan`, `mac`, `notes`

## Ideas for later

Address lookup from Google Contacts · guest Wi-Fi vouchers from UniFi as QR
labels · picking network and battery devices from Home Assistant.

## Licence

LabelPrinter is free software, released under the
[GNU General Public License v3.0](LICENSE). You can use, change and share
it, including commercially; if you share a changed version, it must stay
under the same licence with its source code available. It comes with no
warranty.

It is built on [`brother_ql_next`](https://pypi.org/project/brother_ql_next/)
(GPL-3.0), which turns labels into the printer's commands – which is why
this project uses the GPL too. The other libraries it uses (Flask, Werkzeug,
Pillow, waitress) have permissive licences compatible with the GPL.
