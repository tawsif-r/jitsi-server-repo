# Scheduling meetings from a calendar

Three ways exist. This deployment uses **#3** (reservation service); #1 is documented
because it is what people find first, and #2 needs nothing.

| | How | Works here? |
|---|---|---|
| 1. Jitsi built-in calendar tab | `ENABLE_CALENDAR=1` + Google / Microsoft OAuth client IDs. Welcome page lists your upcoming calendar events, "Add meeting link" button. | **No.** Both OAuth providers need a public hostname with a browser-trusted certificate as redirect URI, plus Internet access from the browser to Google/Microsoft. This install is LAN-only on `https://192.168.3.35:8443` with a self-signed cert. |
| 2. Paste the link | A room is just a URL. Put `https://192.168.3.35:8443/<room>` in any calendar event. | Yes, always. Nothing enforces the time slot. |
| 3. Reservation service | Small sidecar (`reservation.yml`) with a scheduling page. Prosody asks it before opening any room; it enforces the time slot, sets the meeting password, and produces calendar entries (.ics / Google / Outlook links). | **Yes — installed.** |

## 3. Reservation service

### Start / stop

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml -f reservation.yml up -d
```

(Override file must be listed explicitly once you pass `-f`; add `-f whiteboard.yml` etc. as you already do.)
To remove: `docker compose -f docker-compose.yml -f reservation.yml rm -sf reservation`, then start prosody without `reservation.yml` so `PROSODY_RESERVATION_ENABLED` is unset.

### Scheduling page

`http://192.168.3.35:8600/`

Fill title, room name, start, duration, optional password, organiser email → **Schedule**.
The confirmation shows the meeting link, the password and three calendar actions:

* **download .ics** — import into Thunderbird / Apple Calendar / Outlook desktop / anything.
* **Google Calendar** — opens a pre-filled event in the browser.
* **Outlook** — same, for Outlook on the web / M365.

The event's location and description carry the room URL and the password, so invitees have
everything in the calendar entry.

Times are entered in the browser's timezone and stored as UTC.

### What happens at meeting time

1. Host (registered account, see [AUTH.md](AUTH.md)) opens the room URL and logs in.
2. Prosody `mod_reservations` asks `POST http://reservation.meet.jitsi:8600/conference`.
3. Service answers:
   * inside the slot (from *start − 10 min* to *end*) → **200** with `duration` and `password`
     → room opens, prosody sets the room password. Everyone (host included) types it once.
   * scheduled but too early → **403** "This meeting is scheduled for … Room opens 10 min before."
     Jitsi shows this as a *reservation error* notification.
   * not scheduled at all → **200** ad hoc for `RESERVATION_ADHOC_HOURS` (default 12 h) when
     `RESERVATION_ALLOW_UNSCHEDULED=1`; **403** "This room is not scheduled" when `0`.
4. When the slot ends prosody destroys the room ("Scheduled conference duration exceeded").
   Prosody checks expiry once a minute, so up to ~60 s late.

Guests do not trigger the check (they cannot create rooms under `ENABLE_AUTH=1` anyway); the
room password applies to them once the host has opened the room.

### Settings (`.env`)

```dotenv
RESERVATION_PORT=8600                 # host port of the scheduling page
RESERVATION_ALLOW_UNSCHEDULED=1       # 0 = only scheduled rooms can be opened
RESERVATION_ADHOC_HOURS=12            # lifetime of ad-hoc rooms
RESERVATION_EARLY_JOIN_MIN=10         # room may open this many minutes early
#RESERVATION_UI_PASSWORD=changeme     # basic-auth the scheduling page (any username)
```

Changing these: `docker compose -f … -f reservation.yml up -d` (only the `reservation`
container restarts).

### Files

| Path | Purpose |
|------|---------|
| `reservation.yml` | compose overlay: `reservation` service + prosody env/volume |
| `reservation/app.py` | the service, Python 3 stdlib only, runs on `python:3.12-alpine` (no image build) |
| `reservation/prosody-reservations.cfg.lua` | extra prosody options: `reservations_enable_password_support = true`, 5 s API timeout. Mounted to `/config/conf.d/`, which the prosody entrypoint copies into `/run/prosody/config/conf.d/` (`Include "conf.d/*.cfg.lua"`) |
| `~/.jitsi-meet-cfg/reservation/reservations.db` | sqlite, survives `down` |

Reservation API contract (what prosody calls) is the standard one:
<https://jitsi.github.io/handbook/docs/devops-guide/reservation/> — `POST /conference`
(form-encoded `name`, `start_time`, `mail_owner`), `GET /conference/{id}`, `DELETE /conference/{id}`.
`prosody-reservations.cfg.lua` must re-open `VirtualHost "meet.jitsi"` because conf.d files are
included after the generated file ends on a `Component` section.

### Verify

```bash
curl -s localhost:8600/health                                   # {"ok": true}
curl -s -X POST localhost:8600/conference -d 'name=someroom&mail_owner=x'   # what prosody would get
docker logs jitsi-docker-jitsi-meet-738058b-reservation-1       # every decision is logged
docker logs jitsi-docker-jitsi-meet-738058b-prosody-1 2>&1 | grep reservations
```

### Limits

* No recurring meetings — schedule each occurrence (or copy the link into a recurring calendar event and leave the room unscheduled / ad hoc).
* Scheduling page has no user accounts; use `RESERVATION_UI_PASSWORD` or firewall port 8600.
* The 403 text reaches the client, but the client shows it as a small notification, not a full page.
