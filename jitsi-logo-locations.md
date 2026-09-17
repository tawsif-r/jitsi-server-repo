# Jitsi Logo & Asset Locations

Where the Jitsi branding (logos, icons, images) lives in this deployment, and what
controls it. Verified against the running `web` container
(`ghcr.io/jitsi/web:stable-11146-2`, container `jitsi-docker-jitsi-meet-738058b-web-1`).

## TL;DR — the landing page logo

The logo + "Jitsi" wordmark at the top of `https://192.168.3.35:8443/` is **one SVG**:

| What | Where |
|---|---|
| File (inside `web` container) | `/usr/share/jitsi-meet/images/watermark.svg` (71×32, 6 `<path>`s — icon and "jitsi" wordmark are both paths, no `<text>`) |
| Served at | `https://192.168.3.35:8443/images/watermark.svg` |
| Config key that selects it | `DEFAULT_WELCOME_PAGE_LOGO_URL: 'images/watermark.svg'` in `interface_config.js` (line 30) |
| Toggle | `SHOW_JITSI_WATERMARK: true` (line 130) |
| Click target | `JITSI_WATERMARK_LINK: 'https://jitsi.org'` (line 74) |
| The "Jitsi Meet" heading next to it | Text string, not part of the SVG: `welcomepage.headerTitle` in `/usr/share/jitsi-meet/lang/main.json:1739`. Subtitle "Secure and high quality meetings" is `welcomepage.headerSubtitle` (line 1738) |

Nothing on the host filesystem holds these files — they ship baked into the image.
The repo's `web/` build context does not contain them either (it only installs the
`jitsi-meet-web` Debian package, see `web/Dockerfile`).

## Where `interface_config.js` actually lives

Important for overrides — there are three copies:

1. **Image default:** `/defaults/interface_config.js` in the container.
   Created by `web/Dockerfile:25` (`mv /usr/share/jitsi-meet/interface_config.js /defaults`).
2. **Rendered at boot:** `/run/web/config/interface_config.js` (tmpfs).
   `web/rootfs/etc/s6-overlay/scripts/config:147` copies (1) here, then line 148-150
   appends `/run/web/config/custom-interface_config.js` if it exists.
3. **Served by nginx:** `location = /interface_config.js { alias /run/web/config/interface_config.js; }`
   (`web/rootfs/defaults/meet.conf:50-51`).

Host-side hook: `${CONFIG}/web` = `~/.jitsi-meet-cfg/web` is mounted at `/config`
and copied to `/run/web/config` at startup (`config` script line 7). So a file at
`~/.jitsi-meet-cfg/web/custom-interface_config.js` ends up appended to the served
`interface_config.js`. Same pattern for `custom-config.js` → `config.js` (line 143-145).

Note: `~/.jitsi-meet-cfg/web/` is currently **empty** on this host.

## Static asset directory (inside `web` container)

`/usr/share/jitsi-meet/images/` — served at `/images/...` via
`web/rootfs/defaults/meet.conf:68-70` (regex location for
`libs|css|static|images|fonts|lang|sounds|...`).

### Jitsi-branded files

| File | Used by | Reference location |
|---|---|---|
| `images/watermark.svg` | Welcome page header logo; also the in-meeting top-left watermark | `interface_config.js:30` (`DEFAULT_WELCOME_PAGE_LOGO_URL`); `interface_config.js:222` (`DEFAULT_LOGO_URL`, commented — JS bundle hardcodes `images/watermark.svg` as fallback in `libs/app.bundle.min.js`) |
| `images/favicon.svg` | Browser tab icon | `/usr/share/jitsi-meet/title.html:9` (`<link rel="icon" href="images/favicon.svg?v=1">`) |
| `images/jitsilogo.png` | OpenGraph / schema.org share preview image | `title.html:3` (`og:image`), `title.html:8` (`itemprop="image"`) |
| `images/apple-touch-icon.png` | iOS home-screen icon | `/usr/share/jitsi-meet/index.html:10`; `static/offline.html:11` |
| `images/logo-deep-linking.png` | Desktop deep-linking page ("Launching your meeting in…") | hardcoded in `libs/app.bundle.min.js`; hide via `HIDE_DEEP_LINKING_LOGO` (`interface_config.js:198`, commented) |
| `images/logo-deep-linking-mobile.png` | Mobile deep-linking page | hardcoded in `libs/app.bundle.min.js` |
| `static/pwa/icons/icon192.png`, `icon512.png`, `iconMask.png` | PWA install icon | `/usr/share/jitsi-meet/manifest.json` (linked from `index.html`) |
| `images/welcome-background.png` | Welcome page background | `css/all.css` (`url(../images/welcome-background.png)`) |

### Text branding (not images)

| String | Location |
|---|---|
| `APP_NAME: 'Jitsi Meet'` | `interface_config.js:12` |
| `PROVIDER_NAME: 'Jitsi'` | `interface_config.js:103` |
| `NATIVE_APP_NAME: 'Jitsi Meet'` | `interface_config.js:193` (commented) |
| `<title>Jitsi Meet</title>`, `og:title`, `og:description` | `/usr/share/jitsi-meet/title.html:1-7` |
| `"name": "Jitsi Meet"`, `"short_name"`, `theme_color #17A0DB` | `/usr/share/jitsi-meet/manifest.json` |
| `welcomepage.headerTitle` / `headerSubtitle` / `jitsiOnMobile` | `/usr/share/jitsi-meet/lang/main.json:1738-1741` |

