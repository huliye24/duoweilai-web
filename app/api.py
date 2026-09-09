"""All /api/* routes: the v0.5 form endpoints ported, plus the new JSON API.

Content negotiation: JSON POSTs get JSON envelopes; form POSTs keep the
v0.5 behavior (302 redirects or re-rendered pages). Validation errors on
content endpoints are always JSON — same as v0.5. Deletes and edits always
answer JSON; they're called from fetch().
"""
import math
from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request
from . import auth, services
from .auth import is_json_request, login_required
from .security import MAX_BODY, MAX_COMMENT, MAX_CONTRIB_TITLE, MAX_TITLE

api = Blueprint("api", __name__, url_prefix="/api")


# -------------------------------------------------
# Request helpers
# -------------------------------------------------
def form_payload():
    return request.get_json(silent=True) or request.form


def form_value(key):
    """Read a field from either a JSON or urlencoded POST, stripped."""
    v = form_payload().get(key)
    return str(v).strip() if v is not None else ""


def respond(payload, redirect_to=None, status=200):
    """Success path: JSON clients get an envelope, form posts get a 302."""
    if is_json_request():
        body = dict(payload)
        if redirect_to:
            body.setdefault("redirect", redirect_to)
        return jsonify(body), status
    return redirect(redirect_to or "/")


def auth_error(template, err, form=None):
    """Auth form errors: re-render the page (v0.5 did 200 + HTML);
    JSON clients get a 400 envelope."""
    if is_json_request():
        return jsonify({"ok": False, "error": err}), 400
    return render_template(template, err=err, form=form or {})


def json_error(msg, status):
    return jsonify({"ok": False, "error": msg}), status


# -------------------------------------------------
# Auth endpoints (ported from v0.5, exact error strings)
# -------------------------------------------------
@api.route("/register", methods=["POST"])
def register():
    username, email, password = (form_value("username"),
                                  form_value("email"),
                                  form_value("password"))
    form = {"username": username, "email": email}
    if not auth.valid_username(username):
        return auth_error("register.html", "ID must be 3–20 letters, digits, or underscore.", form)
    if not auth.valid_email(email):
        return auth_error("register.html", "Please enter a valid email.", form)
    if len(password) < 6:
        return auth_error("register.html", "Password must be at least 6 characters.", form)
    if auth.get_user_by_username(username):
        return auth_error("register.html", "That ID is already taken — pick another.", form)
    if auth.get_user_by_email(email):
        return auth_error("register.html",
                          "That email is already registered. Try signing in or using a different email.", form)
    uid = auth.create_user(username, password, email)
    if not uid:
        return auth_error("register.html", "Could not create account — please try a different ID or email.", form)
    services.add_notification(uid, uid, "welcome", None,
                              f"Welcome to Duoweilai, {username}!", force=True)
    auth.sign_in(uid)
    return respond({"ok": True}, "/")


@api.route("/login", methods=["POST"])
def login():
    username, password = form_value("username"), form_value("password")
    form = {"username": username}
    if not username or not password:
        return auth_error("login.html", "Enter your ID and password.", form)
    uid = auth.authenticate(username, password)
    if not uid:
        return auth_error("login.html", "ID or password is incorrect.", form)
    auth.sign_in(uid)
    return respond({"ok": True}, "/")


@api.route("/logout", methods=["POST"])
def logout():
    auth.sign_out()
    if is_json_request():
        return jsonify({"ok": True})
    return redirect("/")


@api.route("/forgot", methods=["POST"])
def forgot():
    email = form_value("email")
    if not email:
        if is_json_request():
            return json_error("Please enter your email.", 400)
        return render_template("forgot.html", err="Please enter your email.")
    target = auth.get_user_by_email(email)
    if target:
        token = auth.create_password_reset(target["id"])
        services.log_password_reset(target, f"/reset/{token}")
    # Always report success — never reveal whether an account exists.
    if is_json_request():
        return jsonify({"ok": True, "message": "Check your inbox."})
    return render_template("forgot.html", sent_to=email)


@api.route("/reset/<token>", methods=["POST"])
def reset_with_token(token):
    return _do_reset(token)


@api.route("/reset", methods=["POST"])
def reset():
    return _do_reset(form_value("token"))


