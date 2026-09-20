# Password-protected meetings (internal auth)

Rooms require a registered host to log in before anyone can use them. Guests can join
but sit in the "Waiting for the host" screen until a host authenticates.

## What is configured

`.env`:

```dotenv
ENABLE_AUTH=1        # rooms need an authenticated host
ENABLE_GUESTS=1      # unauthenticated users may join once a host is present
AUTH_TYPE=internal   # accounts live in prosody's own DB (no LDAP/JWT)
```

Effect at boot (generated, not edited by hand):

| Component | Result |
|-----------|--------|
| prosody | `VirtualHost "meet.jitsi"` → `authentication = "internal_hashed"`; `guest.meet.jitsi` → `jitsi-anonymous` |
| web | `config.hosts.anonymousdomain = 'guest.meet.jitsi'` — shows the "I am the host" login dialog |
| jicofo | `authentication { enabled = true, type = XMPP, login-url = "meet.jitsi" }` — first authenticated user becomes moderator |

Accounts are stored in `~/.jitsi-meet-cfg/storage/prosody/data/meet%2ejitsi/accounts/`
(bind mount → survive `docker compose down`).

Note: in image `stable-11146-2` prosody renders its config to `/run/prosody/config/`
inside the container, so `prosodyctl` needs `--config`.

## User flow

1. Anyone opens `https://192.168.3.35:8443/RoomName`.
2. Dialog: **Waiting for the host…** → click **I am the host**.
3. Enter username + password of a registered account.
4. Host is in and is moderator. Guests who were waiting are let through
   automatically (lobby still applies if the host enables it).

Username on the login form is just `host` (not `host@meet.jitsi`).

## Manage accounts

All commands run on the docker host in this repo directory.

```bash
# add
docker compose exec prosody prosodyctl --config /run/prosody/config/prosody.cfg.lua \
  register <user> meet.jitsi '<password>'

# change password
docker compose exec prosody prosodyctl --config /run/prosody/config/prosody.cfg.lua \
  passwd <user>@meet.jitsi

# delete
docker compose exec prosody prosodyctl --config /run/prosody/config/prosody.cfg.lua \
  deluser <user>@meet.jitsi

# list
ls ~/.jitsi-meet-cfg/storage/prosody/data/meet%2ejitsi/accounts/
```

Currently registered: `host`.

## Variants

| Want | Change |
|------|--------|
| Everyone must log in, no guests at all | `ENABLE_GUESTS=0` in `.env`, then `docker compose up -d --force-recreate` |
| Per-room password on top (e.g. `1234`) | No config. Moderator → Security options → Add password. Lasts while room is alive. |
| Back to open rooms | Comment out `ENABLE_AUTH`, recreate containers |

Any `.env` change to these three variables needs `docker compose up -d --force-recreate`
(web, prosody, jicofo regenerate their configs at start). Account changes need no restart.
