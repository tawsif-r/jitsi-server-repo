#!/usr/bin/env python3
"""
Minimal Jitsi reservation backend + scheduling UI.  Stdlib only.

  UI  (humans):   GET  /                 schedule form + upcoming list
                  POST /schedule         create reservation
                  POST /r/<id>/delete    remove reservation
                  GET  /r/<id>.ics       calendar file for the meeting

  API (prosody mod_reservations, see
       https://jitsi.github.io/handbook/docs/devops-guide/reservation/):
                  POST   /conference     room about to be created -> allow/deny
                  GET    /conference/<id>
                  DELETE /conference/<id>

Env:
  PUBLIC_URL                      base URL of the Jitsi web UI (for links)
  RESERVATION_DB                  sqlite path            (default /data/reservations.db)
  RESERVATION_ALLOW_UNSCHEDULED   1 = ad-hoc rooms still allowed (default 1)
  RESERVATION_ADHOC_HOURS         lifetime of ad-hoc rooms (default 12)
  RESERVATION_EARLY_JOIN_MIN      minutes before start a room may open (default 10)
  RESERVATION_UI_PASSWORD         if set, UI needs basic auth (user: any)
"""
import base64
import html
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://localhost:8443").rstrip("/")
DB_PATH = os.environ.get("RESERVATION_DB", "/data/reservations.db")
ALLOW_UNSCHEDULED = os.environ.get("RESERVATION_ALLOW_UNSCHEDULED", "1") == "1"
ADHOC_SECONDS = int(float(os.environ.get("RESERVATION_ADHOC_HOURS", "12")) * 3600)
EARLY_JOIN = int(os.environ.get("RESERVATION_EARLY_JOIN_MIN", "10")) * 60
UI_PASSWORD = os.environ.get("RESERVATION_UI_PASSWORD", "")
PORT = int(os.environ.get("RESERVATION_PORT", "8600"))


