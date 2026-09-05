"""
utils/keep_alive.py
--------------------
Render's Free tier only offers "Web Service" (requires a bound port) or
"Background Worker" (paid). Pyrogram itself never opens a port, so Render's
port scanner times out and kills the deploy.

This starts a tiny stdlib HTTP server on $PORT in its own background
thread. It runs completely outside Pyrogram's asyncio event loop -- plain
blocking sockets in a separate OS thread -- so it cannot interfere with,
share state with, or break Pyrogram's own async runtime. No new
dependency: http.server and threading are both in the standard library.
"""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from utils.logger import LOGGER


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running.")

    def log_message(self, format, *args):
        # Suppress per-request access logging -- Render's port scanner and
        # any external uptime pinger would otherwise spam bot.log/stdout.
        pass


def start_keep_alive_server() -> ThreadingHTTPServer:
    """Bind $PORT (Render sets this) and serve forever in a daemon thread."""
    port = int(os.environ.get("PORT", 8080))
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    LOGGER.info(f"Keep-alive HTTP server listening on 0.0.0.0:{port}")
    return server