def _do_reset(token):
    password = form_value("password")
    if len(password) < 6:
        return _reset_error(token, "Password must be at least 6 characters.")
    if not auth.get_password_reset(token):
        return _reset_error(token, "This reset link is invalid or has expired.")
    auth.consume_password_reset(token, password)
    if is_json_request():
        return jsonify({"ok": True, "message": "Password updated"})
    return render_template("reset_done.html")


def _reset_error(token, err):
    if is_json_request():
        return json_error(err, 400)
    return render_template("reset.html", token=token, err=err)


# -------------------------------------------------
# Content endpoints — write
# -------------------------------------------------
@api.route("/future", methods=["POST"])
@login_required
def create_seed():
    title, body = form_value("title"), form_value("body")
    category = services.normalize_category(form_value("category"))
    parent_short = form_value("parent")

    if not title:
        return json_error("Title required", 400)
    if len(title) > MAX_TITLE:
        return json_error(f"Title must be {MAX_TITLE} characters or fewer.", 400)
    if len(body) > MAX_BODY:
        return json_error(f"Body must be {MAX_BODY} characters or fewer.", 400)

    parent = None
    if parent_short:
        parent = services.get_future_by_short(parent_short)
        if not parent:
            return json_error("Parent seed not found", 404)

    short = services.create_future(title, body, g.user["username"], g.user["id"],
                                   category=category, parent_short_id=parent_short or None)
    if not short:
        return json_error("Could not create seed — please retry.", 500)
    if parent and parent["creator_id"] and parent["creator_id"] != g.user["id"]:
        services.add_notification(parent["creator_id"], g.user["id"], "branch", short,
                                  "branched off your future")
    return respond({"ok": True, "short": short}, f"/f/{short}")


@api.route("/contribute", methods=["POST"])
@login_required
def contribute():
    future_id, ctype, title, body = (form_value("future_id"), form_value("type"),
                                     form_value("title"), form_value("body"))
    if ctype not in services.TYPE_EN:
        return json_error("Invalid type", 400)
    if not title:
        return json_error("Title required", 400)
    if len(title) > MAX_CONTRIB_TITLE:
        return json_error(f"Title must be {MAX_CONTRIB_TITLE} characters or fewer.", 400)
    if len(body) > MAX_BODY:
        return json_error(f"Body must be {MAX_BODY} characters or fewer.", 400)
    target = services.get_future_by_short(future_id)
    if not target:
        return json_error("Future not found", 404)
    services.add_contribution(target["id"], ctype, title, body,
                              g.user["username"], g.user["id"])
    services.maybe_make_world(future_id)
    if target["creator_id"] and target["creator_id"] != g.user["id"]:
        t = services.TYPE_EN.get(ctype, ctype)
        services.add_notification(target["creator_id"], g.user["id"], "contribute", future_id,
                                  f"contributed a {t}: {title}")
    return respond({"ok": True}, f"/f/{future_id}")


@api.route("/comment", methods=["POST"])
@login_required
def comment():
    future_id, body = form_value("future_id"), form_value("body")
    parent_raw = form_value("parent_id")
    if not body:
        return json_error("Comment body required", 400)
    if len(body) > MAX_COMMENT:
        return json_error(f"Comment must be {MAX_COMMENT} characters or fewer.", 400)
    target = services.get_future_by_short(future_id)
    if not target:
        return json_error("Future not found", 404)
    parent_id = None
    if parent_raw:
        try:
            parent_id = int(parent_raw)
        except ValueError:
            return json_error("Invalid parent", 400)
    services.add_comment(target["id"], None, parent_id, g.user["id"], body)
    if target["creator_id"] and target["creator_id"] != g.user["id"]:
        services.add_notification(target["creator_id"], g.user["id"], "comment", future_id,
                                  "commented on your future")
    # Replies also notify the parent comment's author (new) — skipping
    # self and the seed creator, who already got the notification above.
    if parent_id:
        parent_cm = services.get_comment(parent_id)
        if (parent_cm and parent_cm["author_id"] != g.user["id"]
                and parent_cm["author_id"] != target["creator_id"]):
            services.add_notification(parent_cm["author_id"], g.user["id"], "reply", future_id,
                                      "replied to your comment")
    return respond({"ok": True}, f"/f/{future_id}")


