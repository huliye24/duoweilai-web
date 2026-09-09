"""Shared helpers for the Duoweilai test suite.

Each test file spins up its own server on its own port with its own scratch
database (.test-db-<port>.db, deleted afterwards), so the files can run in
any order. Run them with the project venv:

    .venv/Scripts/python tests/e2e_test.py

Client mirrors what a browser does:
  1. GET any page first -> the server mints the CSRF cookie (duoweilai_csrf)
  2. every POST sends that token back via the X-CSRF-Token header
     (the hidden `csrf` form field works too — the server accepts either).
"""

import http.client
import json
import os
import subprocess
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESET_LOG = os.path.join(ROOT, "reset_link.log")


class Server:
    """One `python server.py` process bound to 127.0.0.1:<port>."""

    def __init__(self, port):
        self.port = port
        self.db = os.path.join(ROOT, f".test-db-{port}.db")
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(self.db + suffix)
            except OSError:
                pass
        env = dict(
            os.environ, DUOWEILAI_PORT=str(port), DUOWEILAI_BIND="127.0.0.1", DUOWEILAI_DB=self.db
        )
        self.proc = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            env=env,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                r = Client(self).get("/api/health")
                if r.status == 200 and r.json().get("ok"):
                    return
            except OSError:
                pass
            time.sleep(0.15)
        self.stop()
        raise RuntimeError(f"server on port {port} did not come up")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(self.db + suffix)
            except OSError:
                pass


class Response:
    def __init__(self, status, text, headers):
        self.status = status
        self.text = text
        self.headers = headers  # list of (name, value), possibly repeated

    def json(self):
        return json.loads(self.text)

    def header(self, name):
        name = name.lower()
        vals = [v for k, v in self.headers if k.lower() == name]
        return vals[0] if vals else ""

    @property
    def location(self):
        return self.header("Location")


class Client:
    """Minimal browser: cookie jar + CSRF handshake + form/JSON POSTs."""

    def __init__(self, server):
        self.server = server
        self.cookies = {}

    # -- plumbing ----------------------------------------------------
    def _absorb(self, headers):
        for k, v in headers:
            if k.lower() != "set-cookie":
                continue
            first = v.split(";", 1)[0]
            name, _, val = first.partition("=")
            name, val = name.strip(), val.strip()
            if val:
                self.cookies[name] = val
            else:  # delete_cookie() sends an empty value
                self.cookies.pop(name, None)

    def request(self, method, path, data=None, json_body=None, send_csrf=True):
        # http.client rejects control characters (e.g. spaces) in the path —
        # percent-encode them, keeping the query structure chars intact.
        path = urllib.parse.quote(path, safe="/?&=%+")
        headers = {}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif json_body is not None:
            body = json.dumps(json_body)
            headers["Content-Type"] = "application/json"
        if method == "POST" and send_csrf:
            headers["X-CSRF-Token"] = self.csrf
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        conn.request(method, path, body=body, headers=headers)
        r = conn.getresponse()
        text = r.read().decode("utf-8", errors="replace")
        headers_out = r.getheaders()
        conn.close()
        self._absorb(headers_out)
        return Response(r.status, text, headers_out)

    # -- conveniences ------------------------------------------------
    @property
    def csrf(self):
        return self.cookies.get("duoweilai_csrf", "")

    @property
    def session(self):
        return self.cookies.get("duoweilai_session", "")

    def prime(self, path="/"):
        """First GET — picks up the CSRF cookie, like a browser loading a page."""
        return self.get(path)

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, **fields):
        """Form POST (what the site's own <form>s send)."""
        return self.request("POST", path, data=fields)

    def post_json(self, path, **fields):
        """JSON POST (what app.js fetch() calls send)."""
        return self.request("POST", path, json_body=fields)


# -- check / report -------------------------------------------------
_passed = _failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    ok = bool(cond)
    line = f"  [{'PASS' if ok else 'FAIL'}] {name}"
    if not ok and detail:
        line += f"  -- {detail}"
    print(line)
    if ok:
        _passed += 1
    else:
        _failed += 1
    return ok


def finish():
    print(f"\n=== Results: {_passed} passed, {_failed} failed ===")
    return 0 if _failed == 0 else 1