### Third-party / non-Jitsi images in the same dir

`GIPHY_icon.png`, `GIPHY_logo.png`, `app-store-badge.png`, `google-play-badge.png`,
`f-droid-badge.png`, `btn_google_signin_dark_normal.png`, `chromeLogo.svg`,
`googleLogo.svg`, `microsoftLogo.svg`, `dropboxLogo_square.png`, `calendar.svg`,
`avatar.png`, `flags.png` / `flags@2x.png`, `icon-cloud.png`, `icon-info.png`,
`icon-users.png`, `downloadLocalRecording.png`, `share-audio.gif`,
`virtual-background/background-{1..7}.jpg`.

Other asset dirs at the same level: `/usr/share/jitsi-meet/{css,fonts,lang,libs,sounds,static}`.

## Other branding knobs (for later)

- `SHOW_BRAND_WATERMARK` / `BRAND_WATERMARK_LINK` (`interface_config.js:121`, `:25`) — second, custom watermark.
- `SHOW_POWERED_BY` (`interface_config.js:131`).
- `POLICY_LOGO` (`interface_config.js:102`).
- Dynamic branding via env: `DYNAMIC_BRANDING_URL` / `BRANDING_DATA_URL`
  → `config.dynamicBrandingUrl` / `config.brandingDataUrl`
  (`web/rootfs/defaults/settings-config.js:390-395`). JSON there can set `logoImageUrl`,
  `logoClickUrl`, `backgroundImageUrl`, etc. without touching image files.
- `static/welcomePageAdditionalContent.html` — empty template, injectable extra content on landing page.

## Quick commands

```bash
W=jitsi-docker-jitsi-meet-738058b-web-1
docker exec $W ls /usr/share/jitsi-meet/images/
docker cp $W:/usr/share/jitsi-meet/images/watermark.svg ./watermark.svg
docker exec $W grep -nE "LOGO|WATERMARK|APP_NAME|PROVIDER_NAME" /run/web/config/interface_config.js
```

---

## Applied override: DNS Meet branding (2026-09-17)

All changes are runtime overrides — no image rebuild, no edits to upstream files.
Source of truth is `branding/` + `docker-compose.override.yml` (auto-merged by
`docker compose`). Apply with `docker compose up -d web`.

### Files in `branding/`

| File | Mounted at (in `web` container) | Purpose |
|---|---|---|
| `logo.png` | `images/logo.png`, `images/jitsilogo.png`, `images/logo-deep-linking.png`, `images/logo-deep-linking-mobile.png` | Real PNG (converted from root `logo.png`, which is actually JPEG data) |
| `apple-touch-icon.png` | `images/apple-touch-icon.png` | 180×180 padded |
| `pwa/icon192.png`, `pwa/icon512.png`, `pwa/iconMask.png` | `static/pwa/icons/*` | PWA icons |
| `title.html` | `title.html` (SSI-included into `index.html`) | `<title>DNS Meet`, `og:*`, favicon → `images/logo.png` |
| `manifest.json` | `manifest.json` | PWA name "DNS Meet" |
| `lang/main.json` | `lang/main.json` | Fallback translations, Jitsi → DNS Meet |
| `custom-interface_config.js` | `/config/custom-interface_config.js` → appended to `interface_config.js` | `APP_NAME`, `NATIVE_APP_NAME`, `PROVIDER_NAME`, `DEFAULT_LOGO_URL`, `DEFAULT_WELCOME_PAGE_LOGO_URL` |
| `custom-config.js` | `/config/custom-config.js` → appended to `config.js` | `config.dynamicBrandingUrl = '/static/branding.json'` |
| `branding.json` | `static/branding.json` | Dynamic branding: `logoImageUrl`, `labels.en` → URL |
| `labels-en.json` | `static/labels-en.json` | English i18n overrides merged at runtime |

### Why dynamic branding for the text

English strings are **baked into `libs/app.bundle.min.js`** — `lang/main.json` is only
a fallback and is not fetched for `en`. Jitsi's dynamic-branding feature
(`config.dynamicBrandingUrl`) merges `labels.<lang>` (a URL to a JSON file, not an
inline object) into i18next at runtime. That is what flips `welcomepage.headerTitle`
to "DNS Meet" without patching the bundle.

### Not changed

- `lang/main.json:872` "Jitsi as a Service" (external product link) — left as-is.
- Non-English translations (`lang/main-*.json`) still say Jitsi. Add `labels.<lang>` entries in `branding.json` + a `labels-<lang>.json` if needed.
- `images/watermark.svg`, `images/favicon.svg` still exist in the image but nothing references them now.

### Verify

```bash
curl -sk https://192.168.3.35:8443/interface_config.js | grep -n "DNS"
curl -sk https://192.168.3.35:8443/ | grep -n "<title>"
curl -sk https://192.168.3.35:8443/static/labels-en.json | head
```
