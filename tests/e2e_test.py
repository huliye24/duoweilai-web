"""End-to-end test of the v0.6 user journey (real accounts).

Register -> publish -> contribute x2 -> comment -> explore (search +
category + pagination) -> world upgrade -> profile -> notifications ->
logout/login. Exercises the HTML pages and the form-POST side of the API.
Uses its own scratch server on port 8091.
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Client, Server, check, finish

PORT = 8091
server = Server(PORT)
stamp = str(int(time.time()))
try:
    c = Client(server)
    print(f"\n=== Duoweilai v0.6 E2E (port {PORT}) ===\n")

    # -- 1. Anonymous home -------------------------------------------
    r = c.prime()
    check("Home returns 200", r.status == 200)
    check("CSRF cookie issued on first visit", bool(c.csrf))
    check("Logged-out CTA shown", "Plant your first seed" in r.text)
    check("Sign in link in nav", 'href="/login"' in r.text)
    check("Sign up link in nav", 'href="/register"' in r.text)

    # -- 2. Register page + account ----------------------------------
    r = c.get("/register")
    check("Register page loads", r.status == 200 and "Join Duoweilai" in r.text)
    r = c.post("/api/register", username="walkerb", email="walker@example.com",
               password="secret123")
    check("Register -> 302 to /", r.status == 302 and r.location == "/",
          f"got {r.status} {r.location}")
    check("Session cookie set on register", bool(c.session))
    r = c.get("/")
    check("Header shows signed-in user", "walkerb" in r.text)
    check("Publish form visible when signed in", "Publish a Future" in r.text)

    # -- 3. Publish a future (form POST) ------------------------------
    title = f"A future for E2E testing {stamp}"
    r = c.post("/api/future", title=title, body="Testing the v0.6 flow.",
               category="Cities")
    check("Publish -> 302 to seed page", r.status == 302)
    m = re.search(r"/f/([A-Z2-9]{5})", r.location or "")
    short = m.group(1) if m else ""
    check("Got short ID from redirect", bool(short), f"loc={r.location}")
    check("Redirect is to the new seed", r.location == f"/f/{short}")

    # -- 4. Seed page -------------------------------------------------
    r = c.get(f"/f/{short}")
    check("Seed page loads", r.status == 200)
    check("Seed shows title", title in r.text)
    check("Seed shows category", "Cities" in r.text)
    check("Seed shows creator", "walkerb" in r.text)
    check("Seed has Explore this Future grid", "Explore this Future" in r.text)
    check("Seed has Contribute CTA", "Contribute" in r.text)
    check("Seed has Post comment button", "Post comment" in r.text)
    check("Bogus seed 404s", c.get("/f/ZZZZZ").status == 404)

    # -- 5. Contribute People + Place ---------------------------------
    r = c.post("/api/contribute", future_id=short, type="people",
               title="Maya — Night Navigator",
               body="Knows every rooftop in the city.")
    check("Contribute People -> 302", r.status == 302 and r.location == f"/f/{short}")
    r = c.post("/api/contribute", future_id=short, type="place",
               title="Rooftop Garden District",
               body="Where the best conversations happen.")
    check("Contribute Place -> 302", r.status == 302)

    # -- 6. Comment ----------------------------------------------------
    r = c.post("/api/comment", future_id=short, body="Love this future!")
    check("Comment -> 302", r.status == 302)

    # -- 7. Seed page shows it all ------------------------------------
    r = c.get(f"/f/{short}")
    check("Shows People contribution", "Maya — Night Navigator" in r.text)
    check("Shows Place contribution", "Rooftop Garden District" in r.text)
    check("Shows comment", "Love this future!" in r.text)
    check("Section labels pluralized correctly",
          ">People<" in r.text and ">Places<" in r.text)

    # -- 8. Explore: search, category, pagination ----------------------
    r = c.get("/explore")
    check("Explore page loads", r.status == 200)
    check("Explore shows the new future", title in r.text)
    check("Category chips render", 'href="/explore?cat=Life"' in r.text)
    r = c.get(f"/explore?q=E2E testing {stamp}")
    check("Search finds the future", r.status == 200 and title in r.text)
    check("Search shows Results header", "Results" in r.text)
    r = c.get("/explore?cat=Cities")
    check("Category filter keeps our future", title in r.text)
    r = c.get("/explore?cat=Work")
    check("Other category excludes it", title not in r.text)
    r = c.get("/explore?page=999")
    check("Out-of-range page clamps (no crash)", r.status == 200)

    # -- 9. World upgrade at 5+ contributions --------------------------
    for i in range(5):
        c.post("/api/contribute", future_id=short, type="story",
               title=f"Test story {i}", body="filler")
    r = c.get(f"/f/{short}")
    check("Seed upgrades to World", "World" in r.text)
    r = c.get(f"/world/{short}")
    check("World page loads with Timeline", r.status == 200 and "Timeline" in r.text)
    check("World page lists contributors", "Contributors" in r.text)

    # -- 10. Profile page ----------------------------------------------
    r = c.get("/person/walkerb")
    check("Profile page loads", r.status == 200)
    check("Profile shows stats labels", "Futures" in r.text and "Contributions" in r.text)
    check("Profile shows the seed", title in r.text)

    # -- 11. Notifications ----------------------------------------------
    r = c.get("/notifications")
    check("Notifications page loads", r.status == 200 and "Notifications" in r.text)
    check("Welcome notification present", "Welcome to Duoweilai" in r.text)

    # -- 12. Logout / login round-trip ----------------------------------
    r = c.get("/logout")
    check("Logout (GET link) -> 302 to /", r.status == 302 and r.location == "/")
    check("Session cookie cleared", not c.session)
    r = c.get("/")
    check("Back to logged-out CTA", "Plant your first seed" in r.text)
    r = c.post("/api/login", username="walkerb", password="secret123")
    check("Login -> 302 to /", r.status == 302 and r.location == "/")
    r = c.get("/")
    check("Signed back in", "walkerb" in r.text)

    # -- 13. Anonymous write attempts ------------------------------------
    anon = Client(server)
    anon.prime()
    r = anon.post("/api/future", title="nope", body="nope")
    check("Anonymous form publish -> login page (200)", r.status == 200
          and "Sign in to continue" in r.text)

    # -- 14. Design language preserved -----------------------------------
    r = c.get("/")
    css = c.get("/static/style.css")
    check("Inter font present", "fonts.googleapis.com" in r.text and "Inter" in r.text)
    check("Dark theme variables present", css.status == 200 and "--bg" in css.text)
    check("Pill buttons present", "999px" in css.text)
    check("Dashed CTA box present", "dashed" in css.text)
    check("CSS served from /static", css.status == 200)
    check("JS served from /static", c.get("/static/app.js").status == 200)
    check("No inline <script> (CSP-safe)", "<script>" not in r.text)

    code = finish()
finally:
    server.stop()
sys.exit(code)
