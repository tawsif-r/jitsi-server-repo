# Architecture

Jitsi Meet stack on Docker Compose. Written for developers/operators of **this** deployment
(single host `192.168.3.35`), not as generic Jitsi docs. Numbers below were measured on
2026-09-15 from the running stack.

Companion docs: [CODING-CHANGE-GUIDE.md](CODING-CHANGE-GUIDE.md) (how to change things safely),
[CLUSTER.md](CLUSTER.md) (multi-JVB cluster reference), [ISSUES.md](ISSUES.md) (past incidents).

---

## 1. What runs today

| Service | Image (`stable-11146-2`) | Role | Exposed on host | Heap |
|---|---|---|---|---|
| `web` | `ghcr.io/jitsi/web` | nginx: serves the React client, terminates TLS, reverse-proxies BOSH / XMPP-WebSocket to Prosody | `8000/tcp` (HTTP→redirect), `8443/tcp` (HTTPS) | – |
| `prosody` | `ghcr.io/jitsi/prosody` | XMPP server: auth, MUC rooms, lobby, breakout, presence, all signalling | none (internal `5222`, `5269`, `5347`, `5280`) | Lua, single-threaded |
| `jicofo` | `ghcr.io/jitsi/jicofo` | Focus: room controller, picks a JVB per conference, allocates COLIBRI channels, sends Jingle offers | `127.0.0.1:8888` (REST/health) | `-Xmx3072m` |
| `jvb` | `ghcr.io/jitsi/jvb` | Selective Forwarding Unit: receives every participant's RTP, forwards to others (no transcoding) | `10000/udp` (media), `127.0.0.1:8080` (COLIBRI stats) | `-Xmx3072m` |

Not deployed (overlay files exist, unused): `jibri.yml` (recording), `jigasi.yml` (SIP),
`transcriber.yml`, `etherpad.yml`, `whiteboard.yml`, `prometheus.yml`, `grafana.yml`,
`log-analyser.yml`, `rtcstats.yml`. No TURN/coturn. No OCTO. No Visitors.

### Host

| Item | Value | Note |
|---|---|---|
| CPU | Intel i5-9400, 6 cores, no HT | shared by all 4 containers |
| RAM | 19 GiB, 0 swap used | idle stack uses ~560 MiB; JVB+Jicofo may grow to 3 GiB each |
| NIC | `enp4s0`, **linked at 100 Mb/s full duplex** | card supports `1000baseT/Full`; cable or switch port is capping it |
| LAN IP | `192.168.3.35/24` | `PUBLIC_URL=https://192.168.3.35:8443`, `JVB_ADVERTISE_IPS=192.168.3.35` |
| WAN | dynamic ISP IP (`119.148.19.19x`), no port-forward | LAN-only deployment (see [ISSUES.md](ISSUES.md)) |
| Docker net | `meet.jitsi` bridge, JVB container `172.26.0.4` | ice4j static-mapping `172.26.0.4 → 192.168.3.35` |

### Effective `.env` (non-secret deltas from `env.example`)

```
PUBLIC_URL=https://192.168.3.35:8443
JVB_ADVERTISE_IPS=192.168.3.35
CONFIG=~/.jitsi-meet-cfg
```

Auth: `ENABLE_AUTH=1`, `ENABLE_GUESTS=1`, `AUTH_TYPE=internal` (see AUTH.md). Scheduling/reservation sidecar: `reservation.yml` (see SCHEDULING.md). Everything else is template default: `ENABLE_P2P=true`,
`ENABLE_SIMULCAST=true`, `RESOLUTION=720`, `CODEC_ORDER_JVB=[AV1,VP9,VP8,H264]`,
`START_AUDIO_MUTED=10`, `START_VIDEO_MUTED=10`, `MAX_PARTICIPANTS` unset (no cap),
`channelLastN` unset (client adaptive), `ENABLE_XMPP_WEBSOCKET=1`, lobby / breakout / AV-moderation / polls on.

---

## 2. Topology

```mermaid
flowchart LR
    subgraph Browser
        C[Jitsi Meet client]
    end
    subgraph host["Host 192.168.3.35 (docker network meet.jitsi)"]
        W[web / nginx<br/>:8443 TLS]
        P[prosody<br/>xmpp.meet.jitsi:5222 / :5280]
        J[jicofo<br/>focus@auth.meet.jitsi]
        V[jvb<br/>jvb@auth.meet.jitsi]
    end
    C -- "HTTPS: static app, config.js" --> W
    C -- "wss://…/xmpp-websocket (signalling)" --> W
    W -- "proxy to :5280" --> P
    J -- "XMPP client conn" --> P
    V -- "XMPP client conn, joins jvbbrewery@internal-muc" --> P
    J -. "COLIBRI over XMPP (channel alloc)" .-> V
    C == "SRTP/DTLS media + SCTP data channel<br/>UDP 10000" ==> V
```

### XMPP domains (all inside one Prosody)

