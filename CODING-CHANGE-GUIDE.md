# Coding & Change Guide

Written for developers who need to change this deployment. Read [ARCHITECTURE.md](ARCHITECTURE.md)
first for what runs where. This guide answers: *where* does a change go, *how* do I apply it,
and *how* do I prove it worked.

Golden rule: **this repo is a fork of upstream `jitsi/docker-jitsi-meet`.** Keep it rebasable.
Prefer runtime overrides (`.env`, `${CONFIG}` files, `docker-compose.override.yml`) over editing
templates or `docker-compose.yml`. Only touch image templates/Dockerfiles when no override hook exists,
and then keep the diff minimal and commented.

---

## 1. Decision table — where does my change go?

| I want to… | Put it in | Applies via | Commit? |
|---|---|---|---|
| Toggle a documented feature / set a value that has an env var (`RESOLUTION`, `MAX_PARTICIPANTS`, `ENABLE_OCTO`, …) | `.env` | `docker compose up -d` (recreates changed services) | No (`.env*` is gitignored). Mirror non-secret defaults into `env.example` if they should be the team default. |
| Set a client `config.js` option with no env var (`channelLastN`, `disableTileView`, `toolbarButtons` edge cases…) | `~/.jitsi-meet-cfg/web/custom-config.js` | restart `web` | No (outside repo). Document in this file. |
| Change `interface_config.js` | `~/.jitsi-meet-cfg/web/custom-interface_config.js` | restart `web` | No |
| Add nginx `location`/`server` snippets | `~/.jitsi-meet-cfg/web/nginx/custom-meet.conf` (appended inside the `server {}`), or `~/.jitsi-meet-cfg/web/nginx-custom/*.conf` (included at server scope) | restart `web` | No |
| Bring my own TLS cert | `~/.jitsi-meet-cfg/web/keys/cert.crt` + `cert.key` | restart `web` | No |
| JVB HOCON setting with no env var | `~/.jitsi-meet-cfg/jvb/custom-jvb.conf` | restart `jvb` | No |
| Jicofo HOCON setting with no env var | `~/.jitsi-meet-cfg/jicofo/custom-jicofo.conf` | restart `jicofo` | No |
| Add / override a Prosody module (Lua) | `~/.jitsi-meet-cfg/prosody/prosody-plugins-custom/mod_x.lua`, enable via `XMPP_MODULES` / `XMPP_MUC_MODULES` / `GLOBAL_MODULES` in `.env` | restart `prosody` | Module source: yes, keep a copy under `prosody/rootfs/prosody-plugins/` only if it should ship in the image |
| Extra Prosody config blocks | `~/.jitsi-meet-cfg/prosody/config/conf.d/*.cfg.lua` (auto-`Include`d) or `XMPP_CONFIGURATION` / `GLOBAL_CONFIG` env (comma-separated lines) | restart `prosody` | No |
| Add a service (2nd JVB, coturn, prometheus…) or change ports/resources | `docker-compose.override.yml` (gitignored) for local; a new `*.yml` overlay in repo root if reusable | `docker compose -f docker-compose.yml -f x.yml up -d` | Overlay yes; override no |
| Change a template default (`<svc>/rootfs/defaults/*`) or Dockerfile | the template | `make build_<svc>` + set `JITSI_IMAGE_REPO=jitsi`/`JITSI_IMAGE_VERSION=latest` in `.env`, then `up -d` | Yes, with a comment explaining why no override hook was usable |

Never edit files under `/run/...` inside a container — they are regenerated on every start.

---

## 2. Workflow

```bash
# 1. Render what compose will actually run (catches env typos, missing vars)
docker compose config > /dev/null

# 2. Apply. Compose only recreates services whose env/config changed.
docker compose up -d

# 3. Verify the rendered config inside the container
docker compose exec jvb     cat /run/jvb/config/jvb.conf
docker compose exec jicofo  cat /run/jicofo/config/jicofo.conf
docker compose exec prosody cat /run/prosody/config/conf.d/jitsi-meet.cfg.lua
docker compose exec web     cat /run/web/config/config.js | tail -40   # custom-config.js is appended last

# 4. Watch logs while testing
docker compose logs -f --tail=100 jvb jicofo prosody
```

