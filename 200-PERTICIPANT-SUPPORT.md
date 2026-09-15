# 200-Participant Support

Written for the operator/developer of this deployment. What hardware to buy and what to change
so **one room holds 200 people**. Background math is in [ARCHITECTURE.md §3](ARCHITECTURE.md);
how-to-apply mechanics are in [CODING-CHANGE-GUIDE.md](CODING-CHANGE-GUIDE.md). This file is the
shopping list + checklist.

Two targets. Pick one before buying anything:

| Target | Meaning | Hosts | Cost |
|---|---|---|---|
| **T1 — Webinar-style 200** | ≤ 5–10 people with camera/mic at once, rest watch (moderated) | 1 | cable + tuning |
| **T2 — General-purpose 200** | anyone may turn on camera, tile view, unmoderated | 3–4 | 2–3 extra machines + switch |

---

## 0. Baseline (today)

- 1 host: i5-9400 (6c), 19 GiB, NIC **negotiated 100 Mb/s** (gigabit-capable), LAN only.
- Ceiling: ~30–50 cams-on in one room. Bottleneck order: NIC → single JVB → CPU.

---

## 1. Hardware

### 1.1 Network (both targets — do this first)

| Item | Requirement | Why |
|---|---|---|
| Server link | **1 Gb/s** verified with `ethtool enp4s0 → Speed: 1000Mb/s` | current 100 Mb/s caps everything at ~50 people |
| Cable | Cat5e or Cat6, all 4 pairs | 100 Mb/s negotiation = usually 2-pair / damaged cable or 100 Mb switch port |
| Switch | gigabit, non-blocking backplane | 200 clients × ~1.5 Mb/s down ≈ 300 Mb/s aggregate through the switch fabric |
| Client access | wired or Wi-Fi 5/6 APs with ≤ 30–40 clients per AP | 200 laptops on 2–3 APs will fail regardless of server |
| Uplink to internet | not needed for LAN-only | if remote users: ≥ 300 Mb/s symmetric + static IP/DDNS + TURN |

Rule of thumb for link budget: `egress ≈ N × (lastN × 0.15 + 0.3) Mb/s` at 180p thumbnails;
add sender ingress `S × 0.7 Mb/s` (360p simulcast). Keep NIC ≤ 60 % utilised.

### 1.2 T1 — Webinar-style 200 on one host

Current box is enough **once the link is 1 Gb/s**. Budget at 200 viewers, 5 presenters, 360p,
lastN=2: ≈ 200 × 0.6 + 5 × 0.7 ≈ 125 Mb/s egress → ~13 % of a gigabit link.

| Resource | Have | Need | Note |
|---|---|---|---|
| CPU | 6c i5-9400 | 6c is fine; ≥ 8c nicer | JVB ~2–3 cores at this load, Prosody 1 core during join storm |
| RAM | 19 GiB | ≥ 8 GiB | JVB + Jicofo heaps 3 GiB each max |
| NIC | 100 Mb/s | **1 Gb/s** | |
| Disk | any | any SSD | logs only |

### 1.3 T2 — General-purpose 200 (anyone cams on)

Worst case: 200 senders, tile view, lastN=8–12, 360p. Ingress ≈ 200 × 0.7 = 140 Mb/s;
egress ≈ 200 × (10 × 0.15 + 0.3) = 360 Mb/s; **plus** OCTO relay traffic between bridges
(each bridge re-sends every forwarded source to every other bridge once). One gigabit host is
at ~50–60 % NIC and JVB CPU is the next wall — no headroom, no failover. Split it:

| Role | Count | Spec (each) | Reasoning |
|---|---|---|---|
| **Signalling host** (web + prosody + jicofo) | 1 | 4c, 8 GiB, 1 Gb/s | Prosody is single-threaded; isolate it from JVB packet storms. Current i5 box fits this role. |
| **JVB hosts** | 3 (2 minimum) | 4–8c ≥ 3 GHz, 8 GiB, **1 Gb/s each**, wired | ~70 participants/bridge with headroom; N+1 so one bridge dying does not kill the meeting |
| Switch | 1 | gigabit, ≥ 8 ports, non-blocking | all hosts on same L2 segment; OCTO relay uses `JVB_PORT/udp` host-to-host |
| Optional TURN host | 1 | 2c, 2 GiB, public IP | only for off-LAN participants |

