"""
MUSIC STREAM SERVER — Houridis Sounds
Render-ready version (μόνο Python standard library)

- Streaming only: τα WAV δεν κατεβαίνουν (controlsList nodownload + κανένα download endpoint)
- Μετρητής αναπαραγωγών ανά track (MAX_PLAYS)
- Enable/disable ανά track (στο play_state.json)
- Υποστήριξη HTTP Range ώστε να παίζει σωστά παντού (Safari/Chrome/Firefox)

Τοπικά:   python app.py   ->  http://localhost:8000
Render:    Start Command = python app.py  (το PORT το δίνει το Render αυτόματα)
"""

import os
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

# ---------------------------------------------------------------------------
# Ρυθμίσεις
# ---------------------------------------------------------------------------
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
TRACKS_DIR = os.path.join(BASE_DIR, "tracks")
STATE_FILE = os.path.join(BASE_DIR, "play_state.json")

PORT      = int(os.environ.get("PORT", "8000"))   # Render δίνει το δικό του PORT
MAX_PLAYS = int(os.environ.get("MAX_PLAYS", "0"))  # 0 = απεριόριστες αναπαραγωγές

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# State (μετρητές + enabled ανά track)
# ---------------------------------------------------------------------------
def list_track_files():
    if not os.path.isdir(TRACKS_DIR):
        return []
    files = [f for f in os.listdir(TRACKS_DIR)
             if f.lower().endswith(".wav") and not f.startswith(".")]
    return sorted(files)


def load_state():
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                state = json.load(fh)
        except Exception:
            state = {}
    # Συγχρονισμός με τα πραγματικά αρχεία
    for f in list_track_files():
        if f not in state:
            state[f] = {"plays": 0, "enabled": True}
        else:
            state[f].setdefault("plays", 0)
            state[f].setdefault("enabled", True)
    return state


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        print("State save error:", e)


def remaining_for(rec):
    if MAX_PLAYS <= 0:
        return None  # απεριόριστο
    return max(0, MAX_PLAYS - rec.get("plays", 0))


