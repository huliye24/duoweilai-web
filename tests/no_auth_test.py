"""Test no-auth UI."""
import http.client

HOST = "localhost"
PORT = 8080

def get(path):
    c = http.client.HTTPConnection(HOST, PORT, timeout=5)
    c.request("GET", path)
    r = c.getresponse()
    raw = r.read().decode("utf-8")
    sc = r.getheader("Set-Cookie") or ""
    c.close()
    return r.status, raw, sc

passed = failed = 0
def check(name, cond):
    global passed, failed
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if cond: passed += 1
    else: failed += 1

print("\n=== Auto-login UI Test ===\n")

# Home page
st, raw, sc = get("/")
check("Home 200", st == 200)
check("Auto-session cookie set", "duoweilai_session" in sc)
check("No 'Sign in' text", "Sign in" not in raw)
check("No 'Sign up' text", "Sign up" not in raw)
check("No 'Get started' button", "Get started" not in raw)
check('No /login link', 'href="/login"' not in raw)
check('No /register link', 'href="/register"' not in raw)
check("Publish button visible", "Publish a Future" in raw)
check("Explorer username in header", "explorer" in raw)
check("Notifications link in header", "Notifications" in raw)

# Seed page — use a known seed from earlier test
import re
shorts = re.findall(r'/f/([A-Z2-9]{5})', raw)
if shorts:
    short = shorts[0]
    st2, raw2, _ = get(f"/f/{short}")
    check("Seed page 200", st2 == 200)
    check("Seed no 'Sign in to comment'", "to leave a comment" not in raw2)
    check("Seed no 'Sign in to contribute'", "Sign in" not in raw2)
    check("Seed has Contribute form", "Contribute" in raw2)
    check("Seed has Post comment", "Post comment" in raw2)
    check("Seed shows creator explorer", "explorer" in raw2)

# Login routes redirect
import urllib.parse
for p in ["/login", "/register", "/logout"]:
    c = http.client.HTTPConnection(HOST, PORT, timeout=5)
    c.request("GET", p)
    r = c.getresponse()
    loc = r.getheader("Location")
    r.read()
    c.close()
    check(f"GET {p} redirects to /", r.status == 302 and loc == "/")

# POST api/register and api/login also redirect
for p in ["/api/register", "/api/login"]:
    c = http.client.HTTPConnection(HOST, PORT, timeout=5)
    body = urllib.parse.urlencode({"username": "x", "password": "y"})
    c.request("POST", p, body=body,
              headers={"Content-Type": "application/x-www-form-urlencoded"})
    r = c.getresponse()
    loc = r.getheader("Location")
    r.read()
    c.close()
    check(f"POST {p} redirects to /", r.status == 302 and loc == "/")

print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
