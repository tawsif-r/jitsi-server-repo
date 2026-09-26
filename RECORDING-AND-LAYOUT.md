# Recording format, speaker layout, moderator "camera on"

All three are runtime overrides — no image rebuild, no changes to upstream files.

| Feature | Files |
|---|---|
| Speaker layout | `branding/custom-config.js` |
| Moderator turns camera on | `branding/custom-config.js` |
| Recording format / audio-only | `recording/finalize.sh`, `recording.yml`, `.env` |

`branding/custom-config.js` is appended to `config.js` each time the web container starts
(`web/rootfs/etc/s6-overlay/scripts/config`). After editing it: `docker restart jitsi-docker-jitsi-meet-738058b-web-1`,
then hard-reload the browser.

---

## 1. Speaker layout

```js
config.disableTileView = true;                       // no grid view, stage view only
config.filmstrip = { disableStageFilmstrip: true };  // one speaker on stage, not several
```

Whoever is speaking (dominant speaker) is shown large for everyone. Jibri loads the same
config, so recordings show the active speaker full-frame.

To allow grid view again, delete `config.disableTileView = true;`.
Moderators can also force their own layout on everyone with **Settings → Moderator → Follow me** (no config needed).

## 2. Moderator turns a participant's camera on/off

Stock Jitsi only lets moderators turn cameras **off**. This is a hack:

- **Turn camera on** and **Turn camera off** entries are added to each remote participant's `⋯` menu (`config.customParticipantMenuButtons`).
- On click, the moderator's browser sends a private endpoint message `{type: 'force-cam-on' | 'force-cam-off'}` to that participant.
- The participant's browser checks the sender is a moderator, then calls `APP.conference.muteVideo(false | true)`.
- Clicks by non-moderators and messages from non-moderators are ignored (logged to the browser console).

Limitations:
- The browser must already have camera permission. Otherwise the user sees the permission prompt.
- The participant can turn the camera off again.
- If AV moderation has video locked for that user, Jitsi refuses the unmute.
- It uses Jitsi internals (`APP.API.notifyParticipantMenuButtonClicked`, `APP.conference._room`,
  `conference.endpoint_message_received`). **Re-test after every image upgrade.**
- Participants should know moderators can do this.

## 3. Recording: choose the format, or audio only

Jibri always records MP4. After a recording stops, Jibri runs `recording/finalize.sh`, which converts it with ffmpeg.

`.env`:

```
ENABLE_RECORDING=1
RECORDING_FORMAT=mp4          # mp4 | mkv | webm
RECORDING_AUDIO_ONLY=0        # 1 = drop video
RECORDING_AUDIO_FORMAT=mp3    # mp3 | opus | m4a | wav  (when RECORDING_AUDIO_ONLY=1)
RECORDING_KEEP_ORIGINAL=0     # 1 = also keep Jibri's MP4
IGNORE_CERTIFICATE_ERRORS=true  # required with the self-signed cert
```

Without `IGNORE_CERTIFICATE_ERRORS=true`, Jibri's Chrome hits `ERR_CERT_AUTHORITY_INVALID` on
`PUBLIC_URL` and recording fails with `FailedToJoinCall` ("Timed out waiting for call page to load"
in `~/.jitsi-meet-cfg/storage/jibri/logs/log.0.txt`).

| Setting | Result | Cost |
|---|---|---|
| `mkv` | remux, same streams | instant |
| `webm` | VP9 + Opus re-encode | slow, CPU heavy (runs niced) |
| audio `mp3`/`opus`/`m4a`/`wav` | audio track only | fast |

These settings apply to every recording. The Jitsi "Start recording" dialog has no format or
audio-only option (adding one would mean changing Jitsi's source).

### Audio-only for one meeting: end the room name with `-audio`

A room whose name ends in `-audio` (e.g. `https://192.168.3.35:8443/standup-audio`) is always saved
audio-only in `RECORDING_AUDIO_FORMAT`, whatever `RECORDING_AUDIO_ONLY` is set to. Other rooms follow `.env`.
`finalize.sh` reads the room name from `metadata.json`, which Jibri writes next to each recording.

After editing `recording/finalize.sh`, recreate Jibri (`... up -d --force-recreate jibri`). It is a
single-file bind mount, so a restart alone can keep the old version. Don't do this while a recording is running.

### Start

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml -f whiteboard.yml -f reservation.yml \
  -f jibri.yml -f recording.yml up -d
```

`ENABLE_RECORDING` is read by web, prosody and jicofo, so those containers get recreated.
Changing a `RECORDING_*` value only needs Jibri recreated (same command). **Always include `-f recording.yml`**: if Jibri is recreated without it, recordings stay MP4 and `finalize.log` gets no new lines.

Output: `~/.jitsi-meet-cfg/storage/jibri/recordings/<session-id>/`
Log: `~/.jitsi-meet-cfg/storage/jibri/logs/finalize.log`

### Notes
- One Jibri container = one recording at a time.
- Jibri uses about 1–2 CPU cores and 2 GB shm while recording.
- If a conversion fails, the original MP4 is kept and the failure goes to `finalize.log`.