# ---------------------------------------------------------------- storage
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS reservations (
                 id       INTEGER PRIMARY KEY AUTOINCREMENT,
                 room     TEXT NOT NULL,           -- as typed (URL slug)
                 room_lc  TEXT NOT NULL,           -- lowercased, what prosody sends
                 title    TEXT NOT NULL,
                 owner    TEXT NOT NULL,
                 start    INTEGER NOT NULL,        -- unix seconds, UTC
                 duration INTEGER NOT NULL,        -- seconds
                 password TEXT NOT NULL DEFAULT '',
                 created  INTEGER NOT NULL
               )"""
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_room ON reservations(room_lc, start)")


def find_active(room_lc, now):
    """Reservation whose join window contains `now`, else None."""
    with db() as con:
        return con.execute(
            """SELECT * FROM reservations
               WHERE room_lc = ? AND start - ? <= ? AND start + duration > ?
               ORDER BY start LIMIT 1""",
            (room_lc, EARLY_JOIN, now, now),
        ).fetchone()


def find_next(room_lc, now):
    with db() as con:
        return con.execute(
            "SELECT * FROM reservations WHERE room_lc = ? AND start > ? ORDER BY start LIMIT 1",
            (room_lc, now),
        ).fetchone()


# ---------------------------------------------------------------- helpers
def iso_utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def human_local(ts):
    """For messages shown to people: local time per TZ env, e.g. '2026-09-20 13:00 +06'."""
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def ics_ts(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def room_url(room):
    return f"{PUBLIC_URL}/{quote(room)}"


def slug(s):
    s = re.sub(r"[^A-Za-z0-9_-]+", "", s.strip())
    return s[:64]


def api_payload(row):
    return {
        "id": str(row["id"]),
        "name": row["room_lc"],
        "mail_owner": row["owner"],
        "start_time": iso_utc(row["start"]),
        "duration": int(row["duration"]),
        "password": row["password"] or "",
    }


def event_text(row):
    lines = [f"Join: {room_url(row['room'])}"]
    if row["password"]:
        lines.append(f"Meeting password: {row['password']}")
    return "\n".join(lines)


def make_ics(row):
    end = row["start"] + row["duration"]
    desc = event_text(row).replace("\n", "\\n")
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//DNS Meet//Reservation//EN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:meet-{row['id']}@{urlparse(PUBLIC_URL).hostname}",
            f"DTSTAMP:{ics_ts(row['created'])}",
            f"DTSTART:{ics_ts(row['start'])}",
            f"DTEND:{ics_ts(end)}",
            f"SUMMARY:{row['title']}",
            f"LOCATION:{room_url(row['room'])}",
            f"URL:{room_url(row['room'])}",
            f"DESCRIPTION:{desc}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def gcal_link(row):
    end = row["start"] + row["duration"]
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote(row['title'])}"
        f"&dates={ics_ts(row['start'])}/{ics_ts(end)}"
        f"&details={quote(event_text(row))}"
        f"&location={quote(room_url(row['room']))}"
    )


def outlook_link(row):
    end = row["start"] + row["duration"]
    return (
        "https://outlook.office.com/calendar/0/deeplink/compose?path=/calendar/action/compose&rru=addevent"
        f"&subject={quote(row['title'])}"
        f"&startdt={iso_utc(row['start'])}&enddt={iso_utc(end)}"
        f"&body={quote(event_text(row))}"
        f"&location={quote(room_url(row['room']))}"
    )


# ---------------------------------------------------------------- UI
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Schedule a meeting</title>
<style>
 body{font:15px system-ui,sans-serif;margin:0;padding:24px 16px;max-width:900px;margin:auto;color:#222}
 h1{font-size:22px} h2{font-size:17px;margin-top:32px}
 form.new{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;align-items:end}
 label{display:flex;flex-direction:column;font-size:13px;gap:4px}
 input{padding:7px;border:1px solid #bbb;border-radius:4px;font:inherit}
 button{padding:8px 14px;border:0;border-radius:4px;background:#1a56db;color:#fff;font:inherit;cursor:pointer}
 button.del{background:#c33;padding:4px 10px;font-size:12px}
 table{width:100%%;border-collapse:collapse;margin-top:8px} td,th{padding:8px 6px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top;font-size:14px}
 .ok{background:#e6f4ea;border:1px solid #9bd0a8;padding:12px;border-radius:6px;margin-bottom:20px}
 .ok a{margin-right:12px} code{background:#f2f2f2;padding:1px 4px;border-radius:3px}
 .muted{color:#777;font-size:12px}
</style></head><body>
<h1>Schedule a meeting</h1>
%(flash)s
<form class="new" method="post" action="/schedule" onsubmit="return fix(this)">
 <label>Title <input name="title" required placeholder="Weekly sync"></label>
 <label>Room name <input name="room" required pattern="[A-Za-z0-9_-]+" placeholder="weekly-sync"></label>
 <label>Start <input type="datetime-local" name="start_local" required></label>
 <label>Duration (min) <input type="number" name="minutes" value="60" min="5" max="1440" required></label>
 <label>Password <input name="password" placeholder="blank = none"></label>
 <label>Organiser email <input name="owner" type="email" placeholder="you@example.com"></label>
 <input type="hidden" name="start" value="">
 <button>Schedule</button>
</form>
<p class="muted">Times are entered in <span id="tz"></span>. Room opens %(early)d min early and is closed automatically when the slot ends.
%(adhoc)s</p>

<h2>Upcoming</h2>
<table><tr><th>When</th><th>Title</th><th>Room</th><th>Password</th><th>Calendar</th><th></th></tr>
%(rows)s
</table>
<script>
 document.getElementById('tz').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;
 function fix(f){ const d=new Date(f.start_local.value); if(isNaN(d)) return false; f.start.value=Math.floor(d.getTime()/1000); return true; }
 document.querySelectorAll('time[data-ts]').forEach(t=>{ t.textContent=new Date(t.dataset.ts*1000).toLocaleString(); });
</script>
</body></html>"""


