"""Page routes (HTML). All /api/* endpoints live in app.api.

Markup matches v0.5 (same classes, same text) — it just comes from Jinja
templates now. Page titles match v0.5's page() calls: Home, Explore,
the seed's own title, the username, and so on.
"""
import re
from urllib.parse import urlencode

from flask import Blueprint, g, redirect, render_template, request

from . import auth
from .services import (get_child_branches, get_comments, get_contributions,
                       get_contributions_by_creator, get_creator_stats,
                       get_future_by_short, get_futures_by_creator,
                       get_notifications, inc_views, list_futures,
                       mark_notifications_read, search_futures)

web = Blueprint("web", __name__)

# Chip order matches v0.5's explore page: All first, Unknown last.
EXPLORE_CATS = ["All", "Life", "Cities", "Education", "Culture",
                "Relationships", "Work", "Civilization", "Technology",
                "Unknown"]

PER_PAGE = 12

# Seed/world page sections: type key -> (plural label, anchor id, icon).
# (v0.5 said "Peoples"/"Storys" and linked to broken #peoples/#storys
# anchors — fixed here.)
TYPE_SECTIONS = {
    "people": ("People", "people", "◎"),
    "place": ("Places", "places", "◇"),
    "story": ("Stories", "stories", "▣"),
    "rule": ("Rules", "rules", "◈"),
    "object": ("Objects", "objects", "○"),
    "branch": ("Branches", "branches", "↗"),
}

_TOKEN_RE = re.compile(r"[A-Fa-f0-9]+")


def _not_found(title, message):
    return render_template("error.html", title=title, message=message), 404


def _group_contributions(contribs):
    """Group rows by type, in the fixed section order.
    Returns (groups dict, ordered [(type, plural label, rows)])."""
    groups = {}
    for c in contribs:
        groups.setdefault(c["type"], []).append(c)
    ordered = [(t, info[0], groups[t])
               for t, info in TYPE_SECTIONS.items() if t in groups]
    return groups, ordered


# -------------------------------------------------
# Home & Explore
# -------------------------------------------------
@web.route("/")
def home():
    # Guests tour the world first — no composer on their home, so give
    # them a fuller wall of seeds to walk into.
    return render_template("home.html", title="Home",
                           futures=list_futures(6 if g.user else 12))