Health checks (host-local):

```bash
curl -s 127.0.0.1:8080/colibri/stats | jq '{participants, conferences, stress_level, total_loss_degraded_participant_seconds, bit_rate_download, bit_rate_upload}'
curl -s 127.0.0.1:8888/about/health
```

Client-side verification: `chrome://webrtc-internals` → selected candidate pair must be
`192.168.3.35:10000/udp`; `Ctrl+Shift+D`-style stats in the meeting show bridge vs P2P.
Secrets: `.env` holds live passwords. `./gen-passwords.sh` regenerates them **and breaks running
containers until every service is recreated**. Never paste `.env` into issues/docs.

---

## 3. Recipes for the scaling work in ARCHITECTURE.md §3

All are `.env`-level unless noted. Values are starting points, not gospel — load test.

### 3.1 Guard rails for one large room (do these first)

```dotenv
RESOLUTION=360
RESOLUTION_WIDTH=640
RESOLUTION_MIN=180
RESOLUTION_WIDTH_MIN=320
CODEC_ORDER_JVB=["VP9","VP8","H264","AV1"]
START_VIDEO_MUTED=10          # participants after the Nth join with video off
START_AUDIO_MUTED=10
MAX_PARTICIPANTS=200          # enables mod_muc_max_occupants
E2EPING_MAX_CONFERENCE_SIZE=20
JICOFO_CONF_MAX_VIDEO_SENDERS=25
JICOFO_CONF_MAX_AUDIO_SENDERS=50
PROSODY_ENABLE_RATE_LIMITS=1
PROSODY_RATE_LIMIT_ALLOW_RANGES=192.168.3.0/24   # LAN exempt: a 200-person join wave must not get throttled
```

`~/.jitsi-meet-cfg/web/custom-config.js` (no env var for these):

```js
config.channelLastN = 8;   // max forwarded video streams per receiver; -1 = unlimited (current)
```

Reasoning: egress ≈ N × (lastN × 0.15 Mb/s + audio). At N=200, lastN=8 that is ~290 Mb/s; at
lastN=2 ~100 Mb/s. Pick lastN to your link.

### 3.2 Fix the link before anything else

```bash
ethtool enp4s0 | grep -E 'Speed|Duplex'     # currently 100Mb/s; card supports 1000baseT
```

Replace cable / move switch port, re-check. Compose changes are pointless while this is 100 Mb/s.

### 3.3 Second JVB on the **same** host (many rooms, not one big room)

`docker-compose.override.yml` — copy the whole `jvb:` block from `docker-compose.yml`, rename it,
and change only what is listed below. Do **not** use `extends:` — compose *merges* `ports:` lists,
so `jvb2` would also claim `10000/udp` and fail to start.

```yaml
services:
  jvb2:
    # ...identical to `jvb` except:
    ports:
      - '10001:10001/udp'
      - '127.0.0.1:8081:8080'
    volumes:
      - ${CONFIG}/jvb2:/config:Z          # separate custom-jvb.conf if needed
    environment:
      # ...same list as jvb, plus:
      - JVB_PORT=10001
      - JVB_INSTANCE_ID=jvb-2
```

Each JVB needs a unique `JVB_PORT` (media) and `JVB_INSTANCE_ID` (MUC nickname). Jicofo
discovers both through `jvbbrewery@internal-muc.meet.jitsi`; no Jicofo change. Verify with
`docker compose logs jicofo | grep -i "added new videobridge"`.

### 3.4 OCTO — one room across several JVBs (required for 200 general-purpose)

Set on **jicofo and every JVB** (they must agree or bridges crash on octo channels):

