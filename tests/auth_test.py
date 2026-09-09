"""Auth flow test: register (email + password -> system-assigned ID),
login by email and by ID, password reset, validation errors.

Own scratch server on port 8092. System IDs are deterministic on a fresh
DB: the first account gets 100010 (100000-100009 and 100011 are 靓号,
held back for manual delivery), the second gets 100012.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RESET_LOG, Client, Server, check, finish

PORT = 8092
if os.path.exists(RESET_LOG):
    os.remove(RESET_LOG)  # read only the reset link this run generates

server = Server(PORT)
code = 1
try:
    c = Client(server)
    print(f"\n=== Duoweilai v0.6 auth flow (port {PORT}) ===\n")

    # -- 1. Anonymous home: the world first, auth in the background ------
    r = c.prime()
    check("Guest sees the world, not a login wall",
          "A world of imagined futures" in r.text)
    check("No big register CTA on guest home",
          "Plant your first seed" not in r.text)
    check("Nav still offers Sign in / Sign up",
          'href="/login"' in r.text and 'href="/register"' in r.text)

    # -- 2. Register page: email + password only -------------------------
    r = c.get("/register")
    check("Register page loads", r.status == 200 and "Join Duoweilai" in r.text)
    check("Email field present", 'name="email"' in r.text)
    check("No username field — the ID is system-assigned",
          'name="username"' not in r.text)

    # -- 3. Register: email + password -> assigned ID ----------------------
    r = c.post("/api/register", email="alice@example.com", password="secret123")
    check("Register -> 302 to welcome reveal",
          r.status == 302 and r.location == "/welcome?id=100010",
          f"got {r.status} {r.location}")
    check("Session cookie set", bool(c.session))
    r = c.get("/welcome?id=100010")
    check("Welcome page shows the ID", "100010" in r.text
          and "Your Duoweilai ID" in r.text)
    r = c.get("/")
    check("Header shows the ID after register", "100010" in r.text)

    # -- 4. Publish while signed in -----------------------------------------
    r = c.post("/api/future", title="Cities on water by 2080",
               body="Floating districts everywhere", category="Cities")
    check("Publish -> 302 to seed", r.status == 302 and "/f/" in r.location)

    # -- 5. Logout -----------------------------------------------------------
    r = c.get("/logout")
    check("Logout -> 302 /", r.status == 302 and r.location == "/")
    check("Session cleared", not c.session)
    r = c.get("/")
    check("Back to guest view", "A world of imagined futures" in r.text)

    # -- 6. Publish while logged out ------------------------------------------
    r = c.post("/api/future", title="Should fail", body="No")
    check("Blocked with friendly login page", r.status == 200
          and "Sign in to continue" in r.text)

    # -- 7-8. Wrong password, then correct password (by email) ----------------
    r = c.post("/api/login", username="alice@example.com", password="wrong")
    check("Wrong password re-renders with error", r.status == 200
          and "incorrect" in r.text.lower())
    r = c.post("/api/login", username="alice@example.com", password="secret123")
    check("Login by email -> 302 /", r.status == 302 and r.location == "/")
    r = c.get("/")
    check("Signed back in", "100010" in r.text)

    # -- 9. Login by system ID --------------------------------------------------
    c.get("/logout")
    r = c.post("/api/login", username="100010", password="secret123")
    check("Login by ID -> 302 /", r.status == 302 and r.location == "/")
    r = c.get("/")
    check("ID login works", "100010" in r.text)

    # -- 10-12. Forgot password -> reset link -> new password ----------------
    r = c.get("/forgot")
    check("Forgot page redirects while signed in", r.status == 302
          and r.location == "/")
    c.get("/logout")
    r = c.get("/forgot")
    check("Forgot page loads when signed out", r.status == 200
          and "Forgot your password?" in r.text)
    r = c.post("/api/forgot", email="alice@example.com")
    check("Forgot -> inbox confirmation", r.status == 200 and "Check your inbox" in r.text)
    check("reset_link.log written", os.path.exists(RESET_LOG))
    lines = [ln for ln in open(RESET_LOG, encoding="utf-8").read().splitlines()
             if "Link: " in ln]
    check("Reset link logged", bool(lines))
    token = lines[0].split("/reset/")[1].strip() if lines else ""
    check("Token extracted", bool(token))
    r = c.get(f"/reset/{token}")
    check("Reset form loads", r.status == 200 and "Set a new password" in r.text)
    r = c.post(f"/api/reset/{token}", password="newpass99")
    check("Reset -> Password updated", r.status == 200 and "Password updated" in r.text)

    # -- 13. Old password dead, new password works -----------------------------
    r = c.post("/api/login", username="alice@example.com", password="secret123")
    check("Old password rejected", "incorrect" in r.text.lower())
    r = c.post("/api/login", username="alice@example.com", password="newpass99")
    check("New password logs in", r.status == 302 and r.location == "/")
    r = c.get("/")
    check("ID in header with new password", "100010" in r.text)

    # -- 14-17. Validation errors -----------------------------------------------
    r = c.post("/api/register", email="alice@example.com", password="another")
    check("Duplicate email rejected", "already registered" in r.text)
    r = c.post("/api/register", email="not-an-email", password="bob12345")
    check("Bad email rejected", "valid email" in r.text.lower())
    r = c.post("/api/register", email="bob@example.com", password="123")
    check("Short password rejected", "at least 6" in r.text.lower())
    c2 = Client(server)
    c2.prime()
    r = c2.post("/api/register", email="bob@example.com", password="bob12345")
    check("Second account gets the next non-premium ID",
          r.status == 302 and r.location == "/welcome?id=100012",
          f"got {r.status} {r.location}")

    # -- 18. Notifications page while signed in ----------------------------------
    r = c.get("/notifications")
    check("Notifications page loads", r.status == 200 and "Notifications" in r.text)
    check("Welcome notification carries the ID",
          "Welcome to Duoweilai! Your ID is 100010." in r.text)

    # -- 19. Reset link is single-use ---------------------------------------------
    r = c.get(f"/reset/{token}")
    check("Used reset link shows form (validity checked on POST)",
          r.status == 200)
    r = c.post(f"/api/reset/{token}", password="another1")
    check("Used reset token rejected on POST", "invalid or has expired" in r.text.lower())

    # -- 20. CSRF enforcement -------------------------------------------------------
    r = c.request("POST", "/api/login", data={"username": "alice@example.com",
                                              "password": "newpass99"},
                  send_csrf=False)
    check("POST without CSRF token -> 403", r.status == 403)

    code = finish()
finally:
    server.stop()
    try:
        os.remove(RESET_LOG)
    except OSError:
        pass
sys.exit(code)
