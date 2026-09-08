"""Full end-to-end API test with fresh DB."""
import http.client, urllib.parse, re, sys

HOST, PORT = "localhost", 8080

def req(method, path, data=None, cookie=None):
    """Single-use connection for each request."""
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

def extract_token(sc):
    m = re.search(r"duoweilai_session=([^;]+)", sc)
    return m.group(1) if m else None

def check(name, condition, detail=""):
    ok = "[PASS]" if condition else "[FAIL]"
    msg = f"  {ok} {name}"
    if not condition and detail: msg += f" -- {detail}"
    print(msg)
    return condition

print("\n=== Duoweilai v0.4 Full E2E Tests ===\n")

# Fresh user names (timestamp suffix to avoid collisions)
import time
suffix = str(int(time.time()))[-4:]
alice_name = f"alice{suffix}"
bob_name = f"bob{suffix}"

# 1. Register alice
st, raw, sc = req("POST", "/api/register", {"username": alice_name, "password": "secret123"})
check(f"Register {alice_name} -> 302", st == 302, f"got {st}, body={raw[:100]}")
alice_tok = extract_token(sc)
check("Session cookie received", bool(alice_tok), f"sc={repr(sc)[:50]}")

# 2. Register bob
st, raw, sc = req("POST", "/api/register", {"username": bob_name, "password": "secret456"})
check(f"Register {bob_name} -> 302", st == 302)
bob_tok = extract_token(sc)
check("Bob session cookie received", bool(bob_tok))

# 3. Duplicate username
st, raw, sc = req("POST", "/api/register", {"username": alice_name, "password": "xxxx"})
check("Duplicate rejected -> 200", st == 200)
check("Error message shown", "already taken" in raw)

# 4. Wrong password
st, raw, sc = req("POST", "/api/login", {"username": alice_name, "password": "wrong"})
check("Wrong password -> 200", st == 200)
check("Wrong password message", "Incorrect" in raw)

# 5. Correct login
st, raw, sc = req("POST", "/api/login", {"username": alice_name, "password": "secret123"})
check("Correct login -> 302", st == 302)
login_tok = extract_token(sc)
check("Login cookie received", bool(login_tok))

# 6. Publish future
st, raw, sc = req("POST", "/api/future",
                   {"title": "What if cities only came alive at night?",
                    "body": "Daytime is for preparation. Night is for living."},
                   cookie=f"duoweilai_session={login_tok}")
check("Publish future -> 302", st == 302, f"got {st}")
m = re.search(r'/f/([A-Z2-9]{5})', raw)
short = m.group(1) if m else "(not in body)"
check("Redirect body has /f/ short ID", m is not None, f"body={raw[:100]}")
if not m:
    # Check Location header via redirect
    # Actually, let's check if the short ID is anywhere
    # The redirect body should have the /f/ link
    pass

# 7. Unauthenticated publish
st, raw, sc = req("POST", "/api/future", {"title": "x", "body": "y"})
check("Unauthenticated -> 401", st == 401)

# 8. Get explore page
st, raw, sc = req("GET", "/explore")
check("Explore page loads", st == 200)
check("Explore has English content", "Browse the futures" in raw)
check("Explore shows future", "cities only came alive" in raw)

# 9. Get seed page
if m:
    st, raw, sc = req("GET", f"/f/{m.group(1)}")
    check("Seed detail page loads", st == 200)
    check("Seed shows title", "cities only came alive" in raw)
    check("Seed has Contribute form", "Contribute" in raw)
    check("Seed has English labels", "People" in raw and "Place" in raw and "Story" in raw)

    # 10. Contribute (People type)
    st, raw, sc = req("POST", "/api/contribute",
                      {"future_id": m.group(1), "type": "people",
                       "title": "Maya — Night Navigator",
                       "body": "Knows every rooftop in the city."},
                      cookie=f"duoweilai_session={login_tok}")
    check("Contribute People -> 302", st == 302)

    # 11. Bob contributes Place
    st, raw, sc = req("POST", "/api/contribute",
                      {"future_id": m.group(1), "type": "place",
                       "title": "Rooftop Garden District",
                       "body": "Where the best conversations happen."},
                      cookie=f"duoweilai_session={bob_tok}")
    check("Contribute Place (bob) -> 302", st == 302)

    # 12. Comment
    st, raw, sc = req("POST", "/api/comment",
                      {"future_id": m.group(1), "body": "This is exactly what I was thinking about!"},
                      cookie=f"duoweilai_session={bob_tok}")
    check("Comment -> 302", st == 302)

    # 13. Notifications
    st, raw, sc = req("GET", "/notifications", cookie=f"duoweilai_session={login_tok}")
    check("Notifications page loads", st == 200)
    check("Has English notification", "commented on your future" in raw)

    # 14. Profile page
    st, raw, sc = req("GET", f"/person/{alice_name}", cookie=f"duoweilai_session={login_tok}")
    check("Profile page loads", st == 200)
    check("Profile has English", "Futures" in raw and "Contributions" in raw)

# 15. CSS / design language
st, raw, sc = req("GET", "/")
check("Inter font in CSS", "fonts.googleapis.com" in raw and "Inter" in raw)
check("Dark theme CSS vars", "--bg" in raw)
check("Pill buttons (999px)", "999px" in raw)
check("Dashed CTA boxes", "dashed" in raw)
check("seed-card class", "seed-card" in raw)
check("No Chinese anywhere", "多未来" not in raw and "发布" not in raw and "探索" not in raw)

print("\n=== Done ===\n")
