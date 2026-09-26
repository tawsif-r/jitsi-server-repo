#!/bin/bash
# Jibri finalize script: converts the MP4 Jibri produces into the format chosen in .env.
# Jibri calls this with the recording directory as $1 once a recording stops.
#
#   RECORDING_FORMAT        mp4 | mkv | webm        (video output; ignored when audio-only)
#   RECORDING_AUDIO_ONLY    0 | 1
#   RECORDING_AUDIO_FORMAT  mp3 | opus | m4a | wav  (used when RECORDING_AUDIO_ONLY=1)
#   RECORDING_KEEP_ORIGINAL 0 | 1                   (keep Jibri's MP4 next to the converted file)
#
# Rooms whose name ends in "-audio" are recorded audio-only regardless of RECORDING_AUDIO_ONLY.

RECORDINGS_DIR="$1"
FORMAT="${RECORDING_FORMAT:-mp4}"
AUDIO_ONLY="${RECORDING_AUDIO_ONLY:-0}"
AUDIO_FORMAT="${RECORDING_AUDIO_FORMAT:-mp3}"
KEEP_ORIGINAL="${RECORDING_KEEP_ORIGINAL:-0}"
LOG=/storage/logs/finalize.log

log() { echo "$(date -Is) $*" >> "$LOG"; }

if [ -z "$RECORDINGS_DIR" ] || [ ! -d "$RECORDINGS_DIR" ]; then
    log "no such directory: $RECORDINGS_DIR"
    exit 1
fi

# Per-meeting override: a room named "<name>-audio" is always recorded audio-only.
ROOM=$(jq -r '.meeting_url // empty' "$RECORDINGS_DIR/metadata.json" 2>/dev/null)
ROOM="${ROOM##*/}"
ROOM="${ROOM%%\?*}"
case "${ROOM,,}" in
    *-audio) AUDIO_ONLY=1 ;;
esac

log "finalize start dir=$RECORDINGS_DIR room=$ROOM format=$FORMAT audio_only=$AUDIO_ONLY audio_format=$AUDIO_FORMAT keep=$KEEP_ORIGINAL"

if [ "$AUDIO_ONLY" = "1" ]; then
    case "$AUDIO_FORMAT" in
        mp3)  EXT=mp3;  CODEC=(-c:a libmp3lame -q:a 2) ;;
        opus) EXT=opus; CODEC=(-c:a libopus -b:a 64k) ;;
        m4a)  EXT=m4a;  CODEC=(-c:a aac -b:a 128k) ;;
        wav)  EXT=wav;  CODEC=(-c:a pcm_s16le) ;;
        *)    log "unknown RECORDING_AUDIO_FORMAT=$AUDIO_FORMAT"; exit 1 ;;
    esac
    ARGS=(-vn "${CODEC[@]}")
else
    case "$FORMAT" in
        mp4)  log "mp4 requested, nothing to convert"; exit 0 ;;
        mkv)  EXT=mkv;  ARGS=(-c copy) ;;
        webm) EXT=webm; ARGS=(-c:v libvpx-vp9 -b:v 0 -crf 32 -deadline good -cpu-used 4 -row-mt 1 -c:a libopus -b:a 96k) ;;
        *)    log "unknown RECORDING_FORMAT=$FORMAT"; exit 1 ;;
    esac
fi

rc=0
shopt -s nullglob
for IN in "$RECORDINGS_DIR"/*.mp4; do
    OUT="${IN%.mp4}.$EXT"
    log "converting $IN -> $OUT"
    if nice -n 10 ffmpeg -hide_banner -loglevel error -y -i "$IN" "${ARGS[@]}" "$OUT" >> "$LOG" 2>&1; then
        log "done $OUT"
        [ "$KEEP_ORIGINAL" = "1" ] || rm -f "$IN"
    else
        log "ffmpeg failed for $IN, original kept"
        rm -f "$OUT"
        rc=1
    fi
done

exit $rc