# ---------------------------------------------------------------------------
# HTML player (branded)
# ---------------------------------------------------------------------------
PLAYER_HTML = """<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HOURIDIS SOUNDS — Streaming Player</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 30px 16px;
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    background: #0f0f12; color: #e8e8ea;
    display: flex; flex-direction: column; align-items: center;
  }
  h1 { margin: 0 0 4px; font-size: 1.5em; letter-spacing: 2px; }
  .subtitle { color: #8a8a90; font-size: 0.8em; margin: 0 0 26px; }
  .player-wrap { width: 100%; max-width: 560px; }
  .track-list { list-style: none; margin: 0 0 22px; padding: 0;
    border: 1px solid #26262c; border-radius: 10px; overflow: hidden; }
  .track-item { display: flex; align-items: center; gap: 12px;
    padding: 14px 16px; cursor: pointer; border-bottom: 1px solid #1c1c22;
    transition: background .15s; }
  .track-item:last-child { border-bottom: none; }
  .track-item:hover { background: #18181e; }
  .track-item.active { background: #1f1f29; }
  .track-item.locked { opacity: .45; cursor: not-allowed; }
  .play-icon { width: 18px; text-align: center; color: #c9a24b; }
  .track-name { flex: 1; font-size: 0.95em; }
  .track-meta { font-size: 0.7em; color: #6f6f76; }
  .now-playing { background: #16161b; border: 1px solid #26262c;
    border-radius: 10px; padding: 16px; }
  .np-label { font-size: 0.65em; letter-spacing: 2px; color: #6f6f76; }
  .np-title { font-size: 1.05em; margin: 4px 0 12px; }
  audio { width: 100%; }
  .notice { text-align: center; font-size: 0.72em; color: #6f6f76;
    margin-top: 20px; line-height: 1.6; max-width: 560px; }
  .loading, .error { padding: 28px; text-align: center; }
  .error { color: #c84b4b; }
</style>
</head>
<body>
  <h1>HOURIDIS SOUNDS</h1>
  <p class="subtitle">houridisnikos@yahoo.gr&nbsp; | &nbsp;Streaming Player</p>

  <div class="player-wrap">
    <ul class="track-list" id="trackList">
      <li class="loading">Φόρτωση tracks…</li>
    </ul>
    <div class="now-playing">
      <div class="np-label">NOW PLAYING</div>
      <div class="np-title" id="npTitle">—</div>
      <audio id="audioPlayer" controls controlsList="nodownload nofullscreen noplaybackrate"></audio>
    </div>
  </div>

  <p class="notice">
    🔒 Streaming only — τα αρχεία δεν αποθηκεύονται.<br>
    © Houridis Sounds — All Rights Reserved
  </p>

<script>
const audio   = document.getElementById('audioPlayer');
const npTitle = document.getElementById('npTitle');
const list    = document.getElementById('trackList');
let tracks    = [];

function render() {
  if (!tracks.length) {
    list.innerHTML = '<li class="error">Κανένα διαθέσιμο track.</li>';
    return;
  }
  list.innerHTML = '';
  tracks.forEach((t, i) => {
    const li = document.createElement('li');
    const locked = !t.enabled || (t.remaining !== null && t.remaining <= 0);
    li.className = 'track-item' + (locked ? ' locked' : '');
    let meta = 'WAV';
    if (!t.enabled) meta = 'ΑΝΕΝΕΡΓΟ';
    else if (t.remaining !== null) meta = t.remaining + ' αναπαρ.';
    li.innerHTML =
      '<span class="play-icon">▶</span>' +
      '<span class="track-name">' + t.name + '</span>' +
      '<span class="track-meta">' + meta + '</span>';
    if (!locked) li.onclick = () => playTrack(i);
    list.appendChild(li);
  });
}

function loadPlaylist() {
  fetch('/playlist')
    .then(r => r.json())
    .then(d => { tracks = d; render(); })
    .catch(() => { list.innerHTML = '<li class="error">Αδύνατη σύνδεση με server.</li>'; });
}

function playTrack(idx) {
  const t = tracks[idx];
  fetch('/play?track=' + encodeURIComponent(t.file))
    .then(r => r.json())
    .then(res => {
      if (!res.ok) { alert(res.message || 'Δεν επιτρέπεται.'); loadPlaylist(); return; }
      document.querySelectorAll('.track-item').forEach((el, i) =>
        el.classList.toggle('active', i === idx));
      npTitle.textContent = t.name;
      audio.src = '/stream?track=' + encodeURIComponent(t.file) + '&t=' + Date.now();
      audio.play();
      // ανανέωση μετρητών μετά την έναρξη
      setTimeout(loadPlaylist, 600);
    })
    .catch(() => alert('Σφάλμα σύνδεσης.'));
}

loadPlaylist();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "HouridisStream/1.0"

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _safe_track_path(self, track):
        """Επιστρέφει το ασφαλές path ή None (anti path-traversal)."""
        name = os.path.basename(unquote(track or ""))
        if not name.lower().endswith(".wav"):
            return None, None
        path = os.path.join(TRACKS_DIR, name)
        if not os.path.isfile(path):
            return None, None
        return name, path

    def do_GET(self):
        parsed = urlparse(self.path)
        route  = parsed.path
        qs     = parse_qs(parsed.query)

        if route == "/" or route == "/index.html":
            body = PLAYER_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route == "/playlist":
            with _lock:
                state = load_state()
                save_state(state)
                out = []
                for f in list_track_files():
                    rec = state[f]
                    out.append({
                        "name": os.path.splitext(f)[0],
                        "file": f,
                        "enabled": rec.get("enabled", True),
                        "plays": rec.get("plays", 0),
                        "remaining": remaining_for(rec),
                    })
            self._send_json(out)
            return

        if route == "/play":
            track = (qs.get("track") or [""])[0]
            name, path = self._safe_track_path(track)
            if not name:
                self._send_json({"ok": False, "message": "Δεν βρέθηκε."}, 404)
                return
            with _lock:
                state = load_state()
                rec = state.setdefault(name, {"plays": 0, "enabled": True})
                if not rec.get("enabled", True):
                    self._send_json({"ok": False, "message": "Το track είναι ανενεργό."})
                    return
                rem = remaining_for(rec)
                if rem is not None and rem <= 0:
                    self._send_json({"ok": False, "message": "Έφτασες το όριο αναπαραγωγών."})
                    return
                rec["plays"] = rec.get("plays", 0) + 1
                save_state(state)
                self._send_json({"ok": True, "plays": rec["plays"],
                                 "remaining": remaining_for(rec)})
            return

        if route == "/stream":
            track = (qs.get("track") or [""])[0]
            name, path = self._safe_track_path(track)
            if not name:
                self.send_error(404, "Not found")
                return
            with _lock:
                state = load_state()
                rec = state.get(name, {"plays": 0, "enabled": True})
                if not rec.get("enabled", True):
                    self.send_error(403, "Disabled")
                    return
            self._serve_audio(path)
            return

        self.send_error(404, "Not found")

    # --- streaming με υποστήριξη Range ---
    def _serve_audio(self, path):
        file_size = os.path.getsize(path)
        range_hdr = self.headers.get("Range")
        start, end = 0, file_size - 1

        if range_hdr and range_hdr.startswith("bytes="):
            try:
                rng = range_hdr.split("=", 1)[1].split(",")[0]
                s, e = rng.split("-")
                if s.strip():
                    start = int(s)
                if e.strip():
                    end = int(e)
            except Exception:
                start, end = 0, file_size - 1
            start = max(0, start)
            end = min(end, file_size - 1)

        length = end - start + 1
        partial = bool(range_hdr)

        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", "inline")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                remaining = length
                chunk = 64 * 1024
                while remaining > 0:
                    data = fh.read(min(chunk, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # ο browser έκλεισε / seek — αναμενόμενο

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


def main():
    os.makedirs(TRACKS_DIR, exist_ok=True)
    print(f"Tracks dir : {TRACKS_DIR}")
    print(f"Max plays  : {'απεριόριστες' if MAX_PLAYS <= 0 else MAX_PLAYS}")
    print(f"Listening  : 0.0.0.0:{PORT}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nΤερματισμός.")
        server.server_close()


if __name__ == "__main__":
    main()