```dotenv
ENABLE_OCTO=1
JICOFO_OCTO_REGION=lan
OCTO_BRIDGE_SELECTION_STRATEGY=RegionBasedBridgeSelectionStrategy   # SplitBridgeSelectionStrategy only for testing
JVB_OCTO_REGION=lan
JVB_OCTO_RELAY_ID=<unique per JVB, e.g. its LAN IP or instance id>
```

Note: `jvb/rootfs/defaults/jvb.conf` renders only `relay.enabled / region / relay-id`;
`JVB_OCTO_BIND_ADDRESS` is used solely as the fallback for `relay-id`. Relay traffic rides the
normal ICE UDP port (`JVB_PORT`).

JVB relay traffic uses the same UDP media port between bridges; bridges on different hosts must
reach each other on `JVB_PORT/udp`. `BRIDGE_STRESS_THRESHOLD` (default 0.8) and
`BRIDGE_AVG_PARTICIPANT_STRESS` (default 0.01 → ~80 participants ≈ "full") tune when Jicofo
spills a room to a second bridge. Extra JVBs on **other hosts** point at this Prosody with
`XMPP_SERVER=192.168.3.35` and need `5222/tcp` exposed (today it is `expose:` only — needs a
`ports:` entry in the override).

### 3.5 Visitors — 500+ webinar

Separate Prosody containers with `PROSODY_MODE=visitors`, `PROSODY_VISITOR_INDEX=0..n`, main
Prosody/Jicofo get `ENABLE_VISITORS=1`, `VISITORS_XMPP_SERVER=host1,host2`, `VISITORS_MAX_VISITORS_PER_NODE`.
Requires s2s (`5269`) between nodes. Follow upstream handbook "Visitors"; the templates in
`prosody/rootfs/defaults/conf.d/visitors.cfg.lua` and `jicofo.conf` already support it.

### 3.6 Off-LAN participants

`JVB_ADVERTISE_IPS=192.168.3.35,<public-or-DDNS>` + forward `10000/udp` on the router, and add
coturn (`TURN_HOST`, `TURNS_HOST`, `TURN_CREDENTIALS`) for clients behind strict NAT. Dynamic
ISP IP means DDNS or re-`up` on change.

### 3.7 Monitoring before load testing

```bash
docker compose -f docker-compose.yml -f prometheus.yml -f grafana.yml up -d
```

Set `COLIBRI_REST_ENABLED=true` and `PROSODY_ENABLE_METRICS=true` / `PROSODY_ENABLE_STANZA_COUNTS=true`.
Then load test: `ENABLE_LOAD_TEST_CLIENT=1` exposes `/_load-test/<room>` for scripted headless
browsers (see upstream `jitsi-meet/resources/load-test`). Watch `stress_level` in COLIBRI stats,
Prosody CPU (`docker stats`), and NIC (`sar -n DEV 1` / `ip -s link`).

---

## 4. Repo conventions

- Branch off `main`; one concern per PR. Commit messages: Conventional Commits, subject ≤ 50 chars.
- Keep `docker-compose.yml` byte-identical to upstream where possible; add services via overlays.
- Pin `JITSI_IMAGE_VERSION` when changing it; bump all four core images together (Jicofo/JVB/Prosody wire protocols move in lockstep).
- Anything that changes capacity assumptions → update ARCHITECTURE.md §3 table.
- Anything that fixes an incident → append to [ISSUES.md](ISSUES.md) with symptom, root cause, fix, verification.
- Don't commit `.env`, `.env.bak`, `docker-compose.override.yml`, or anything under `~/.jitsi-meet-cfg` containing keys.

## 5. Things that look editable but aren't

- `web/rootfs/defaults/*.js`, `jvb/rootfs/defaults/jvb.conf`, etc. — image templates. Editing without `make build_<svc>` + switching `JITSI_IMAGE_REPO` has no effect.
- `examples/` — empty stub; upstream moved examples to `jitsi-contrib`.
- `CHANGELOG.md` — upstream's; don't add local entries.
- `resources/` — README artwork only.
