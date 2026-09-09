"""Auth: passwords, sessions, cookies, CSRF, login gate.

Accounts are QQ-style: registration takes only an email and a password,
and the system assigns a numeric Duoweilai ID (stored as the username —
"100001" and so on, sequential from 100000). Sign in with the ID or the
email. Pretty numbers (靓号) are held back from auto-assignment and can be
handed out deliberately via `python server.py adduser`.

Ported from v0.5: pbkdf2 passwords, 30-day session cookies
(`duoweilai_session`), email-based password reset. New in the Flask
build: double-submit-cookie CSRF on every POST.
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

# System IDs start here — 6 digits, low numbers mean early members (QQ-style).
ID_BASE = 100000


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


def is_premium_id(n):
    """靓号 heuristics: pretty numbers never auto-assigned — they're held
    back for the operator to hand out (server.py adduser). Loose on
    purpose; skipping a plain number costs nothing."""
    s = str(n)
    if len(set(s)) == 1:                              # 888888 — all same digit
        return True
    if s.endswith("000"):                             # 100000, 888000 — round
        return True
    if any(d * 4 in s for d in "0123456789"):         # 166666 — 4 in a row
        return True
    if len(s) >= 4:
        a, b, c, d = s[-4:]
        if a != d and (a == b and c == d              # AABB tail (…8866)
                       or a == c and b == d):         # ABAB tail (…6868)
            return True
    pairs = list(zip(s, s[1:]))
    if all(int(b) - int(a) == 1 for a, b in pairs):   # 123456 — ascending
        return True
    return all(int(a) - int(b) == 1 for a, b in pairs)  # 654321 — descending


def next_system_id():
    """Smallest unassigned ID above the current maximum, skipping 靓号."""
    db = get_db()
    row = db.execute(
        "SELECT MAX(CAST(username AS INTEGER)) AS maxid FROM users "
        "WHERE username GLOB '[0-9]*'").fetchone()
    n = max(ID_BASE - 1, row["maxid"] or 0)
    while True:
        n += 1
        if not is_premium_id(n):
            return str(n)


def register_with_system_id(email, password, attempts=3):
    """Create an account with a system-assigned ID (the username IS the
    ID, like a QQ number). Returns the users.id, or None on failure —
    the retry handles the rare race where two workers computed the same
    next ID (UNIQUE(username) rejects the loser)."""
    for _ in range(attempts):
        sysid = next_system_id()
        rowid = create_user(sysid, password, email)
        if rowid:
            return rowid
    return None


def authenticate(identifier, password):
    """Sign in by system ID, email, or legacy v0.5 username."""
    db = get_db()
    if "@" in identifier:
        row = get_user_by_email(identifier)
    else:
        row = get_user_by_username(identifier)
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
