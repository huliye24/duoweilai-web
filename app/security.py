"""Security helpers: POST rate limiting, response headers, input caps."""

import threading
import time
from collections import deque

from flask import jsonify, render_template, request

# Input caps (chars). Over the cap -> 400.
MAX_TITLE = 500  # future title
MAX_CONTRIB_TITLE = 200  # contribution title
MAX_BODY = 10000  # future/contribution body
MAX_COMMENT = 5000  # comment body

RATE_LIMIT = 60  # POST requests ...
RATE_WINDOW = 60  # ... per 60 seconds per IP

CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'"
)


class RateLimiter:
    """In-memory sliding window. Per-worker under gunicorn (acceptable
    at this scale); exact under the single-process dev server."""

    def __init__(self, limit=RATE_LIMIT, window=RATE_WINDOW):
        self.limit = limit
        self.window = window
        self.lock = threading.Lock()
        self.hits = {}
        self._check_count = 0

    def allow(self, key):
        now = time.monotonic()
        with self.lock:
            q = self.hits.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            self._check_count += 1
            if self._check_count % 1000 == 0:  # keep memory bounded
                for k in list(self.hits):
                    qq = self.hits[k]
                    while qq and now - qq[0] > self.window:
                        qq.popleft()
                    if not qq:
                        del self.hits[k]
            return True


limiter = RateLimiter()


def rate_limit_check():
    """before_request hook: reject POST floods with 429."""
    if request.method != "POST":
        return None
    if not limiter.allow(request.remote_addr or "?"):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Too many requests — please slow down."}), 429
        return render_template(
            "error.html", title="429", message="Too many requests — please slow down."
        ), 429
    return None


def add_security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Content-Security-Policy", CSP)
    return resp
