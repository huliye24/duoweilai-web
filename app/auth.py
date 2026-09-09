"""Auth: passwords, sessions, cookies, CSRF, login gate.

The v0.5 account flow is ported unchanged: username + password (pbkdf2),
30-day session cookies (`duoweilai_session`), email-based password reset.
New in the Flask build: double-submit-cookie CSRF on every POST.
"""
import functools
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from flask import g, jsonify, render_template, request
from .db import get_db, SESSION_MAX_AGE_DAYS, RESET_MAX_AGE_HOURS
from .services import now_iso

SESSION_COOKIE = "duoweilai_session"
CSRF_COOKIE = "duoweilai_csrf"
SESSION_MAX_AGE = SESSION_MAX_AGE_DAYS * 86400  # 30 days, seconds

_USERNAME_RE = re.compile(r"[A-Za-z0-9_]+")


# -------------------------------------------------
# Passwords & accounts (ported from v0.5)
# -------------------------------------------------
def hash_password(password):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100000)
    return f"{salt}${dk.hex()}"


def verify_password(password, stored):
    try:
        salt, hx = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100000)
        return secrets.compare_digest(dk.hex(), hx)
    except ValueError:
        return False


def valid_username(u):
    return bool(u) and 3 <= len(u) <= 20 and _USERNAME_RE.fullmatch(u)


def valid_email(e):
    return bool(e) and "@" in e and "." in e.split("@")[-1] and len(e) <= 254


def create_user(username, password, email=None):
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (username, password_hash, email, created_at) VALUES (?,?,?,?)",
            (username, hash_password(password), email, now_iso()))
        db.commit()
        return cur.lastrowid
    except Exception:  # sqlite3.IntegrityError (imported lazily to avoid a cycle)
        db.rollback()
        return None


def authenticate(username, password):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return row["id"] if row and verify_password(password, row["password_hash"]) else None


def create_session(user_id):
    token = secrets.token_hex(32)
    db = get_db()
    db.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
               (token, user_id, now_iso()))
    db.commit()
    return token


def get_user_by_session(token):
    if not token:
        return None
    db = get_db()
    return db.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
        (token,)).fetchone()


def delete_session(token):
    if not token:
        return
    db = get_db()
    db.execute("DELETE FROM sessions WHERE token=?", (token,))
    db.commit()


def get_user_by_id(uid):
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def get_user_by_username(username):
    return get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def get_user_by_email(email):
    return get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()


def create_password_reset(user_id):
    token = secrets.token_hex(24)
    expires = (datetime.now(timezone.utc) + timedelta(hours=RESET_MAX_AGE_HOURS)).isoformat()
    db = get_db()
    db.execute("DELETE FROM password_resets WHERE user_id=?", (user_id,))
    db.execute("INSERT INTO password_resets (user_id, token, expires_at) VALUES (?,?,?)",
               (user_id, token, expires))
    db.commit()
    return token


def get_password_reset(token):
    """Return the user row for a valid, unexpired reset token, else None."""
    db = get_db()
    row = db.execute("SELECT * FROM password_resets WHERE token=? AND expires_at>?",
                     (token, now_iso())).fetchone()
    return get_user_by_id(row["user_id"]) if row else None


def consume_password_reset(token, new_password):
    user = get_password_reset(token)
    if not user:
        return False
    db = get_db()
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (hash_password(new_password), user["id"]))
    db.execute("DELETE FROM password_resets WHERE token=?", (token,))
    db.commit()
    return True


# -------------------------------------------------
# Request classification (form vs JSON client)
# -------------------------------------------------
def is_json_request():
    """A request is treated as a JSON client when it posts JSON.
    Form posts keep getting redirects/rendered pages (v0.5 behavior)."""
    return request.is_json


# -------------------------------------------------
# Current user (before_request hook)
# -------------------------------------------------
def load_user():
    token = request.cookies.get(SESSION_COOKIE)
    g.user = get_user_by_session(token) if token else None


def sign_in(user_id):
    """Create a session; the cookie is attached by apply_session_cookie."""
    g._set_session = create_session(user_id)


def sign_out():
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(token)
    g._clear_session = True


def login_required(view):
    """Gate for write endpoints. JSON clients get 401; form posts get the
    friendly 'Sign in to continue' page (v0.5 behavior, 200)."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user"):
            return view(*args, **kwargs)
        if is_json_request():
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        return render_template("need_login.html")
    return wrapped


# -------------------------------------------------
# CSRF — double-submit cookie
# -------------------------------------------------
def ensure_csrf():
    """before_request hook: reuse the browser's token or mint a fresh one."""
    token = request.cookies.get(CSRF_COOKIE)
    if token and len(token) == 64:
        g._csrf_token, g._csrf_new = token, False
    else:
        g._csrf_token, g._csrf_new = secrets.token_hex(32), True


def csrf_token():
    """Template global. Also exposed to JS via <meta name="csrf-token">."""
    if "_csrf_token" not in g:
        ensure_csrf()
    return g._csrf_token


def verify_csrf():
    """before_request hook for POSTs: token must arrive back via the
    X-CSRF-Token header, the `csrf` form field, or a `csrf` JSON field."""
    if request.method != "POST":
        return None
    sent = (request.headers.get("X-CSRF-Token", "")
            or request.form.get("csrf", "")
            or (request.get_json(silent=True) or {}).get("csrf", ""))
    if sent and secrets.compare_digest(sent, g.get("_csrf_token", "")):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Invalid or missing CSRF token."}), 403
    return render_template("error.html", title="403",
                           message="Invalid or missing CSRF token."), 403


def set_csrf_cookie(resp):
    """after_request hook: only writes when a fresh token was minted.
    Not httponly on purpose — the fetch() wrapper reads it from the meta
    tag, and having it readable keeps debugging simple."""
    from flask import current_app
    if g.get("_csrf_new"):
        resp.set_cookie(CSRF_COOKIE, g._csrf_token, max_age=SESSION_MAX_AGE,
                        httponly=False, samesite="Lax",
                        secure=current_app.config["SECURE_COOKIE"])
    return resp


def apply_session_cookie(resp):
    """after_request hook: attach the session cookie set by sign_in(),
    or clear it after sign_out()."""
    from flask import current_app
    tok = g.pop("_set_session", None)
    if tok is not None:
        resp.set_cookie(SESSION_COOKIE, tok, max_age=SESSION_MAX_AGE,
                        httponly=True, samesite="Lax",
                        secure=current_app.config["SECURE_COOKIE"])
    if g.pop("_clear_session", False):
        resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