Hardware equivalents: three used SFF desktops (i5-8xxx or Ryzen 5) or three 4-vCPU VMs on
*different* physical hosts (VMs on one box share one NIC — pointless). Cloud equivalent:
3 × `c5.xlarge`-class instances.

Why not one bigger host? A 16-core box with a 10 Gb/s NIC also works technically, but
single-JVB CPU ceiling and no failover. OCTO across 3 hosts is cheaper and is the topology
[CLUSTER.md](CLUSTER.md) already points at.

---

## 2. Configuration changes

All `.env` unless marked. Apply with `docker compose up -d`. Verify rendered files per the change guide.

### 2.1 Common (both targets)

```dotenv
# --- video budget ---
RESOLUTION=360
RESOLUTION_WIDTH=640
RESOLUTION_MIN=180
RESOLUTION_WIDTH_MIN=320
CODEC_ORDER_JVB=["VP9","VP8","H264","AV1"]      # AV1 = software encode on most laptops
ENABLE_SIMULCAST=1                             # keep on; lets JVB pick low layer per receiver

# --- join defaults ---
START_AUDIO_MUTED=5                            # everyone after 5th joins muted
START_VIDEO_MUTED=10                           # everyone after 10th joins video-off

# --- room caps / protection ---
MAX_PARTICIPANTS=210                           # hard MUC cap (mod_muc_max_occupants), a bit above target
E2EPING_MAX_CONFERENCE_SIZE=20                 # e2e ping floods presence in big rooms
JICOFO_CONF_MAX_VIDEO_SENDERS=25               # T1: 10   T2: 25–50
JICOFO_CONF_MAX_AUDIO_SENDERS=50
PROSODY_ENABLE_RATE_LIMITS=1
PROSODY_RATE_LIMIT_ALLOW_RANGES=192.168.3.0/24 # LAN exempt so a 200-person join wave is not throttled

# --- memory (current 3 GiB defaults are fine; make explicit) ---
VIDEOBRIDGE_MAX_MEMORY=3072m
JICOFO_MAX_MEMORY=2048m

# --- observability ---
COLIBRI_REST_ENABLED=true
PROSODY_ENABLE_METRICS=true
PROSODY_ENABLE_STANZA_COUNTS=true
```

`~/.jitsi-meet-cfg/web/custom-config.js`:

```js
config.channelLastN = 8;                 // T1: 2–4   T2: 8–12
config.disableThirdPartyRequests = true;
```

Deploy monitoring: `docker compose -f docker-compose.yml -f prometheus.yml -f grafana.yml up -d`.

### 2.2 T1 extras — webinar-style

```dotenv
JICOFO_CONF_MAX_VIDEO_SENDERS=10
ENABLE_AV_MODERATION=1          # default on; moderator locks mic/cam for audience
ENABLE_LOBBY=1                  # default on
ENABLE_AUTH=1                   # so only hosts are moderators
ENABLE_GUESTS=1
AUTH_TYPE=internal              # create host accounts with prosodyctl register
```

`custom-config.js`: `config.channelLastN = 3;`

Run the meeting with AV-moderation on: audience joins muted/video-off and cannot unmute
until a moderator allows. This is what keeps egress at ~125 Mb/s instead of 400+.

### 2.3 T2 extras — OCTO across JVB hosts

**Signalling host** `.env` (in addition to §2.1):

```dotenv
ENABLE_OCTO=1
JICOFO_OCTO_REGION=lan
OCTO_BRIDGE_SELECTION_STRATEGY=RegionBasedBridgeSelectionStrategy
BRIDGE_AVG_PARTICIPANT_STRESS=0.012     # ~65 participants ≈ stress 0.8 → spill to next bridge
BRIDGE_STRESS_THRESHOLD=0.8
JICOFO_ENABLE_BRIDGE_HEALTH_CHECKS=1
JICOFO_ENABLE_ICE_FAILURE_DETECTION=1
```

`docker-compose.override.yml` on signalling host — expose XMPP to JVB hosts and drop the local JVB:

```yaml
services:
  prosody:
    ports:
      - '5222:5222'
  jvb:
    deploy:
      replicas: 0          # do not run a bridge next to Prosody
  web:
    depends_on: !reset []  # `!reset` needed: plain [] would merge with the base list, not clear it
```

(Alternative: keep the local JVB as one of the OCTO bridges — simpler, but Prosody then shares
the NIC/CPU with media. Acceptable for T1, not recommended for T2.)

