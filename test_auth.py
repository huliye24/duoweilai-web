#!/usr/bin/env python3
"""Local end-to-end test of the new auth flow. Uses a separate test DB."""
import os, urllib.request, urllib.parse, http.cookiejar, sys, subprocess, time

DB = os.path.join(os.path.dirname(__file__), "test_auth.db")
PORT = "8090"

# Fresh DB
if os.path.exists(DB): os.remove(DB)

server = subprocess.Popen(
    [sys.executable, "server.py"],
    cwd=os.path.dirname(__file__),
    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    env={**os.environ, "DUOWEILAI_PORT": PORT, "DUOWEILAI_DB": DB},
)
time.sleep(1.5)

try:
    BASE = f"http://127.0.0.1:{PORT}"

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    def get(path):
        r = opener.open(BASE + path)
        return r.status, r.read().decode("utf-8", errors="replace")

    def post(path, **kw):
        data = urllib.parse.urlencode(kw).encode()
        req = urllib.request.Request(BASE + path, data=data, method="POST")
        try:
            r = opener.open(req)
            return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def assert_(cond, msg):
        if not cond:
            print(f"  FAIL: {msg}")
            sys.exit(1)

    print("\n=== 1. Homepage (anonymous) ===")
    code, html = get("/")
    assert_("Plant your first seed" in html, "Expected logged-out CTA")
    assert_("Sign up" in html, "Expected Sign up link")
    print("  OK")

    print("\n=== 2. Register page ===")
    code, html = get("/register")
    assert_("Join Duoweilai" in html, "Expected register page")
    assert_('name="username"' in html, "Expected username field")
    print("  OK")

    print("\n=== 3. Register a new account ===")
    code, html = post("/api/register",
                      username="alice", email="alice@example.com", password="secret123")
    assert_("alice" in html or "What future" in html,
            f"Register didn't redirect cleanly, got: {html[:150]}")
    code, html = get("/")
    assert_("alice" in html, "Expected alice's name in header after register")
    print("  OK — auto-signed in")

    print("\n=== 4. Publish a future ===")
    code, html = post("/api/future",
                      title="Cities on water by 2080",
                      category="Cities", body="Floating districts everywhere")
    assert_("Cities on water" in html or "Floating" in html,
            f"Publish didn't render seed page, got: {html[:150]}")
    print("  OK")

    print("\n=== 5. Logout ===")
    post("/api/logout")
    code, html = get("/")
    assert_("Plant your first seed" in html, "Expected logged-out CTA again")
    assert_("Sign in" in html and "Sign up" in html, "Expected sign-in/up in nav")
    print("  OK")

    print("\n=== 6. Try to publish while logged out ===")
    code, html = post("/api/future",
                      title="Should fail", category="Life", body="No")
    assert_("Sign in to continue" in html, "Expected login required page")
    print("  OK — blocked with friendly message")

    print("\n=== 7. Login with wrong password ===")
    code, html = post("/api/login", username="alice", password="wrong")
    assert_("incorrect" in html.lower(), "Expected wrong-creds error")
    print("  OK")

    print("\n=== 8. Login with correct password ===")
    code, html = post("/api/login", username="alice", password="secret123")
    code, html = get("/")
    assert_("alice" in html, "Expected alice in header")
    print("  OK")

    print("\n=== 9. Forgot password → inbox page ===")
    code, html = get("/forgot")
    assert_("Forgot your password" in html, "Expected forgot page")
    code, html = post("/api/forgot", email="alice@example.com")
    assert_("Check your inbox" in html, "Expected inbox confirmation")
    print("  OK")

    print("\n=== 10. Reset link in log? ===")
    log = "reset_link.log"
    assert_(os.path.exists(log), f"Expected {log} to be created")
    content = open(log, encoding="utf-8").read()
    assert_("alice@example.com" in content, "Expected alice's email in log")
    assert_("/reset/" in content, "Expected reset link in log")
    reset_url = [line.split("Link: ")[1].strip() for line in content.splitlines() if "Link: " in line][0]
    print(f"  OK — reset URL: {reset_url[:50]}...")

    print("\n=== 11. Open reset link & set new password ===")
    # Extract token
    token = reset_url.split("/reset/")[1]
    code, html = get(f"/reset/{token}")
    assert_("Set a new password" in html, "Expected reset form")
    code, html = post(f"/api/reset/{token}", password="newpass99")
    assert_("Password updated" in html, "Expected success page")
    print("  OK")

    print("\n=== 12. Login with the new password ===")
    post("/api/logout")
    code, html = post("/api/login", username="alice", password="newpass99")
    code, html = get("/")
    assert_("alice" in html, "Expected alice signed in with new password")
    print("  OK")

    print("\n=== 13. Duplicate username ===")
    code, html = post("/api/register",
                      username="alice", email="diff@example.com", password="another")
    assert_("already taken" in html.lower(), "Expected duplicate-username error")
    print("  OK")

    print("\n=== 14. Bad email format ===")
    code, html = post("/api/register",
                      username="bob", email="not-an-email", password="bob12345")
    assert_("valid email" in html.lower(), "Expected bad-email error")
    print("  OK")

    print("\n=== 15. Short password ===")
    code, html = post("/api/register",
                      username="bob", email="bob@example.com", password="123")
    assert_("at least 6" in html.lower(), "Expected short-password error")
    print("  OK")

    print("\n=== 16. Username too short ===")
    code, html = post("/api/register",
                      username="ab", email="ab@example.com", password="abc123")
    assert_("3" in html and "20" in html, "Expected username length error")
    print("  OK")

    print("\n=== 17. Username with bad chars ===")
    code, html = post("/api/register",
                      username="bad name!", email="bad@example.com", password="abc123")
    # Should reject the space/exclamation
    assert_("3" in html and "20" in html or "letter" in html.lower(), "Expected username format error")
    print("  OK")

    print("\n=== 18. Notifications page when signed in ===")
    code, html = get("/notifications")
    assert_("Notifications" in html, "Expected notifications page")
    assert_("alice" in html, "Expected alice in notifications")
    print("  OK")

    print("\n\n*** ALL TESTS PASSED ***\n")
finally:
    server.terminate()
    try: server.wait(timeout=3)
    except Exception: server.kill()
    try: os.remove(DB)
    except Exception: pass
    try: os.remove(os.path.join(os.path.dirname(__file__), "reset_link.log"))
    except Exception: pass
