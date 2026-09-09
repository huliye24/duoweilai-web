"""Auth flow test: register, login, password reset, validation errors.

Ported from the v0.5 root test_auth.py to the shared Server/Client helpers
(the only behavior change: form POSTs now answer 302 instead of the
redirect-followed page, and CSRF is handled by Client). Own scratch server
on port 8092.
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

    # -- 1. Anonymous home --------------------------------------------
    r = c.prime()
    check("Logged-out CTA on home", "Plant your first seed" in r.text)
    check("Sign up link present", "Sign up" in r.text)

    # -- 2. Register page ---------------------------------------------
    r = c.get("/register")
    check("Register page loads", r.status == 200 and "Join Duoweilai" in r.text)
    check("Username field present", 'name="username"' in r.text)

    # -- 3. Register a new account (auto sign-in) -----------------------
    r = c.post("/api/register", username="alice", email="alice@example.com",
               password="secret123")
    check("Register -> 302 /", r.status == 302 and r.location == "/")
    check("Session cookie set", bool(c.session))
    r = c.get("/")
    check("Header shows alice after register", "alice" in r.text)

    # -- 4. Publish while signed in -------------------------------------
    r = c.post("/api/future", title="Cities on water by 2080",
               body="Floating districts everywhere", category="Cities")
    check("Publish -> 302 to seed", r.status == 302 and "/f/" in r.location)

    # -- 5. Logout -------------------------------------------------------
    r = c.get("/logout")
    check("Logout -> 302 /", r.status == 302 and r.location == "/")
    check("Session cleared", not c.session)
    r = c.get("/")
    check("Logged-out CTA again", "Plant your first seed" in r.text)
    check("Nav shows Sign in / Sign up", "Sign in" in r.text and "Sign up" in r.text)

    # -- 6. Publish while logged out --------------------------------------
    r = c.post("/api/future", title="Should fail", body="No")
    check("Blocked with friendly login page", r.status == 200
          and "Sign in to continue" in r.text)

    # -- 7-8. Wrong password, then correct password -------------------------
    r = c.post("/api/login", username="alice", password="wrong")
    check("Wrong password re-renders with error", r.status == 200
          and "incorrect" in r.text.lower())
    r = c.post("/api/login", username="alice", password="secret123")
    check("Login -> 302 /", r.status == 302 and r.location == "/")
    r = c.get("/")
    check("alice signed back in", "alice" in r.text)

    # -- 9-11. Forgot password -> reset link -> new password ----------------
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

    # -- 12. Old password dead, new password works ---------------------------
    r = c.post("/api/login", username="alice", password="secret123")
    check("Old password rejected", "incorrect" in r.text.lower())
    r = c.post("/api/login", username="alice", password="newpass99")
    check("New password logs in", r.status == 302 and r.location == "/")
    r = c.get("/")
    check("alice in header with new password", "alice" in r.text)

    # -- 13-17. Validation errors (exact v0.5 strings) ------------------------
    r = c.post("/api/register", username="alice", email="diff@example.com",
               password="another")
    check("Duplicate username rejected", "already taken" in r.text)
    r = c.post("/api/register", username="bob", email="not-an-email",
               password="bob12345")
    check("Bad email rejected", "valid email" in r.text.lower())
    r = c.post("/api/register", username="bob", email="bob@example.com",
               password="123")
    check("Short password rejected", "at least 6" in r.text.lower())
    r = c.post("/api/register", username="ab", email="ab@example.com",
               password="abc123")
    check("Short username rejected", "3" in r.text and "20" in r.text)
    r = c.post("/api/register", username="bad name!", email="bad@example.com",
               password="abc123")
    check("Username bad chars rejected", "3–20" in r.text or "letters" in r.text.lower())

    # -- 18. Notifications page while signed in --------------------------------
    r = c.get("/notifications")
    check("Notifications page loads", r.status == 200 and "Notifications" in r.text)
    check("Welcome notification for alice", "Welcome to Duoweilai, alice" in r.text)

    # -- 19. Reset link is single-use ------------------------------------------
    r = c.get(f"/reset/{token}")
    check("Used reset link shows form (validity checked on POST)",
          r.status == 200)
    r = c.post(f"/api/reset/{token}", password="another1")
    check("Used reset token rejected on POST", "invalid or has expired" in r.text.lower())

    # -- 20. CSRF enforcement ---------------------------------------------------
    r = c.request("POST", "/api/login", data={"username": "alice",
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