| Domain | Purpose |
|---|---|
| `meet.jitsi` | client VirtualHost, `jitsi-anonymous` auth |
| `auth.meet.jitsi` | service accounts: `focus`, `jvb` (`unlimited_jids`, no rate limit) |
| `muc.meet.jitsi` | conference rooms (memory storage, `muc_room_cache_size=10000`) |
| `internal-muc.meet.jitsi` | `jvbbrewery` — JVBs advertise presence+stats here; Jicofo reads them for bridge selection |
| `lobby.meet.jitsi`, `breakout.meet.jitsi` | lobby & breakout MUCs |
| `focus.meet.jitsi` | `client_proxy` component → `focus@auth` |
| `speakerstats.`, `avmoderation.`, `endconference.`, `metadata.`, `polls.` | per-room feature components |

### Call setup sequence

1. Browser loads `/` from nginx, fetches `/config.js` (rendered from env at container start).
2. Client opens `wss://192.168.3.35:8443/xmpp-websocket` → nginx → Prosody `:5280`.
3. Client joins `room@muc.meet.jitsi`. Prosody invites `focus` (Jicofo) into the room.
4. Jicofo picks a JVB from `jvbbrewery` (only one exists), allocates COLIBRI channels,
   sends a Jingle `session-initiate` to the client.
5. Client and JVB do ICE (JVB candidate = `192.168.3.35:10000/udp`), DTLS, then SRTP flows.
6. Two-person rooms use **P2P** (browser↔browser) and never touch JVB; third participant
   triggers a switch to JVB.

### Config generation pipeline

`.env` → compose `environment:` list → container start → s6 `10-config` service runs
`tpl /defaults/<template> > /run/<svc>/config/...` → daemon reads `/run/...`.
Templates live in `<svc>/rootfs/defaults/`. Templates are **baked into the image**;
editing them in this repo does nothing until you rebuild (`make build_<svc>`).
Runtime overrides live in `${CONFIG}` (`~/.jitsi-meet-cfg`) — see the change guide.

---

## 3. Can this run a 200-participant general-purpose meeting?

**No. Not as deployed.** Realistic single-room ceiling today is roughly **30–50 participants
with cameras on**, or **~80–100 in an audio-first / few-presenters layout**. Reasons, in order
of severity:

### 3.1 Network: 100 Mb/s NIC (hard blocker)

JVB is an SFU: every participant uploads once, JVB re-sends to every receiver for each
forwarded stream (`lastN`). Bandwidth scales with `senders + receivers × lastN`, all through
one NIC, shared with HTTPS + WebSocket signalling.

Per-stream budget (Jitsi defaults, VP8/VP9): audio ≈ 50 kbps incl. overhead; video 180p ≈ 0.15–0.2 Mbps,
360p ≈ 0.5–0.7 Mbps, 720p ≈ 1.5–2.5 Mbps; a simulcast sender at 720p uploads all three layers ≈ 2.5 Mbps.

| Scenario, 200 participants | JVB ingress | JVB egress | Total | vs 100 Mb/s | vs 1 Gb/s |
|---|---|---|---|---|---|
| A. General meeting: all cams on, tile view (~25 visible tiles @180p) | 200 × 2.5 ≈ 500 Mb/s | 200 × (25 × 0.15 + 0.25) ≈ 800 Mb/s | ≈ 1.3 Gb/s | 13× over | ~1.3× over |
| A′. Same, but `RESOLUTION=360`, `channelLastN=8` | 200 × 0.7 ≈ 140 Mb/s | 200 × (8 × 0.15 + 0.25) ≈ 290 Mb/s | ≈ 430 Mb/s | 4× over | fits (~45%) |
| B. Webinar-ish: 5 presenters with video, 195 muted viewers, `RESOLUTION=360`, `lastN=2` | 5 × 0.7 ≈ 4 Mb/s | 200 × (0.7 + 0.15 + 0.25) ≈ 220 Mb/s | ≈ 225 Mb/s | 2× over | fits (~25%) |
| C. What fits today: cams on, BWE squeezes to ~0.6 Mb/s up, lastN≈4–8 | N × 0.6 | N × (0.6–1.2) | ≤ 80 Mb/s usable → **N ≈ 35–55** | — | — |

The NIC advertises `1000baseT/Full` but negotiated 100 — fix the cable (Cat5e+) or the switch
port first. That alone moves the ceiling ~10×.

### 3.2 Single JVB, no OCTO (blocker for growth)

`ENABLE_OCTO` is unset, so one conference is pinned to exactly one bridge. Adding a second
JVB container helps only when there are many *rooms*, not one big room. To spread one room
across bridges you need OCTO (`ENABLE_OCTO=1` on **both** jicofo and every jvb, plus
`JVB_OCTO_BIND_ADDRESS`/`JVB_OCTO_RELAY_ID`/`JVB_OCTO_REGION`). This is the fix
[CLUSTER.md](CLUSTER.md) points to.

### 3.3 CPU: 6 cores shared by 4 services (soft limit)