# -------------------------------------------------
# Deletes (owner-checked, always JSON)
# -------------------------------------------------
@api.route("/future/<short>/delete", methods=["POST"])
@login_required
def delete_seed(short):
    target = services.get_future_by_short(short)
    if not target:
        return json_error("Not found", 404)
    if target["creator_id"] != g.user["id"]:
        return json_error("Only the seed creator can delete it", 403)
    services.delete_future(short)
    return jsonify({"ok": True, "redirect": "/"})


@api.route("/contribution/<int:cid>/delete", methods=["POST"])
@login_required
def delete_contribution(cid):
    owner = services.get_contribution_author(cid)
    if not owner:
        return json_error("Not found", 404)
    if owner["author_id"] != g.user["id"]:
        return json_error("Only the author can delete this", 403)
    short = services.delete_contribution(cid)
    return jsonify({"ok": True, "redirect": f"/f/{short}" if short else "/"})


@api.route("/comment/<int:cid>/delete", methods=["POST"])
@login_required
def delete_comment(cid):
    owner = services.get_comment_author(cid)
    if not owner:
        return json_error("Not found", 404)
    if owner["author_id"] != g.user["id"]:
        return json_error("Only the author can delete this", 403)
    services.delete_comment(cid)
    return jsonify({"ok": True})


# -------------------------------------------------
# Edits (new — owner-checked, always JSON for the AJAX panels)
# -------------------------------------------------
@api.route("/future/<short>/edit", methods=["POST"])
@login_required
def edit_seed(short):
    target = services.get_future_by_short(short)
    if not target:
        return json_error("Not found", 404)
    if target["creator_id"] != g.user["id"]:
        return json_error("Only the seed creator can edit it", 403)
    title, body = form_value("title"), form_value("body")
    category = services.normalize_category(form_value("category") or target["category"])
    if not title:
        return json_error("Title required", 400)
    if len(title) > MAX_TITLE:
        return json_error(f"Title must be {MAX_TITLE} characters or fewer.", 400)
    if len(body) > MAX_BODY:
        return json_error(f"Body must be {MAX_BODY} characters or fewer.", 400)
    services.edit_future(short, title, body, category)
    return jsonify({"ok": True, "redirect": f"/f/{short}"})


@api.route("/contribution/<int:cid>/edit", methods=["POST"])
@login_required
def edit_contribution(cid):
    target = services.get_contribution(cid)
    if not target:
        return json_error("Not found", 404)
    if target["author_id"] != g.user["id"]:
        return json_error("Only the author can edit this", 403)
    title, body = form_value("title"), form_value("body")
    if not title:
        return json_error("Title required", 400)
    if len(title) > MAX_CONTRIB_TITLE:
        return json_error(f"Title must be {MAX_CONTRIB_TITLE} characters or fewer.", 400)
    if len(body) > MAX_BODY:
        return json_error(f"Body must be {MAX_BODY} characters or fewer.", 400)
    services.edit_contribution(cid, title, body)
    return jsonify({"ok": True, "redirect": f"/f/{target['future_id']}"})


@api.route("/comment/<int:cid>/edit", methods=["POST"])
@login_required
def edit_comment(cid):
    target = services.get_comment(cid)
    if not target:
        return json_error("Not found", 404)
    if target["author_id"] != g.user["id"]:
        return json_error("Only the author can edit this", 403)
    body = form_value("body")
    if not body:
        return json_error("Comment body required", 400)
    if len(body) > MAX_COMMENT:
        return json_error(f"Comment must be {MAX_COMMENT} characters or fewer.", 400)
    services.edit_comment(cid, body)
    return jsonify({"ok": True})


# -------------------------------------------------
# JSON read API (new)
# -------------------------------------------------
def future_dict(f):
    return {"short_id": f["short_id"], "title": f["title"], "body": f["body"],
            "creator": f["creator"], "created_at": f["created_at"],
            "category": f["category"] or "Unknown", "branches": f["branches"],
            "views": f["views"], "is_world": bool(f["is_world"]),
            "parent_short_id": f["parent_short_id"], "edited_at": f["edited_at"],
            "when": services.rel_time(f["created_at"])}