@web.route("/explore")
def explore():
    q = (request.args.get("q") or "").strip()[:100]
    cat = request.args.get("cat") or "All"
    if cat not in EXPLORE_CATS:
        cat = "All"
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    rows, total = search_futures(page, PER_PAGE, category=cat, q=q or None)
    pages = max(1, -(-total // PER_PAGE))
    if page > pages:  # e.g. /explore?page=999 — land on the last real page
        page = pages
        rows, total = search_futures(page, PER_PAGE, category=cat, q=q or None)

    def page_url(p):
        params = {}
        if cat != "All":
            params["cat"] = cat
        if q:
            params["q"] = q
        if p > 1:
            params["page"] = p
        return "/explore" + ("?" + urlencode(params) if params else "")

    chips = []
    for c in EXPLORE_CATS:
        params = {}
        if c != "All":
            params["cat"] = c
        if q:
            params["q"] = q
        chips.append({
            "label": c,
            "url": "/explore" + ("?" + urlencode(params) if params else ""),
            "active": c == cat,
        })

    return render_template(
        "explore.html", title="Explore", futures=rows, page=page, pages=pages,
        total=total, cat=cat, q=q, chips=chips,
        filtered=bool(q or cat != "All"),
        prev_url=page_url(page - 1) if page > 1 else None,
        next_url=page_url(page + 1) if page < pages else None)


# -------------------------------------------------
# Auth pages (forms POST to /api/*)
# -------------------------------------------------
@web.route("/login")
def login_page():
    if g.get("user"):
        return redirect("/")
    return render_template("login.html", title="Sign in", form={})


@web.route("/register")
def register_page():
    if g.get("user"):
        return redirect("/")
    return render_template("register.html", title="Register", form={})


@web.route("/welcome")
def welcome():
    """Post-registration reveal of the system-assigned ID (QQ-number moment)."""
    sys_id = request.args.get("id", "") or (g.user["username"] if g.get("user") else "")
    return render_template("welcome.html", title="Welcome", sys_id=sys_id)


@web.route("/forgot")
def forgot_page():
    if g.get("user"):
        return redirect("/")
    return render_template("forgot.html", title="Forgot password")


@web.route("/reset/<token>")
def reset_page(token):
    if not token or not _TOKEN_RE.fullmatch(token):
        return _not_found("Not Found", "This reset link is invalid.")
    return render_template("reset.html", title="Reset password", token=token)


@web.route("/logout")
def logout():
    auth.sign_out()
    return redirect("/")


# -------------------------------------------------
# Notifications
# -------------------------------------------------
@web.route("/notifications")
def notifications():
    if not g.get("user"):
        return redirect("/login")
    uid = g.user["id"]
    notifs = get_notifications(uid)  # fetch first, then mark read
    mark_notifications_read(uid)
    return render_template("notifications.html", title="Notifications",
                           notifs=notifs)


# -------------------------------------------------
# Seed page
# -------------------------------------------------
@web.route("/f/<short>")
def seed(short):
    f = get_future_by_short(short)
    if not f:
        return _not_found("Not Found", "This seed doesn't exist.")
    inc_views(short)
    contribs = get_contributions(f["id"])
    comments = get_comments(f["id"])
    groups, ordered_groups = _group_contributions(contribs)

    parent = get_future_by_short(f["parent_short_id"]) if f["parent_short_id"] else None
    can_edit_seed = bool(g.get("user") and g.user["id"] == f["creator_id"])

    # Comments flattened pre-order with a depth key — v0.5 rendered replies
    # as siblings anyway, so this produces the same markup without recursion
    # in the template.
    replies = {}
    for cm in comments:
        if cm["parent_id"]:
            replies.setdefault(cm["parent_id"], []).append(cm)
    flat = []

    def walk(cm, depth):
        item = dict(cm)
        item["depth"] = depth
        flat.append(item)
        for r in replies.get(cm["id"], []):
            walk(r, depth + 1)

    for cm in comments:
        if not cm["parent_id"]:
            walk(cm, 0)

    return render_template(
        "seed.html", title=f["title"], f=f, parent=parent, groups=groups,
        ordered_groups=ordered_groups, n_contribs=len(contribs),
        n_comments=len(comments), child_branches=get_child_branches(short, 5),
        flat_comments=flat, can_edit_seed=can_edit_seed)


# -------------------------------------------------
# World page
# -------------------------------------------------
@web.route("/world/<short>")
def world(short):
    f = get_future_by_short(short)
    if not f:
        return _not_found("Not Found", "World not found.")
    contribs = get_contributions(f["id"])
    _, ordered_groups = _group_contributions(contribs)

    timeline_contribs = sorted(contribs, key=lambda c: c["created_at"])
    contributors = []
    for c in contribs:
        if c["creator"] not in contributors:
            contributors.append(c["creator"])

    return render_template(
        "world.html", title=f["title"], f=f, ordered_groups=ordered_groups,
        n_contribs=len(contribs), timeline_contribs=timeline_contribs,
        contributors=contributors)


# -------------------------------------------------
# Person page
# -------------------------------------------------
@web.route("/person/<username>")
def person(username):
    started, contributions_count, worlds_count = get_creator_stats(username)
    futures = get_futures_by_creator(username)
    total_branches = sum(fu["branches"] for fu in futures)
    worlds = [dict(fu, ccount=len(get_contributions(fu["id"])))
              for fu in futures if fu["is_world"]]
    recent_contribs = get_contributions_by_creator(username, limit=10)

    return render_template(
        "person.html", title=username, username=username, started=started,
        worlds_count=worlds_count, total_branches=total_branches,
        contributions_count=contributions_count, futures=futures,
        worlds=worlds, recent_contribs=recent_contribs)
