#!/usr/bin/env python3
"""Local smoke tests for Duoweilai v0.4 — English UI + 5-design language."""
import http.client, urllib.parse, json, re, sys

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
    c.close()
    return r.status, raw, setcookie

def extract_session(setcookie):
    m = re.search(r"duoweilai_session=([^;]+)", setcookie)
    return m.group(1) if m else None

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  [PASS] {name}")
        passed += 1
    else:
        print(f"  [FAIL] {name} -- {detail}")
        failed += 1

print("\n=== Duoweilai v0.4 Smoke Tests ===\n")

# 1. Home page loads with English UI
st, raw, sc = req("GET", "/")
check("Home page loads (200)", st == 200)
check("Home has English title", "What future do you imagine" in raw)
check("Home has Sign up CTA", "Get started" in raw)
check("No Chinese left in home", "多未来" not in raw and "发布" not in raw)

# 2. Register
st, raw, sc = req("POST", "/api/register", {"username": "alice", "password": "secret123"})
check("Register alice (302 redirect)", st == 302)
alice_tok = extract_session(sc)
check("Session cookie set", bool(alice_tok))

# 3. Register duplicate
st, raw, sc = req("POST", "/api/register", {"username": "alice", "password": "xxxxxx"})
check("Duplicate username rejected", st == 200 and "already taken" in raw)

# 4. Register bob
st, raw, sc = req("POST", "/api/register", {"username": "bob", "password": "secret456"})
bob_tok = extract_session(sc)
check("Register bob OK", st == 302 and bool(bob_tok))

# 5. Login
st, raw, sc = req("POST", "/api/login", {"username": "alice", "password": "wrong"})
check("Wrong password rejected", st == 200 and "Incorrect" in raw)

st, raw, sc = req("POST", "/api/login", {"username": "alice", "password": "secret123"})
check("Correct login (302)", st == 302)
alice_tok2 = extract_session(sc)
check("Session renewed", bool(alice_tok2))

# 6. Publish a future (authenticated)
st, raw, sc = req("POST", "/api/future",
                   {"title": "What if cities only came alive at night?", "body": "Daytime is for preparation. Night is for living."},
                   cookie=f"duoweilai_session={alice_tok2}")
check("Publish future (302)", st == 302 and "/f/" in raw)
short = re.search(r'/f/([A-Z2-9]{5})', raw)
short = short.group(1) if short else None
check("Got short ID", bool(short), f"raw={raw[:200]}")

# 7. Unauthenticated publish rejected
st, raw, sc = req("POST", "/api/future", {"title": "test", "body": "x"})
check("Unauthenticated publish (401)", st == 401)

# 8. Seed detail page
if short:
    st, raw, sc = req("GET", f"/f/{short}")
    check(f"Seed page /f/{short} loads", st == 200)
    check("Seed shows English title", "cities only came alive" in raw)
    check("Seed shows English meta", "branches" in raw.lower() or "Future Seed" in raw)
    check("Seed has Contribute CTA", "Contribute" in raw)
    check("Seed has English labels", "People" in raw and "Place" in raw and "Story" in raw)
    check("No Chinese in seed page", "多未来" not in raw and "人物" not in raw)

    # 9. Contribute (People)
    st, raw, sc = req("POST", "/api/contribute",
                      {"future_id": short, "type": "people",
                       "title": "Maya — Night Navigator",
                       "body": "A guide who knows every rooftop in the city."},
                      cookie=f"duoweilai_session={alice_tok2}")
    check("Contribute People (302)", st == 302)
    check("Contribute redirect to seed", f"/f/{short}" in raw)

    # 10. Second contribution (Place)
    st, raw, sc = req("POST", "/api/contribute",
                      {"future_id": short, "type": "place",
                       "title": "Rooftop Garden District",
                       "body": "Where the best conversations happen."},
                      cookie=f"duoweilai_session={bob_tok}")
    check("Contribute Place as bob OK", st == 302)

    # 11. Comment
    st, raw, sc = req("POST", "/api/comment",
                      {"future_id": short, "body": "This is exactly what I was thinking about!"},
                      cookie=f"duoweilai_session={bob_tok}")
    check("Comment (302)", st == 302)
    check("Comment redirects back to seed", f"/f/{short}" in raw)

    # 12. Notification check
    st, raw, sc = req("GET", "/notifications", cookie=f"duoweilai_session={alice_tok2}")
    check("Notifications page loads", st == 200)
    check("Has English notification text", "commented on your future" in raw)

    # 13. Profile page
    st, raw, sc = req("GET", "/person/alice", cookie=f"duoweilai_session={alice_tok2}")
    check("Profile page loads", st == 200)
    check("Profile has English stats", "Futures" in raw and "Contributions" in raw)
    check("Profile has English tabs", "Futures Started" in raw)

    # 14. Explore page
    st, raw, sc = req("GET", "/explore")
    check("Explore page loads", st == 200)
    check("Explore has English labels", "Browse the futures" in raw)
    check("Explore shows published future", "cities only came alive" in raw)

# 15. CSS design language check
st, raw, sc = req("GET", "/")
check("Has Inter font import", "fonts.googleapis.com" in raw and "Inter" in raw)
check("Has dark theme colors", "#0a0a0b" in raw or "var(--bg)" in raw)
check("Has pill buttons (border-radius:999px)", "999px" in raw)
check("Has CTA boxes (dashed border)", "dashed" in raw)
check("Has seed card styling", "seed-card" in raw)

print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
sys.exit(0 if failed == 0 else 1)
