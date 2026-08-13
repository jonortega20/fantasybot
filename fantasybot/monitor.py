"""fantasybot's supervision mini-UI ("mission control").

A minimal HTTP server (stdlib only) that serves a web panel and streams LIVE, over
SSE, the events the agent leaves in `.state/events.jsonl`. To supervise a run: open
it, trigger the run and watch in real time what the agent reads, decides and
executes (lineup, bids, sniping...).

Binds to 127.0.0.1 by default (never expose it openly). On a VPS, open it over an
SSH tunnel:  ssh -L 9137:127.0.0.1:9137 root@your-vps

Endpoints:
  GET /           the panel (self-contained HTML)
  GET /stream     SSE: history first, then each new event live
  GET /insights   tokens/tool-calls for the day (best-effort via `hermes insights`)
  GET /health     ok
"""

import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from . import events

_RUNNING = False   # prevents launching two cycles at once from the button

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
DASHBOARD = os.path.join(WEB_DIR, "dashboard.html")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9137

# Agent cycle prompt for Hermes (shared by the button and `watch --hermes`).
# Keep it in sync with the cron job in deploy/install.sh.
HERMES_PROMPT = ("Review my LALIGA Fantasy with your fantasy-manager skill: run "
                 "fantasybot agent --json, set the best lineup, schedule the "
                 "profitable bids with bid-plan and a sensible cap, handle "
                 "sales/buyouts with judgment and be concise.")


def _insights():
    """Day's tokens and tool-calls via Hermes (text → regex). Degrades to unavailable."""
    if not shutil.which("hermes"):
        return {"available": False}
    try:
        # `hermes insights` may print non-ASCII (emoji, box-drawing) that the
        # console's default codepage (e.g. cp1252 on Windows) can't decode;
        # force UTF-8 and never let a stray byte blow up the reader thread.
        out = subprocess.run(["hermes", "insights", "--days", "1"],
                             capture_output=True, text=True, timeout=20,
                             encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return {"available": False}
    if not out:
        return {"available": False}

    def grab(label):
        m = re.search(label + r":\s*~?([\d,]+)", out)
        return int(m.group(1).replace(",", "")) if m else None

    tm = re.search(r"Active time:\s*~?(\S+)", out)
    return {"available": True,
            "sessions": grab("Sessions"),
            "tool_calls": grab("Tool calls"),
            "total_tokens": grab("Total tokens"),
            "output_tokens": grab("Output tokens"),
            "active_time": tm.group(1) if tm else None}


def trigger(mode):
    """Runs one agent cycle in a background thread, guarded by `_RUNNING` so a
    concurrent trigger (CLI --run/--hermes racing the UI's own button, or two
    `watch` processes pointed at the same team) can't fire a second real cycle
    on top of one already in flight. Returns False if one was already running.
    """
    global _RUNNING
    if _RUNNING:
        return False

    def go():
        global _RUNNING
        try:
            if mode == "hermes":
                subprocess.run(["hermes", "-z", HERMES_PROMPT,
                                "--skill", "fantasy-manager"])
            else:
                subprocess.run([sys.executable, "-m", "fantasybot", "agent", "--execute"])
        finally:
            _RUNNING = False

    _RUNNING = True
    threading.Thread(target=go, daemon=True).start()
    return True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # silent: don't clutter the run's console
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            return self._page()
        if self.path.startswith("/stream"):
            return self._stream()
        if self.path.startswith("/insights"):
            body = json.dumps(_insights()).encode("utf-8")
            return self._send(200, "application/json", body)
        if self.path.startswith("/health"):
            return self._send(200, "application/json", b'{"ok":true}')
        self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self):
        if self.path.startswith("/run"):
            return self._run()
        self._send(404, "text/plain; charset=utf-8", b"not found")

    def _run(self):
        """Launches the real agent cycle (the 'Launch agent' button)."""
        mode = getattr(self.server, "run_mode", "agent")
        if not trigger(mode):
            return self._send(409, "application/json", b'{"error":"already running"}')
        self._send(202, "application/json", b'{"ok":true}')

    def _page(self):
        try:
            with open(DASHBOARD, "rb") as f:
                body = f.read()
        except OSError:
            body = b"<h1>dashboard.html not found</h1>"
        self._send(200, "text/html; charset=utf-8", body)

    def _stream(self):
        """SSE: dumps the history and then follows the events file live."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def push(obj):
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
                             .encode("utf-8"))
            self.wfile.flush()

        try:
            for ev in events.load():          # history
                push(ev)
            # from here on, follow the file by byte position
            path = events.EVENTS_PATH
            pos = os.path.getsize(path) if os.path.exists(path) else 0
            last_ping = time.time()
            while True:
                size = os.path.getsize(path) if os.path.exists(path) else 0
                if size < pos:                # the file was trimmed/reset
                    pos = 0
                if size > pos:
                    with open(path, encoding="utf-8") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for line in chunk.splitlines():
                        line = line.strip()
                        if line:
                            try:
                                push(json.loads(line))
                            except ValueError:
                                pass
                    last_ping = time.time()
                elif time.time() - last_ping > 15:
                    self.wfile.write(b": ping\n\n")   # keep-alive
                    self.wfile.flush()
                    last_ping = time.time()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return   # the client closed the tab


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    run_mode = "agent"


def serve(host=DEFAULT_HOST, port=DEFAULT_PORT, background=False, run_mode="agent"):
    """Starts the server. Returns (server, url). With background=True, non-blocking.

    run_mode: what the 'Launch agent' button triggers — 'agent' (deterministic) or 'hermes'.
    """
    srv = _Server((host, port), Handler)
    srv.run_mode = run_mode
    url = f"http://{host}:{port}"
    if background:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, url
