# Issues

This .md contains the issues that have been worked on.

## TOC
- [Frequently disconnected from meeting](#frequently-disconnected-from-meeting)


## frequently disconnected from meeting
### Summary
jitsi meeting app server running on https://192.168.3.35:8443/, my colleagues from same network was able to connect to it without any issue, however they get frequently disconnected, i checked the discourse in `https://community.jitsi.org/t/tip-how-to-check-udp-10000-connectivity/73031/6`, they said its a udp port issue, if so then how should you fix it. take a look at this issue and solve it.

### Fix Applied by Claude

Fixed. JVB now runs StaticMappingCandidateHarvester(face=172.26.0.3, mask=192.168.3.35) — LAN IP advertised as ICE candidate. Jicofo re-registered bridge.

What was wrong
Not firewall, not port binding — ss showed 0.0.0.0:10000/udp open, ufw/firewalld/nftables all inactive. Problem was JVB advertised wrong IPs:

Candidate	Reachable from LAN?
172.26.0.3 (docker bridge)	No
119.148.19.196 (public, via STUN)	Only via NAT hairpin — flaky
192.168.3.35 (host LAN)	Never advertised
Clients connected via peer-reflexive candidates / hairpin → worked sometimes, ICE failed often → "disconnected". Two-person calls likely fine (P2P), 3+ hit JVB → drops.

Fix applied
.env:41: JVB_ADVERTISE_IPS=192.168.3.35, then docker compose up -d --force-recreate jvb.

Notes
Public IP 119.148.19.19x changes between restarts (.196 → .194) — dynamic ISP. If remote (non-LAN) users ever needed, forward 10000/udp on router and add public IP or DDNS to JVB_ADVERTISE_IPS (comma-separated). Not needed for LAN-only.
Test: 3+ people join, open chrome://webrtc-internals → selected candidate pair should show 192.168.3.35:10000.
Discourse test from thread still valid: nc -u -z -v 192.168.3.35 10000 from colleague machine while call active.