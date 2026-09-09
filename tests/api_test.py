"""API test: JSON endpoints, content negotiation, edits, branch flow,
reply notifications, input caps, 404s, and the POST rate limit.

Runs against its own scratch server on port 8093. The rate-limit check
goes last on purpose — it exhausts the per-IP POST budget (60/minute)
shared by everything else in this file.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Client, Server, check, finish

PORT = 8093
server = Server(PORT)
code = 1
try:
    c = Client(server)  # alice
    stamp = str(int(time.time()))
    print(f"\n=== Duoweilai v0.6 API test (port {PORT}) ===\n")

    # -- 1. Health -----------------------------------------------------
    r = c.prime("/api/health")
    check("CSRF cookie from a JSON GET", bool(c.csrf))
    check("health ok", r.status == 200 and r.json()["ok"] is True)
    check("health reports version", r.json().get("version") == "0.6")

    # -- 2. Register via JSON ------------------------------------------
    r = c.post_json("/api/register", username="alice", email="alice@example.com",
                    password="secret123")
    check("JSON register -> envelope", r.status == 200
          and r.json()["ok"] is True and r.json()["redirect"] == "/")
    check("Session cookie set by JSON register", bool(c.session))

    # -- 3. Pagination: 13 seeds total ----------------------------------
    shorts = []
    for i in range(12):
        cat = "Cities" if i % 2 == 0 else "Life"
        r = c.post_json("/api/future", title=f"API pagination seed {i} mk{stamp}",
                        body=f"filler body {i}", category=cat)
        shorts.append(r.json()["short"])
    check("12 seeds created via JSON", all(len(s) == 5 for s in shorts)
          and len(set(shorts)) == 12)

    r = c.get("/api/futures?per_page=5").json()
    check("list: total", r["total"] == 12, f"total={r['total']}")
    check("list: pages = ceil(12/5)", r["pages"] == 3)
    check("list: page 1 has 5 items", len(r["items"]) == 5)
    r = c.get("/api/futures?per_page=5&page=3").json()
    check("list: last page has 2 items", len(r["items"]) == 2)
    r = c.get("/api/futures?per_page=5&page=99").json()
    check("list: past-the-end page is empty, not an error",
          r["items"] == [] and r["page"] == 99)
    r = c.get("/api/futures?per_page=1000").json()
    check("list: per_page clamped to 100", r["per_page"] == 100
          and len(r["items"]) == 12)
    r = c.get("/api/futures?page=0").json()
    check("list: page clamped up to 1", r["page"] == 1)
    check("list: envelope shape", r["ok"] is True and "items" in r)

    # -- 4. Search --------------------------------------------------------
    r = c.post_json("/api/future", title=f"Quiet seed {stamp}",
                    body=f"hidden token zq{stamp} inside the body",
                    category="Work")
    work_short = r.json()["short"]
    r = c.get(f"/api/futures?q=zq{stamp}").json()
    check("search matches body text", r["total"] == 1
          and r["items"][0]["short_id"] == work_short)
    r = c.get(f"/api/futures?q=API pagination seed 7 mk{stamp}").json()
    check("search matches title text", r["total"] == 1)
    r = c.get("/api/futures?q=100%25_match").json()
    check("LIKE wildcards escaped (no match-all)", r["total"] == 0,
          f"total={r['total']}")
    r = c.get("/api/futures?q=quiet").json()
    check("search is case-insensitive-ish substring", r["total"] >= 1)

    # -- 5. Category filter ------------------------------------------------
    r = c.get("/api/futures?cat=Cities").json()
    check("cat=Cities -> 6", r["total"] == 6
          and all(i["category"] == "Cities" for i in r["items"]))
    r = c.get("/api/futures?cat=Life").json()
    check("cat=Life -> 6", r["total"] == 6)
    r = c.get("/api/futures?cat=All").json()
    check("cat=All means no filter", r["total"] == 13)
    r = c.get("/api/futures?cat=Bogus").json()
    check("unknown category -> empty, not error", r["total"] == 0)
    r = c.get(f"/api/futures?cat=Work&q=zq{stamp}").json()
    check("cat + q combine (AND)", r["total"] == 1)

    # -- 6. Content negotiation ---------------------------------------------
    target = shorts[0]
    r = c.post("/api/contribute", future_id=target, type="people",
               title="Maya the Navigator", body="Form post from the site UI")
    check("form POST contribute -> 302", r.status == 302
          and r.location == f"/f/{target}")
    r = c.post_json("/api/contribute", future_id=target, type="place",
                    title="Harbor Steps", body="JSON post from app.js")
    check("JSON POST contribute -> envelope", r.status == 200
          and r.json()["ok"] is True and r.json()["redirect"] == f"/f/{target}")
    r = c.post("/api/future", title="", body="x")
    check("validation error is JSON even for form posts",
          r.status == 400 and r.json()["error"] == "Title required")
    r = c.request("POST", "/api/future", data={"title": "x"}, send_csrf=False)
    check("missing CSRF -> 403 JSON", r.status == 403
          and "CSRF" in r.json()["error"])
    anon = Client(server)
    anon.prime("/api/health")
    r = anon.post_json("/api/future", title="x", body="y")
    check("anonymous JSON write -> 401", r.status == 401
          and r.json()["error"] == "Sign in required")

    # -- 7. Detail endpoints -------------------------------------------------
    r = c.get(f"/api/futures/{target}").json()
    check("detail: future block", r["future"]["short_id"] == target)
    check("detail: 2 contributions", len(r["contributions"]) == 2)
    check("detail: empty comments list", r["comments"] == [])
    check("detail: no child branches yet", r["child_branches"] == [])
    r = c.get(f"/api/futures/{target}/contributions?type=people").json()
    check("contributions filtered by type", r["total"] == 1
          and r["items"][0]["type"] == "people")
    r = c.get("/api/futures/ZZZZZ")
    check("unknown seed -> 404 JSON", r.status == 404
          and r.json()["ok"] is False)

    # -- 8. Edits: owner-checked, always JSON -----------------------------------
    b = Client(server)  # bob
    b.prime("/api/health")
    r = b.post_json("/api/register", username="bobb", email="bob@example.com",
                    password="bobpass1")
    check("second account registered", r.status == 200 and r.json()["ok"])

    r = c.post_json(f"/api/future/{target}/edit",
                    title=f"Renamed by alice {stamp}", body="updated body",
                    category="Work")
    check("owner edits seed -> 200", r.status == 200
          and r.json()["redirect"] == f"/f/{target}")
    r = c.get(f"/api/futures/{target}").json()
    check("edit persisted + edited_at set", r["future"]["title"] ==
          f"Renamed by alice {stamp}" and r["future"]["edited_at"])
    check("edit changed category", r["future"]["category"] == "Work")
    check("seed page shows edited mark", "edited" in c.get(f"/f/{target}").text)
    r = b.post_json(f"/api/future/{target}/edit", title="hijack", body="nope")
    check("non-owner seed edit -> 403", r.status == 403
          and "creator" in r.json()["error"])

    r = b.post_json("/api/contribute", future_id=target, type="story",
                    title="Bob's story", body="from bob")
    check("bob contributes", r.status == 200 and r.json()["ok"])
    contribs = c.get(f"/api/futures/{target}/contributions").json()["items"]
    bob_contrib = next(x for x in contribs if x["creator"] == "bobb")
    r = b.post_json(f"/api/contribution/{bob_contrib['id']}/edit",
                    title="Bob's story v2", body="edited by bob")
    check("author edits own contribution", r.status == 200
          and r.json()["ok"])
    r = c.post_json(f"/api/contribution/{bob_contrib['id']}/edit",
                    title="hijack", body="nope")
    check("non-owner contribution edit -> 403", r.status == 403)

    r = c.post_json("/api/comment", future_id=target, body="Alice's comment")
    check("alice comments on own seed", r.status == 200)
    r = b.post_json("/api/comment", future_id=target, body="Bob's comment")
    check("bob comments", r.status == 200)
    cms = c.get(f"/api/futures/{target}/comments").json()["items"]
    alice_cm = next(x for x in cms if x["author"] == "alice")
    bob_cm = next(x for x in cms if x["author"] == "bobb")
    check("comments carry parent_id (null at top level)",
          alice_cm["parent_id"] is None and bob_cm["parent_id"] is None)
    r = c.post_json(f"/api/comment/{alice_cm['id']}/edit",
                    body="Alice's comment, edited")
    check("author edits own comment", r.status == 200)
    r = b.post_json(f"/api/comment/{alice_cm['id']}/edit", body="hijack")
    check("non-owner comment edit -> 403", r.status == 403)
    check("contribution + comment show (edited)",
          "(edited)" in c.get(f"/f/{target}").text)

    # -- 9. Branch flow ------------------------------------------------------------
    r = c.post_json("/api/future", title=f"Branch parent {stamp}",
                    body="root of the branch test", category="Life")
    parent = r.json()["short"]
    r = b.post_json("/api/future", title=f"Child branch {stamp}",
                    body="branched off", parent=parent)
    child = r.json()["short"]
    check("branch created", r.status == 200 and len(child) == 5)
    r = b.get(f"/api/futures/{child}").json()
    check("child records parent_short_id", r["future"]["parent_short_id"] == parent)
    r = b.get(f"/api/futures/{parent}").json()
    check("parent lists child in child_branches",
          [x["short_id"] for x in r["child_branches"]] == [child])
    check("child page shows Branched from",
          "Branched from" in b.get(f"/f/{child}").text
          and parent in b.get(f"/f/{child}").text)
    check("parent page shows Recent Branches with child",
          "Recent Branches" in b.get(f"/f/{parent}").text
          and f"Child branch {stamp}" in b.get(f"/f/{parent}").text)
    r = b.post_json("/api/future", title="orphan", body="x", parent="ZZZZZ")
    check("branch from missing parent -> 404", r.status == 404)

    # -- 10. Notifications: contribute/comment/branch/reply ---------------------------
    notifs = c.get("/api/notifications").json()
    kinds = [(n["type"], n["text"]) for n in notifs["items"]]
    check("alice notified of bob's contribution",
          ("contribute", f"contributed a Story: Bob's story") in kinds, f"{kinds}")
    check("alice notified of bob's comment",
          any(t == "comment" and "commented on your future" in x
              for t, x in kinds))
    check("alice notified of bob's branch",
          any(t == "branch" and "branched off your future" in x
              for t, x in kinds))
    check("notifications envelope has unread", notifs["unread"] >= 3)

    # alice replies to bob's comment -> bob gets a reply notification
    alice_before = len(c.get("/api/notifications").json()["items"])
    r = c.post_json("/api/comment", future_id=target,
                    body="alice replies to bob", parent_id=bob_cm["id"])
    check("reply accepted", r.status == 200)
    replies = c.get(f"/api/futures/{target}/comments").json()["items"]
    check("reply stored with parent_id",
          any(x["parent_id"] == bob_cm["id"] and x["author"] == "alice"
              for x in replies))
    bn = b.get("/api/notifications").json()
    check("bob notified of the reply",
          any(n["type"] == "reply" and "replied to your comment" in n["text"]
              for n in bn["items"]))
    # alice is both the replier and the seed creator -> nothing for herself
    an = c.get("/api/notifications").json()
    check("no self-notification for the creator's reply",
          len(an["items"]) == alice_before,
          f"{alice_before} -> {len(an['items'])}")
    # bob replies to his own comment -> nobody new notified
    bob_before = len(b.get("/api/notifications").json()["items"])
    r = b.post_json("/api/comment", future_id=target, body="bob self-reply",
                    parent_id=bob_cm["id"])
    bob_after = len(b.get("/api/notifications").json()["items"])
    check("self-reply creates no notification for bob", bob_before == bob_after)

    r = b.get("/api/notifications/read")
    check("legacy read endpoint", r.status == 200 and r.json()["ok"] is True)
    check("unread drops to 0 after read",
          b.get("/api/notifications").json()["unread"] == 0)

    # -- 11. Input caps ---------------------------------------------------------------
    r = c.post_json("/api/future", title="x" * 501, body="y")
    check("501-char title -> 400", r.status == 400 and "500" in r.json()["error"])
    r = c.post_json("/api/contribute", future_id=target, type="people",
                    title="y" * 201, body="y")
    check("201-char contribution title -> 400", r.status == 400
          and "200" in r.json()["error"])
    r = c.post_json("/api/comment", future_id=target, body="z" * 5001)
    check("5001-char comment -> 400", r.status == 400
          and "5000" in r.json()["error"])

    # -- 12. Misc reads -----------------------------------------------------------------
    r = c.get("/api/users/alice").json()
    check("user endpoint: stats", r["ok"] and r["registered"] is True
          and r["stats"]["futures"] >= 14 and r["stats"]["contributions"] >= 1)
    check("user endpoint: recent futures listed",
          len(r["recent_futures"]) >= 10)
    r = c.get("/api/users/whoami_not_a_user")
    check("unknown user -> 404", r.status == 404)
    r = c.get("/api/feed?limit=10").json()
    check("feed returns items with kind", len(r["items"]) == 10
          and all("kind" in x for x in r["items"]))

    # -- 13. Security headers -------------------------------------------------------------
    r = c.get("/")
    h = {k.lower(): v for k, v in r.headers}
    check("nosniff header", h.get("x-content-type-options") == "nosniff")
    check("frame deny header", h.get("x-frame-options") == "DENY")
    check("referrer policy header", h.get("referrer-policy") ==
          "strict-origin-when-cross-origin")
    check("CSP header", "default-src 'self'" in h.get("content-security-policy", ""))

    # -- 14. Rate limit (LAST — burns the per-IP POST budget) ------------------------------
    limited_at = None
    for i in range(130):
        r = c.post_json("/api/future", title="")  # cheap 400, no DB write
        if r.status == 429:
            limited_at = i + 1
            break
    check("POST flood gets 429", limited_at is not None,
          f"never limited in 130 posts")
    if limited_at:
        check("429 body is JSON", r.json()["ok"] is False
              and "slow down" in r.json()["error"])
    check("GETs still served while POST-limited",
          c.get("/api/health").status == 200)

    code = finish()
finally:
    server.stop()
sys.exit(code)