def contribution_dict(c):
    return {"id": c["id"], "type": c["type"], "title": c["title"], "body": c["body"],
            "creator": c["creator"], "created_at": c["created_at"],
            "edited_at": c["edited_at"], "when": services.rel_time(c["created_at"])}


def comment_dict(c):
    return {"id": c["id"], "parent_id": c["parent_id"], "author": c["username"] or "Anonymous",
            "body": c["body"], "created_at": c["created_at"], "edited_at": c["edited_at"],
            "when": services.rel_time(c["created_at"])}


def notif_dict(n):
    return {"id": n["id"], "type": n["type"], "actor": n["actor_name"] or "someone",
            "text": n["text"], "future_short_id": n["future_short_id"],
            "is_read": bool(n["is_read"]), "created_at": n["created_at"],
            "when": services.rel_time(n["created_at"])}


def _int_arg(name, default, lo, hi):
    try:
        return min(hi, max(lo, int(request.args.get(name, default))))
    except (TypeError, ValueError):
        return default


@api.route("/health")
def health():
    return jsonify({"ok": True, "version": current_app.config["VERSION"],
                    "db": str(current_app.config["DB_PATH"])})


@api.route("/futures")
def api_futures():
    page = _int_arg("page", 1, 1, 100000)
    per_page = _int_arg("per_page", 12, 1, 100)
    category = request.args.get("cat") or None
    q = (request.args.get("q") or "").strip() or None
    rows, total = services.search_futures(page, per_page, category, q)
    return jsonify({"ok": True, "items": [future_dict(f) for f in rows],
                    "page": page, "per_page": per_page, "total": total,
                    "pages": math.ceil(total / per_page) if total else 0})


@api.route("/futures/<short>")
def api_future_detail(short):
    f = services.get_future_by_short(short)
    if not f:
        return json_error("Not found", 404)
    return jsonify({"ok": True, "future": future_dict(f),
                    "contributions": [contribution_dict(c)
                                      for c in services.get_contributions(f["id"])],
                    "comments": [comment_dict(c) for c in services.get_comments(f["id"])],
                    "child_branches": [future_dict(b)
                                       for b in services.get_child_branches(short, 20)]})


@api.route("/futures/<short>/contributions")
def api_future_contributions(short):
    f = services.get_future_by_short(short)
    if not f:
        return json_error("Not found", 404)
    ctype = request.args.get("type")
    if ctype and ctype not in services.TYPE_EN:
        return json_error("Invalid type", 400)
    rows = services.get_contributions(f["id"])
    if ctype:
        rows = [c for c in rows if c["type"] == ctype]
    return jsonify({"ok": True, "items": [contribution_dict(c) for c in rows],
                    "total": len(rows)})


@api.route("/futures/<short>/comments")
def api_future_comments(short):
    f = services.get_future_by_short(short)
    if not f:
        return json_error("Not found", 404)
    rows = services.get_comments(f["id"])
    return jsonify({"ok": True, "items": [comment_dict(c) for c in rows],
                    "total": len(rows)})


@api.route("/notifications")
def api_notifications():
    if not g.user:
        return json_error("Sign in required", 401)
    rows = services.get_notifications(g.user["id"])
    return jsonify({"ok": True, "unread": services.unread_count(g.user["id"]),
                    "items": [notif_dict(n) for n in rows]})


@api.route("/users/<username>")
def api_user(username):
    user = auth.get_user_by_username(username)
    started, contribs, worlds = services.get_creator_stats(username)
    if not user and not started and not contribs:
        return json_error("No such user", 404)
    futures = services.get_futures_by_creator(username)
    return jsonify({"ok": True, "username": username, "registered": bool(user),
                    "stats": {"futures": started, "contributions": contribs,
                              "worlds": worlds},
                    "recent_futures": [future_dict(f) for f in futures[:10]]})


@api.route("/feed")
def api_feed():
    limit = _int_arg("limit", 30, 1, 100)
    return jsonify({"ok": True, "items": services.get_feed(limit)})


# Legacy v0.5 endpoint: the bell marks notifications read on click.
@api.route("/notifications/read")
def notifications_read():
    if g.user:
        services.mark_notifications_read(g.user["id"])
    return jsonify({"ok": True})