JVB does no transcoding; its CPU cost is packet forwarding + SRTP + bandwidth estimation.
Public Jitsi load tests show one JVB saturating a 1 Gb/s link at well under 100% of 4 cores,
and the [CLUSTER.md](CLUSTER.md) report shows a 4-core JVB "hot" at ~60 participants with
simulcast *disabled* (worst case). Rough expectation for this box at 360p with simulcast on:
**~100–150 participants in one room** before JVB CPU becomes the wall — *if* the NIC were 1 Gb/s.

Prosody is single-threaded Lua. Every join/leave/mute/raise-hand fans presence out to all
N occupants (O(N²) over a full join wave; 200 joins ≈ 20 000 stanzas). 200 in one room is
workable on one modern core but shares the 6 cores with JVB; keep features that spam presence
(e2eping, speaker stats, reactions) trimmed. Above ~300–500 in one room Jitsi's own answer is
Visitors (separate Prosody nodes), not a bigger core.

Jicofo is not a bottleneck at this scale.

### 3.4 Other gaps for a 200-person meeting

- **LAN only.** Only `192.168.3.35` is advertised; no TURN; ISP IP is dynamic and not forwarded. All 200 must be on the `192.168.3.0/24` LAN.
- **No guard rails.** `MAX_PARTICIPANTS` unset, `channelLastN` unset, `RESOLUTION=720`, `START_VIDEO_MUTED=10` (only participants after the 10th join video-muted). A 200-person room with defaults will drive the NIC to saturation and every call degrades at once.
- **AV1 first in codec order.** AV1 is software-encoded in most browsers; fine for 5 people, painful for weak laptops in a large room. VP9 or VP8 first is safer at scale.
- **No observability.** `prometheus.yml`/`grafana.yml` exist but are not deployed; you cannot see JVB stress or Prosody CPU during a big call.
- **Client-side.** Browsers handle 200-occupant rooms fine when `lastN` is bounded; tile view paginates. Not the limiting factor.

### 3.5 Verdict & sizing ladder

| Target | What is required |
|---|---|
| ≤ 50, cams on (today) | Nothing. Optionally cap `MAX_PARTICIPANTS`, `RESOLUTION=360`, lastN. |
| 100–150, cams on, one room | 1 Gb/s link (fix cable/switch). `RESOLUTION=360`, `channelLastN≈8`, VP9/VP8 first, `MAX_PARTICIPANTS`, `E2EPING_MAX_CONFERENCE_SIZE` low, `JICOFO_CONF_MAX_VIDEO_SENDERS`. Dedicated host preferred. |
| 200, webinar-style (few presenters, rest muted) | Everything above + `START_WITH_VIDEO_MUTED`, `JICOFO_CONF_MAX_VIDEO_SENDERS≈5`, `JICOFO_CONF_MAX_AUDIO_SENDERS`, lobby/AV-moderation. Fits on one 1 Gb/s host with ~25% NIC headroom. |
| 200, general-purpose (anyone can turn on cam) | Above + **OCTO with 2–3 JVBs on separate hosts, each ≥ 1 Gb/s**, ideally a dedicated Prosody/Jicofo host, monitoring stack deployed, TURN if anyone is off-LAN. |
| 500+ webinar | Visitors (`ENABLE_VISITORS=1`, ≥1 `PROSODY_MODE=visitors` node, `VISITORS_MAX_VISITORS_PER_NODE`) + OCTO. |

---

## 4. Ports & data paths reference

| Path (host) | Mounted at | Content |
|---|---|---|
| `~/.jitsi-meet-cfg/web` | `web:/config` | `custom-config.js`, `custom-interface_config.js`, `nginx/custom-meet.conf`, `nginx-custom/*.conf`, `keys/` |
| `~/.jitsi-meet-cfg/storage/web` | `web:/storage` | self-signed/ACME certs (persistent) |
| `~/.jitsi-meet-cfg/prosody/config` | `prosody:/config` | extra `conf.d/*.cfg.lua`, certs |
| `~/.jitsi-meet-cfg/prosody/prosody-plugins-custom` | `prosody:/prosody-plugins-custom` | custom Lua modules (first in `plugin_paths`) |
| `~/.jitsi-meet-cfg/storage/prosody` | `prosody:/var/lib/prosody` | account data |
| `~/.jitsi-meet-cfg/jicofo` | `jicofo:/config` | `custom-jicofo.conf` (HOCON, `include`d last) |
| `~/.jitsi-meet-cfg/jvb` | `jvb:/config` | `custom-jvb.conf` (HOCON, `include`d last), `custom-sip-communicator.properties` |

All containers are `read_only: true` with 16 MiB tmpfs on `/run` and `/tmp`; rendered configs
live under `/run/<svc>/config` and are regenerated on every restart.

Health/stats endpoints (host-local only): `curl 127.0.0.1:8080/colibri/stats` (JVB),
`curl 127.0.0.1:8888/about/health` (Jicofo).
