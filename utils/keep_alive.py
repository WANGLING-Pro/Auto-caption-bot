"""
utils/keep_alive.py
--------------------
Render "Web Service" needs a bound port; Pyrogram never opens one. This starts
a tiny stdlib HTTP server on $PORT in a daemon thread (completely outside
Pyrogram's asyncio loop).

Review fixes
------------
* Answers HEAD as well as GET (uptime monitors such as UptimeRobot use HEAD;
  BaseHTTPRequestHandler answered those with 501) and sends Content-Length.
* Optional self-ping: Render's FREE web services are spun down after ~15
  minutes without inbound HTTP traffic, and a sleeping service cannot answer
  Telegram messages (this alone can look like "/start is not responding").
  If RENDER_EXTERNAL_URL is set (Render sets it automatically) a background
  thread requests it every KEEP_ALIVE_PING_SECONDS (default 600; 0 disables).
  An external pinger (cron-job.org / UptimeRobot every 5-10 min on your
  .onrender.com URL) is the more reliable option -- use either.
"""

import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from utils.logger import LOGGER

_BODY = b"Bot is running."


class _HealthHandler(BaseHTTPRequestHandler):
    def _respond(self, with_body: bool):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(_BODY)))
        self.end_headers()
        if with_body:
            self.wfile.write(_BODY)

    def do_GET(self):
        self._respond(True)

    def do_HEAD(self):
        self._respond(False)

    def log_message(self, format, *args):
        pass  # no per-request access logging


def _self_ping_loop(url: str, interval: int):
    LOGGER.info(f"Self-ping enabled: GET {url} every {interval}s")
    while True:
        time.sleep(interval)
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                LOGGER.debug(f"Self-ping OK ({resp.status})")
        except Exception as e:
            LOGGER.warning(f"Self-ping failed: {e}")


def start_keep_alive_server() -> ThreadingHTTPServer:
    """Bind $PORT (Render sets this) and serve forever in a daemon thread."""
    port = int(os.environ.get("PORT", 8080))
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True, name="keep-alive-http")
    thread.start()
    LOGGER.info(f"Keep-alive HTTP server listening on 0.0.0.0:{port}")

    url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    try:
        interval = int(os.environ.get("KEEP_ALIVE_PING_SECONDS", "600"))
    except ValueError:
        interval = 600
    if url and interval > 0:
        threading.Thread(
            target=_self_ping_loop, args=(url, interval), daemon=True, name="keep-alive-ping"
        ).start()
    else:
        LOGGER.info("Self-ping disabled (no RENDER_EXTERNAL_URL or KEEP_ALIVE_PING_SECONDS=0)")

    return server
