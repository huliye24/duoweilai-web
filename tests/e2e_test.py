"""End-to-end test for the no-auth build of Duoweilai v0.4.

In this build everyone is auto-logged in as 'explorer', so all writes are
attributed to the same user. The test publishes a future, contributes two
items, comments, and checks the profile + explore pages.
"""
import http.client, urllib.parse, re, time, sys

HOST, PORT = "localhost", 8080

def req(method, path, data=None, cookie=None):
    c = http.client.HTTPConnection(HOST, PORT, timeout=10)
    headers = {}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if cookie:
        headers["Cookie"] = cookie
    c.request(method, path, body=body, headers=headers)
    r = c.getresponse()
    raw = r.read().decode("utf-8")
    setcookie = r.getheader("Set-Cookie") or ""
    location = r.getheader("Location") or ""
    c.close()
    return r.status, raw, setcookie, location

def check(name, cond, detail=""):
    msg = f"  [{'PASS' if cond else 'FAIL'}] {name}"
    if not cond and detail: msg += f" -- {detail}"
    print(msg)
    return cond

passed = failed = 0
def C(name, cond, detail=""):
    global passed, failed
    if check(name, cond, detail): passed += 1
    else: failed += 1

print("\n=== Duoweilai v0.4 E2E (no-auth build) ===\n")

# 1. Auto-login on first GET
st, raw, sc, loc = req("GET", "/")
C("Home returns 200", st == 200)
tok = re.search(r"duoweilai_session=([^;]+)", sc)
session = tok.group(1) if tok else None
C("Session cookie issued on first visit", bool(session))

# 2. Publish a future (no registration needed)
title = f"A future for E2E testing {int(time.time())}"
st, raw, sc, loc = req("POST", "/api/future",
                       {"title": title, "body": "Testing the no-auth flow."},
                       cookie=f"duoweilai_session={session}")
C("Publish future returns 302", st == 302)
m = re.search(r"/f/([A-Z2-9]{5})", loc)
short = m.group(1) if m else None
C("Got short ID from redirect location", bool(short), f"loc={loc}")

# 3. Seed detail page
if short:
    st, raw, sc, loc = req("GET", f"/f/{short}")
    C("Seed page loads", st == 200)
    C("Seed shows new title", title in raw)
    C("Seed shows creator as explorer", "explorer" in raw)
    C("Seed has Contribute form", "Contribute" in raw)
    C("Seed has Post comment button", "Post comment" in raw)

# 4. Contribute (People)
if short:
    st, raw, sc, loc = req("POST", "/api/contribute",
                          {"future_id": short, "type": "people",
                           "title": "Maya — Night Navigator",
                           "body": "Knows every rooftop in the city."},
                          cookie=f"duoweilai_session={session}")
    C("Contribute People -> 302", st == 302)

# 5. Contribute (Place)
if short:
    st, raw, sc, loc = req("POST", "/api/contribute",
                          {"future_id": short, "type": "place",
                           "title": "Rooftop Garden District",
                           "body": "Where the best conversations happen."},
                          cookie=f"duoweilai_session={session}")
    C("Contribute Place -> 302", st == 302)

# 6. Comment
if short:
    st, raw, sc, loc = req("POST", "/api/comment",
                          {"future_id": short, "body": "Love this future!"},
                          cookie=f"duoweilai_session={session}")
    C("Comment -> 302", st == 302)

# 7. Seed detail shows contributions
if short:
    st, raw, sc, loc = req("GET", f"/f/{short}")
    C("Seed shows Maya contribution", "Maya" in raw and "Night Navigator" in raw)
    C("Seed shows Rooftop contribution", "Rooftop Garden District" in raw)
    C("Seed shows comment", "Love this future!" in raw)
    C("Seed shows branch count >=2", "Growing Content" in raw)

# 8. Explore page
st, raw, sc, loc = req("GET", "/explore")
C("Explore page loads", st == 200)
C("Explore shows our new future", title in raw)

# 9. Profile page
st, raw, sc, loc = req("GET", "/person/explorer")
C("Profile page loads", st == 200)
C("Profile has English stats", "Futures" in raw and "Contributions" in raw)
C("Profile shows explorer's futures", title in raw)

# 10. Notifications page (auto-login gives empty notifs)
st, raw, sc, loc = req("GET", "/notifications")
C("Notifications page loads", st == 200)
C("Notifications page has English title", "Notifications" in raw)

# 11. Auth routes redirect (no broken links)
for p in ["/login", "/register", "/logout"]:
    st, raw, sc, loc = req("GET", p)
    C(f"GET {p} redirects to /", st == 302 and loc == "/")
for p in ["/api/register", "/api/login"]:
    st, raw, sc, loc = req("POST", p, {"username": "x", "password": "y"})
    C(f"POST {p} redirects to /", st == 302 and loc == "/")

# 12. World auto-upgrade (need 5 contributions)
if short:
    for i in range(5):
        req("POST", "/api/contribute",
            {"future_id": short, "type": "story",
             "title": f"Test story {i}", "body": "filler"},
            cookie=f"duoweilai_session={session}")
    st, raw, sc, loc = req("GET", f"/f/{short}")
    C("After 5+ contributions, seed is a World", "World" in raw)

# 13. CSS design language preserved
st, raw, sc, loc = req("GET", "/")
C("Inter font present", "fonts.googleapis.com" in raw and "Inter" in raw)
C("Dark theme variables present", "--bg" in raw)
C("Pill buttons present", "999px" in raw)
C("Dashed CTA box present", "dashed" in raw)
C("English-only UI", "多未来" not in raw and "发布" not in raw)

print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
sys.exit(0 if failed == 0 else 1)