**Each JVB host** — copy repo, `.env` with only:

```dotenv
CONFIG=~/.jitsi-meet-cfg
XMPP_SERVER=192.168.3.35              # signalling host LAN IP
XMPP_DOMAIN=meet.jitsi
XMPP_AUTH_DOMAIN=auth.meet.jitsi
XMPP_INTERNAL_MUC_DOMAIN=internal-muc.meet.jitsi
JVB_AUTH_PASSWORD=<same as signalling host>
JVB_PORT=10000
JVB_ADVERTISE_IPS=<this host LAN IP>
JVB_INSTANCE_ID=jvb-a                 # unique per host
ENABLE_OCTO=1
JVB_OCTO_REGION=lan
JVB_OCTO_RELAY_ID=<this host LAN IP>  # unique per host
JVB_DISABLE_STUN=1                    # LAN only, no need to hit jitsi.net STUN
COLIBRI_REST_ENABLED=true
VIDEOBRIDGE_MAX_MEMORY=4096m
```

Run: `docker compose up -d jvb`. Only the `jvb` service runs there.

Firewall between hosts: `5222/tcp` JVB→signalling; `10000/udp` clients→JVB **and** JVB↔JVB (OCTO relay).

Verify:

```bash
# signalling host: all bridges registered
docker compose logs jicofo | grep -iE "added new videobridge|bridge.*region"
# during a test with > ~70 people: room spans bridges
curl -s 127.0.0.1:8888/debug | jq '.conferences[] | {name, bridges: [.bridges[]?.jid]}'
# each JVB host
curl -s 127.0.0.1:8080/colibri/stats | jq '{participants, stress_level, octo_endpoints, bit_rate_upload, bit_rate_download}'
```

`ENABLE_OCTO` **must** match on Jicofo and every JVB; mismatch = bridges crash on channel allocation.

### 2.4 Off-LAN participants (either target, optional)

- Static IP or DDNS; router forwards `10000/udp` (and each JVB's port for T2) → `JVB_ADVERTISE_IPS=<lan>,<public>`.
- coturn on a public host: `TURN_HOST`, `TURNS_HOST`, `TURN_PORT=443`, `TURN_CREDENTIALS=<shared secret>`.
- Real TLS cert (`ENABLE_LETSENCRYPT=1`) so mobile browsers accept the WebSocket.

---

## 3. Rollout & acceptance test

1. **Link fix** → `ethtool enp4s0` shows 1000 Mb/s. Stop if not.
2. Apply §2.1 on current host. Smoke test 5 people.
3. **Load test on one host** with `ENABLE_LOAD_TEST_CLIENT=1`: headless Chrome instances on 2–3 spare
   machines hitting `https://192.168.3.35:8443/_load-test/<room>`, ramp 50 → 100 → 150 → 200.
   Watch per 30 s: `stress_level` (JVB), `docker stats` prosody CPU (must stay < 80 % of one core),
   `ip -s link show enp4s0` deltas, browser `chrome://webrtc-internals` packet loss on a real client.
4. T1 passes if 200 load-test viewers + 5 real presenters give < 2 % loss and Prosody < 80 % → **done**.
5. T2: add JVB hosts, enable OCTO, repeat ramp with load-test clients sending video
   (`#config.startWithVideoMuted=false` in the load-test URL). Pass = same loss/CPU criteria on every host
   and Jicofo shows the room on ≥ 2 bridges above ~70 participants.
6. Kill one JVB during the T2 test. Participants on it must re-join another bridge within ~10 s
   (`JICOFO_ENABLE_BRIDGE_HEALTH_CHECKS`).
7. Record results + final `.env` deltas in [ISSUES.md](ISSUES.md); update the capacity table in
   [ARCHITECTURE.md §3](ARCHITECTURE.md).

---

## 4. Summary

| | T1 Webinar 200 | T2 General 200 |
|---|---|---|
| Buy | Cat6 cable / gigabit switch port | + 2–3 JVB machines (4–8c, 8 GiB, 1 Gb/s), gigabit switch |
| Config | §2.1 + §2.2 | §2.1 + §2.3 (OCTO) |
| NIC load | ~125 Mb/s on one host | ~150–250 Mb/s per JVB host |
| Failure mode | one host = single point of failure | N+1 bridges, signalling host still SPOF |
| Effort | hours | 1–2 days incl. load test |
