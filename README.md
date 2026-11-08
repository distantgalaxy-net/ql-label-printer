# LabelPrinter

Print useful labels on a Brother QL label printer from your phone or from
Home Assistant.

_Updated: 2026-11-09 00:50 GMT · Developer: Ash @ Distant Galaxy (@distantgalaxy-net)_

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

Address (optional icon, including your own uploaded pictures; on Android,
choose the address straight from your contacts) · Food
(freezer, fridge or cupboard: frozen/opened date, use-by in days or months,
cooking instructions in °C or °F, notes, saved presets) · Travel (your
saved details + flights, sorted and split into journeys, saved trips) ·
Battery (the smallest label your printer allows) · Network device (name,
IP, VLAN, MAC).

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
- **Time zone:** it suggests your device's (or tap **Use this device's time
  zone**). It sets "today" on food and battery labels; daylight saving
  changes are handled automatically.
- Tap **Test and save**. It connects to the printer first and only saves if
  that works; then the label tabs unlock. (Until then the print API replies
  "Setup isn't finished".)
- **Temperature unit:** °C or °F for cooking temperatures on food labels
  (saved as soon as you choose).
- **Colour:** the page's accent colour – green, blue, red, pink, purple,
  orange or monochrome. Each has a light and a dark shade that follows
  your device's light/dark theme (saved as soon as you choose).

If a firewall sits between the host and the printer, allow the host's own
IP address (e.g. your NAS's) to reach the printer on the printer port.

Then, if you like:

- **Travel tab:** type your name, address and phone once and tap
  **Save my details**. They're then shown locked, with **Edit** and
  **Clear**, and filled in every time.
- **Travel flights:** add flights one at a time (date picker, airports you've
  already used are suggested, the next flight starts on the day the last
  one landed, **+1** is ticked for you when it lands at an earlier clock
  time). Or open **Fill in from your booking**, paste one flight copied
  from your confirmation email or itinerary (any layout), and the boxes
  are filled in for you to check before tapping **Add flight**. They're sorted by date, and a gap of more
  than a day starts a new journey on the label. **Save trip** keeps the
  whole set to load again later; the flights on the page are also
  remembered in your browser.
- **Food tab:** fill in a food you make often and tap **Save as preset**.
  A preset keeps everything except the date: choosing it again fills in
  today's date and works out the use-by date afresh.
- **Address tab → Choose from contacts** (Android phones): opens your
  phone's contact list; pick a contact and its address is filled in. If
  it has more than one address you're asked which one. Only the contact
  you pick is shared with the page, and it isn't saved anywhere. See
  [Choosing addresses from contacts](#choosing-addresses-from-contacts).
- **Address tab → Your own icons:** upload a picture; it's converted to a
  black-and-white square. Delete it there too.

The **Print** button sits directly under the label preview. Messages
appear right next to the button you pressed.

Everything is saved in the `data/` folder (never in this repo or the
published image), so it survives updates and is included in your backups.

## Choosing addresses from contacts

The Address tab can fill in a name and address from your phone's
contacts, using the browser's built-in contact picker:

| Device | Works? |
|---|---|
| Android phone, Chrome | Yes – tap **Choose from contacts** |
| iPhone, Safari | Only if Safari's *Contact Picker API* feature flag is on (Settings → Apps → Safari → Advanced → Feature Flags). Not tested. |
| Laptop / desktop | No – browsers on computers don't offer a contact picker |

**It needs HTTPS.** Phones only allow the contact picker on secure pages,
so open the label printer through an `https://` address. On Synology:
Control Panel → Login Portal → Advanced → Reverse Proxy, set the source
protocol to **HTTPS**, and give that host name a certificate (Control
Panel → Security → Certificate). Over plain `http://` the page shows a
note instead of the button.

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

- **Synology:** Container Manager doesn't download updates by itself, and
  the "Update available" badge can take a long time to appear, so update
  by hand once the release's GitHub build has finished:
  1. **Registry** → search `distantgalaxy/ql-label-printer` → select it →
     **Download** → tag `latest`. This fetches the new image (Build on its
     own does not, if an older copy is already on the NAS).
  2. **Project** → `ql-label-printer` → **Action → Stop**, then
     **Action → Build**. This recreates the container from the new image;
     a plain restart keeps using the old one.
  3. Open the page to check it's the new version.
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
wedding, new home. They're drawn by the app's own code (no image files or
third-party artwork).

To add your own, open **Address → Your own icons**, give it a name and
choose a picture (PNG, JPEG, GIF, WebP or BMP, up to 10 MB). It's trimmed,
fitted into a square and converted to pure black and white, then saved in
`data/icons/`. Using a built-in's name (e.g. `gift`) replaces that built-in
until you delete yours. You can also copy black-on-white PNGs into
`data/icons/` directly.

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
| `GET/PUT /api/settings` | Saved details (`me`), `food_presets`, `trips`, battery types, `printer` (`host`, `port`, `model`), `timezone` (e.g. `Europe/London`), `temp_unit` (`C`/`F`), `accent` (`green`/`blue`/`red`/`pink`/`purple`/`orange`/`mono`); `password_set` is read-only |
| `GET /api/options` | Printer models and time zone names |
| `POST /api/printer/test` | Check the printer can be reached without printing (body `host`/`port`, or empty to test the saved one) |
| `GET /api/icons` | Icons: `[{"name", "custom"}]` |
| `GET /api/icons/<name>` | Small PNG of an icon |
| `POST /api/icons` | Upload a custom icon (multipart form: `name`, `file`) |
| `DELETE /api/icons/<name>` | Delete a custom icon |
| `POST /api/travel/parse` | Pick one flight out of pasted text: `{"text": "…"}` → `{"leg": {…}, "missing": […], "more": true/false}` |
| `POST /api/login`, `POST /api/logout`, `PUT /api/password` | Optional password: log in/out; set, change or remove (`{"current": "…", "new": "…"}`, empty `new` removes) |

If a password is set, every call except `/api/login` and `/health` needs a
login session or HTTP Basic auth, and answers `401` otherwise.

`<type>` = `address`, `food`, `travel`, `battery`, `network` (`freezer`
still works as the old name for `food`).

Fields:
- **address:** `name`, `address` (lines separated by newlines), `icon`
- **food:** `title`, `storage` (`frozen` / `fridge` / `cupboard`), `date` (YYYY-MM-DD, default today), `shelf` (number), `shelf_unit` (`days` / `months`), `method` (`from_frozen` / `defrost` / `cook` / `none`), `minutes`, `temp`, `fan` (in the Settings unit), `notes`. The old freezer fields `frozen`, `months`, `temp_c`, `fan_c` still work.
- **travel:** `name`, `address`, `phone`, and either `legs` (list of `{"date": "YYYY-MM-DD", "flight", "from", "to", "dep": "HHMM", "arr": "HHMM", "plus1": true/false}` – sorted and split into journeys for you) or `flights` (text as typed, blank line between journeys)
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