def render_rows(rows):
    out = []
    for r in rows:
        mins = r["duration"] // 60
        out.append(
            "<tr>"
            f"<td><time data-ts='{r['start']}'>{iso_utc(r['start'])}</time><br><span class='muted'>{mins} min</span></td>"
            f"<td>{html.escape(r['title'])}<br><span class='muted'>{html.escape(r['owner'])}</span></td>"
            f"<td><a href='{html.escape(room_url(r['room']))}'>{html.escape(r['room'])}</a></td>"
            f"<td><code>{html.escape(r['password']) or '—'}</code></td>"
            f"<td><a href='/r/{r['id']}.ics'>.ics</a> · <a href='{html.escape(gcal_link(r))}' target='_blank'>Google</a> · "
            f"<a href='{html.escape(outlook_link(r))}' target='_blank'>Outlook</a></td>"
            f"<td><form method='post' action='/r/{r['id']}/delete'><button class='del'>delete</button></form></td>"
            "</tr>"
        )
    return "\n".join(out) or "<tr><td colspan=6 class='muted'>nothing scheduled</td></tr>"


def render_page(flash_row=None):
    now = int(time.time())
    with db() as con:
        rows = con.execute(
            "SELECT * FROM reservations WHERE start + duration > ? ORDER BY start", (now,)
        ).fetchall()
    flash = ""
    if flash_row is not None:
        flash = (
            "<div class='ok'><b>Scheduled.</b> Link: "
            f"<a href='{html.escape(room_url(flash_row['room']))}'>{html.escape(room_url(flash_row['room']))}</a>"
            + (f" &nbsp; password <code>{html.escape(flash_row['password'])}</code>" if flash_row["password"] else "")
            + f"<br>Add to calendar: <a href='/r/{flash_row['id']}.ics'>download .ics</a>"
            f"<a href='{html.escape(gcal_link(flash_row))}' target='_blank'>Google Calendar</a>"
            f"<a href='{html.escape(outlook_link(flash_row))}' target='_blank'>Outlook</a></div>"
        )
    adhoc = (
        f"Unscheduled rooms still work (auto-close after {ADHOC_SECONDS // 3600} h)."
        if ALLOW_UNSCHEDULED
        else "Only scheduled rooms can be opened."
    )
    return PAGE % {"flash": flash, "rows": render_rows(rows), "early": EARLY_JOIN // 60, "adhoc": adhoc}


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "jitsi-reservation/1"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)

    # -- plumbing
    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, obj):
        self.send(code, json.dumps(obj), "application/json")

    def redirect(self, to):
        self.send_response(303)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def form(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode()
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def ui_authorized(self):
        if not UI_PASSWORD:
            return True
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Basic "):
            try:
                _, _, pw = base64.b64decode(hdr[6:]).decode().partition(":")
                if secrets.compare_digest(pw, UI_PASSWORD):
                    return True
            except Exception:
                pass
        self.send(401, "auth required", extra={"WWW-Authenticate": 'Basic realm="scheduler"'})
        return False

    # -- routes
    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/health":
            return self.send_json(200, {"ok": True})
        if p.startswith("/conference/"):
            return self.api_get(p.rsplit("/", 1)[1])
        if not self.ui_authorized():
            return
        if p == "/":
            q = parse_qs(urlparse(self.path).query)
            flash_row = None
            if "created" in q:
                with db() as con:
                    flash_row = con.execute(
                        "SELECT * FROM reservations WHERE id = ?", (q["created"][0],)
                    ).fetchone()
            return self.send(200, render_page(flash_row))
        m = re.fullmatch(r"/r/(\d+)\.ics", p)
        if m:
            with db() as con:
                row = con.execute("SELECT * FROM reservations WHERE id = ?", (m.group(1),)).fetchone()
            if not row:
                return self.send(404, "not found", "text/plain")
            return self.send(
                200, make_ics(row), "text/calendar; charset=utf-8",
                {"Content-Disposition": f'attachment; filename="{slug(row["room"]) or "meeting"}.ics"'},
            )
        self.send(404, "not found", "text/plain")

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/conference":
            return self.api_create()
        if not self.ui_authorized():
            return
        if p == "/schedule":
            return self.ui_schedule()
        m = re.fullmatch(r"/r/(\d+)/delete", p)
        if m:
            with db() as con:
                con.execute("DELETE FROM reservations WHERE id = ?", (m.group(1),))
            return self.redirect("/")
        self.send(404, "not found", "text/plain")

    def do_DELETE(self):
        p = urlparse(self.path).path
        if p.startswith("/conference/"):
            # Prosody tells us the room closed. Nothing to clean up: the row stays
            # as history and can't match again once its slot is over.
            print(f"room closed: reservation {p.rsplit('/', 1)[1]}", flush=True)
            return self.send_json(200, {"ok": True})
        self.send(404, "not found", "text/plain")

    # -- UI handlers
    def ui_schedule(self):
        f = self.form()
        room = slug(f.get("room", ""))
        title = f.get("title", "").strip() or room
        try:
            start = int(f.get("start") or 0)
            minutes = int(f.get("minutes") or 60)
        except ValueError:
            return self.send(400, "bad input", "text/plain")
        if not room or start <= 0 or not (5 <= minutes <= 1440):
            return self.send(400, "bad input", "text/plain")
        owner = f.get("owner", "").strip() or "scheduler@" + (urlparse(PUBLIC_URL).hostname or "meet")
        password = f.get("password", "").strip()
        with db() as con:
            cur = con.execute(
                "INSERT INTO reservations(room, room_lc, title, owner, start, duration, password, created)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (room, room.lower(), title, owner, start, minutes * 60, password, int(time.time())),
            )
            rid = cur.lastrowid
        print(f"scheduled #{rid} {room} at {iso_utc(start)} for {minutes} min", flush=True)
        self.redirect(f"/?created={rid}")

    # -- Prosody reservation API
    def api_create(self):
        f = self.form()
        name = (f.get("name") or "").lower()
        now = int(time.time())
        print(f"prosody asks for room '{name}' (creator {f.get('mail_owner')})", flush=True)
        if not name:
            return self.send_json(400, {"message": "missing name"})
        row = find_active(name, now)
        if row:
            print(f"  -> allowed, reservation #{row['id']} until {iso_utc(row['start'] + row['duration'])}", flush=True)
            return self.send_json(200, api_payload(row))
        nxt = find_next(name, now)
        if nxt:
            msg = f"This meeting is scheduled for {human_local(nxt['start'])}. Room opens {EARLY_JOIN // 60} min before."
            print(f"  -> denied, too early ({msg})", flush=True)
            return self.send_json(403, {"message": msg})
        if ALLOW_UNSCHEDULED:
            print(f"  -> allowed ad hoc for {ADHOC_SECONDS // 3600} h", flush=True)
            return self.send_json(
                200,
                {
                    "id": f"adhoc-{name}-{now}",
                    "name": name,
                    "mail_owner": f.get("mail_owner") or "adhoc",
                    "start_time": iso_utc(now),
                    "duration": ADHOC_SECONDS,
                },
            )
        print("  -> denied, not scheduled", flush=True)
        return self.send_json(403, {"message": "This room is not scheduled. Ask the organiser to schedule it."})

    def api_get(self, rid):
        if rid.startswith("adhoc-"):
            return self.send_json(404, {"message": "ad-hoc rooms are not stored"})
        with db() as con:
            row = con.execute("SELECT * FROM reservations WHERE id = ?", (rid,)).fetchone()
        if not row:
            return self.send_json(404, {"message": "not found"})
        return self.send_json(200, api_payload(row))


if __name__ == "__main__":
    init_db()
    print(f"reservation service on :{PORT}, PUBLIC_URL={PUBLIC_URL}, allow_unscheduled={ALLOW_UNSCHEDULED}", flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
