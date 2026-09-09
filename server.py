#!/usr/bin/env python3
"""
Duoweilai — Web (v0.5)
Core loop: Publish a Future Seed → Permanent link → Explore → Grow together → Become a World
Redesigned with v0.1 prototype UI language · English-first · Overseas market
New in v0.5: Real user accounts (ID + password, no phone), email-based password reset
"""
import sqlite3, json, os, uuid, random, re, hashlib, secrets
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote, quote
from datetime import datetime, timezone
from pathlib import Path
from http.cookies import SimpleCookie

# -------------------------------------------------
# Config
# -------------------------------------------------
PORT = int(os.environ.get("DUOWEILAI_PORT", "8080"))
BIND = os.environ.get("DUOWEILAI_BIND", "0.0.0.0")
SECURE_COOKIE = os.environ.get("DUOWEILAI_SECURE_COOKIE", "") == "1"
MAX_BODY = 64 * 1024
DB_PATH = Path(os.environ.get("DUOWEILAI_DB") or (Path(__file__).parent / "duoweilai.db"))

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def rel_time(iso):
    """English relative time labels."""
    try:
        t = datetime.fromisoformat(iso)
    except Exception:
        return iso
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - t
    s = int(delta.total_seconds())
    if s < 60:    return "just now"
    if s < 3600: return f"{s//60}m ago"
    if s < 86400: return f"{s//3600}h ago"
    if s < 86400*30: return f"{s//86400}d ago"
    return t.strftime("%d %b %Y")

# -------------------------------------------------
# Database
# -------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS futures (
            id TEXT PRIMARY KEY, short_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL, body TEXT NOT NULL,
            creator TEXT NOT NULL DEFAULT 'Anonymous', creator_id INTEGER,
            created_at TEXT NOT NULL, branches INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0, is_world INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, future_id TEXT NOT NULL,
            type TEXT NOT NULL, title TEXT NOT NULL, body TEXT,
            creator TEXT NOT NULL DEFAULT 'Anonymous', author_id INTEGER,
            created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, email TEXT UNIQUE,
            created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL, expires_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, future_id TEXT NOT NULL,
            contribution_id INTEGER, parent_id INTEGER, author_id INTEGER NOT NULL,
            body TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL, type TEXT NOT NULL,
            future_short_id TEXT, text TEXT NOT NULL,
            is_read INTEGER DEFAULT 0, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_cf ON contributions(future_id);
        CREATE INDEX IF NOT EXISTS idx_cm ON comments(future_id);
        CREATE INDEX IF NOT EXISTS idx_nu ON notifications(user_id);
    """)
    for ddl in [
        "ALTER TABLE futures ADD COLUMN creator_id INTEGER",
        "ALTER TABLE contributions ADD COLUMN author_id INTEGER",
        "ALTER TABLE futures ADD COLUMN category TEXT DEFAULT 'Unknown'",
        "ALTER TABLE users ADD COLUMN email TEXT UNIQUE",
        "ALTER TABLE users ADD COLUMN reset_token TEXT",
    ]:
        try: conn.execute(ddl)
        except sqlite3.OperationalError: pass
    conn.commit(); conn.close()

# -------------------------------------------------
# Auth
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

def create_user(username, password, email=None):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email, created_at) VALUES (?,?,?,?)",
            (username, hash_password(password), email, now_iso()))
        conn.commit(); conn.close()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close(); return None

def authenticate(username, password):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return row["id"] if row and verify_password(password, row["password_hash"]) else None

def create_session(user_id):
    token = secrets.token_hex(32)
    conn = get_db()
    conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
                 (token, user_id, now_iso()))
    conn.commit(); conn.close()
    return token

def get_user_by_session(token):
    if not token: return None
    conn = get_db()
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
        (token,)).fetchone()
    conn.close(); return row

def delete_session(token):
    if not token: return
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit(); conn.close()

def get_user_by_id(uid):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close(); return row

def get_user_by_username(username):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close(); return row

def get_user_by_email(email):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close(); return row

def create_password_reset(user_id):
    token = secrets.token_hex(24)
    from datetime import timedelta
    expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    conn = get_db()
    conn.execute("DELETE FROM password_resets WHERE user_id=?", (user_id,))
    conn.execute("INSERT INTO password_resets (user_id, token, expires_at) VALUES (?,?,?)",
                 (user_id, token, expires))
    conn.commit(); conn.close()
    return token

def get_password_reset(token):
    conn = get_db()
    row = conn.execute("SELECT * FROM password_resets WHERE token=? AND expires_at>?",
                       (token, now_iso())).fetchone()
    if row:
        user = get_user_by_id(row["user_id"])
    else:
        user = None
    conn.close(); return user

def consume_password_reset(token, new_password):
    user = get_password_reset(token)
    if not user: return False
    conn = get_db()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user["id"]))
    conn.execute("DELETE FROM password_resets WHERE token=?", (token,))
    conn.commit(); conn.close()
    return True

def ensure_default_user():
    """Legacy: kept for back-compat with the v0.4 auto-login build.
    No longer used — every visitor now has to register / sign in."""
    return create_user("explorer", "explore-duoweilai")

# -------------------------------------------------
# Business
# -------------------------------------------------
def gen_short_id():
    return "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5))

def create_future(title, body, creator, creator_id, category="Unknown"):
    short, fid = gen_short_id(), str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO futures (id,short_id,title,body,category,creator,creator_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (fid, short, title, body, category, creator, creator_id, now_iso()))
    conn.commit(); conn.close()
    return short

def get_future_by_short(short):
    conn = get_db()
    row = conn.execute("SELECT * FROM futures WHERE short_id=?", (short,)).fetchone()
    conn.close(); return row

def inc_views(short):
    conn = get_db()
    conn.execute("UPDATE futures SET views=views+1 WHERE short_id=?", (short,))
    conn.commit(); conn.close()

def list_futures(limit=100):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM futures ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close(); return rows

def get_contributions(future_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM contributions WHERE future_id=? ORDER BY created_at ASC",
        (future_id,)).fetchall()
    conn.close(); return rows

def get_contribution(cid):
    conn = get_db()
    row = conn.execute("SELECT * FROM contributions WHERE id=?", (cid,)).fetchone()
    conn.close(); return row

def add_contribution(future_id, ctype, title, body, creator, author_id):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO contributions (future_id,type,title,body,creator,author_id,created_at) VALUES (?,?,?,?,?,?,?)",
        (future_id, ctype, title, body, creator, author_id, now_iso()))
    conn.execute("UPDATE futures SET branches=branches+1 WHERE id=?", (future_id,))
    conn.commit(); conn.close()
    return cur.lastrowid

def maybe_make_world(short):
    conn = get_db()
    f = conn.execute("SELECT * FROM futures WHERE short_id=?", (short,)).fetchone()
    if not f: conn.close(); return
    cnt = conn.execute(
        "SELECT COUNT(*) FROM contributions WHERE future_id=?", (f["id"],)).fetchone()[0]
    if cnt >= 5 and not f["is_world"]:
        conn.execute("UPDATE futures SET is_world=1 WHERE id=?", (f["id"],))
    conn.commit(); conn.close()

def add_comment(future_id, contribution_id, parent_id, author_id, body):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO comments (future_id,contribution_id,parent_id,author_id,body,created_at) VALUES (?,?,?,?,?,?)",
        (future_id, contribution_id, parent_id, author_id, body, now_iso()))
    conn.commit(); conn.close()
    return cur.lastrowid

def get_comments(future_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT c.*, u.username FROM comments c LEFT JOIN users u ON u.id=c.author_id "
        "WHERE c.future_id=? ORDER BY c.created_at ASC", (future_id,)).fetchall()
    conn.close(); return rows

# ---- Delete helpers ----
def delete_future(short):
    """Owner-only seed deletion: removes the seed + all contributions/comments."""
    conn = get_db()
    f = conn.execute("SELECT id FROM futures WHERE short_id=?", (short,)).fetchone()
    if not f: conn.close(); return False
    fid = f["id"]
    conn.execute("DELETE FROM comments     WHERE future_id=?", (fid,))
    conn.execute("DELETE FROM contributions WHERE future_id=?", (fid,))
    conn.execute("DELETE FROM futures       WHERE id=?",       (fid,))
    conn.commit(); conn.close(); return True

def get_contribution_author(cid):
    conn = get_db()
    row = conn.execute(
        "SELECT c.author_id, c.future_id, f.short_id "
        "FROM contributions c JOIN futures f ON f.id=c.future_id "
        "WHERE c.id=?", (cid,)).fetchone()
    conn.close(); return row

def delete_contribution(cid):
    conn = get_db()
    row = conn.execute(
        "SELECT future_id FROM contributions WHERE id=?", (cid,)).fetchone()
    if not row: conn.close(); return None
    fid = row["future_id"]
    conn.execute("DELETE FROM contributions WHERE id=?", (cid,))
    conn.execute("UPDATE futures SET branches = MAX(0, branches-1) WHERE id=?", (fid,))
    short_row = conn.execute("SELECT short_id FROM futures WHERE id=?", (fid,)).fetchone()
    conn.commit(); conn.close()
    return short_row["short_id"] if short_row else None

def get_comment_author(cid):
    conn = get_db()
    row = conn.execute(
        "SELECT author_id FROM comments WHERE id=?", (cid,)).fetchone()
    conn.close(); return row

def delete_comment(cid):
    conn = get_db()
    # delete the comment + its replies
    conn.execute(
        "DELETE FROM comments WHERE id=? OR parent_id=?", (cid, cid))
    conn.commit(); conn.close()

def add_notification(user_id, actor_id, ntype, short, text):
    if user_id == actor_id: return
    conn = get_db()
    conn.execute(
        "INSERT INTO notifications (user_id,actor_id,type,future_short_id,text,created_at) VALUES (?,?,?,?,?,?)",
        (user_id, actor_id, ntype, short, text, now_iso()))
    conn.commit(); conn.close()

def get_notifications(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT n.*, u.username AS actor_name FROM notifications n "
        "LEFT JOIN users u ON u.id=n.actor_id WHERE n.user_id=? "
        "ORDER BY n.created_at DESC LIMIT 100", (user_id,)).fetchall()
    conn.close(); return rows

def unread_count(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user_id,)).fetchone()
    conn.close(); return row[0]

def mark_notifications_read(user_id):
    conn = get_db()
    conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

def get_creator_stats(username):
    conn = get_db()
    started = conn.execute(
        "SELECT COUNT(*) FROM futures WHERE creator=?", (username,)).fetchone()[0]
    contributions = conn.execute(
        "SELECT COUNT(*) FROM contributions WHERE creator=?", (username,)).fetchone()[0]
    worlds = conn.execute(
        "SELECT COUNT(*) FROM futures WHERE creator=? AND is_world=1", (username,)).fetchone()[0]
    conn.close()
    return started, contributions, worlds

def get_feed(limit=30):
    conn = get_db()
    items = []
    for f in conn.execute("SELECT * FROM futures ORDER BY created_at DESC LIMIT 200"):
        items.append({"kind":"future","time":f["created_at"],"actor":f["creator"],
                      "short":f["short_id"],"text":f["title"],"type":None})
    for c in conn.execute(
            "SELECT c.*, f.short_id FROM contributions c JOIN futures f ON f.id=c.future_id "
            "ORDER BY c.created_at DESC LIMIT 200"):
        items.append({"kind":"contribution","time":c["created_at"],"actor":c["creator"],
                      "short":c["short_id"],"text":c["title"],"type":c["type"]})
    for cm in conn.execute(
            "SELECT cm.*, u.username, f.short_id FROM comments cm "
            "LEFT JOIN users u ON u.id=cm.author_id JOIN futures f ON f.id=cm.future_id "
            "ORDER BY cm.created_at DESC LIMIT 200"):
        items.append({"kind":"comment","time":cm["created_at"],"actor":cm["username"] or "Anonymous",
                      "short":cm["short_id"],"text":cm["body"],"type":None})
    conn.close()
    items.sort(key=lambda x: x["time"], reverse=True)
    return items[:limit]

# -------------------------------------------------
# CSS — based on v0.1 prototype design language
# Minimal dark · Inter font · Monochrome · Clean
# -------------------------------------------------
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Noto+Sans+SC:wght@300;400;500&display=swap');

:root {
  --bg: #0a0a0b; --fg: #f4f4f5; --muted: #a1a1aa; --subtle: #71717a;
  --border: #27272a; --card: #111113; --card-bg: #111113; --hover: #18181b;
  --input-bg: #18181b;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

html { background: var(--bg); scroll-behavior: smooth; }

body {
  font-family: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
  background: var(--bg); color: var(--fg);
  min-height: 100vh; line-height: 1.6; font-size: 15px; -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

/* Header */
header {
  position: sticky; top: 0; z-index: 50;
  background: rgba(10,10,11,0.9); backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid transparent;
  padding: 16px 32px;
  display: flex; justify-content: space-between; align-items: center;
  transition: border-color 0.2s;
}
header.scrolled { border-bottom-color: var(--border); }
.logo {
  font-size: 13px; font-weight: 500; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--fg); text-decoration: none;
}
.header-right { display: flex; gap: 20px; align-items: center; }
.header-right a {
  font-size: 13px; color: var(--muted); text-decoration: none; transition: color 0.2s;
}
.header-right a:hover, .header-right a.active { color: var(--fg); }

/* Layout containers */
.container { max-width: 720px; margin: 0 auto; padding: 48px 24px 100px; }
.container-wide { max-width: 960px; margin: 0 auto; padding: 48px 24px 100px; }

/* Hero */
.hero { text-align: center; margin-bottom: 48px; }
.hero h1 {
  font-size: clamp(28px, 5vw, 36px); font-weight: 400;
  letter-spacing: -0.02em; margin-bottom: 12px;
}
.hero p { font-size: 16px; color: var(--muted); font-weight: 300; }

/* Seed input */
.input-wrapper {
  background: var(--input-bg); border: 1px solid var(--border);
  border-radius: 16px; padding: 20px 20px 16px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-wrapper:focus-within {
  border-color: #3f3f46;
  box-shadow: 0 0 0 4px rgba(255,255,255,0.03);
}
textarea {
  width: 100%; background: transparent; border: none; outline: none;
  color: var(--fg); font-size: 17px; font-family: inherit;
  resize: none; min-height: 120px; line-height: 1.6;
}
textarea::placeholder { color: #52525b; }
.form-footer {
  display: flex; justify-content: space-between; align-items: center;
  gap: 12px; margin-top: 12px; padding: 0 4px;
}
.hint { font-size: 13px; color: #52525b; flex: 1; min-width: 0; }

/* Minimal ghost select (category picker, contribute type fallback) */
.ghost-select {
  background: transparent; border: 1px solid var(--border); border-radius: 999px;
  color: var(--subtle); padding: 6px 12px; font-size: 12px;
  font-family: inherit; cursor: pointer; outline: none; transition: all 0.2s;
}
.ghost-select:hover, .ghost-select:focus { border-color: #3f3f46; color: var(--fg); }
.ghost-select option { background: var(--card); color: var(--fg); }

/* Text inputs (contribute form etc.) */
.text-input {
  width: 100%; background: var(--input-bg); border: 1px solid var(--border);
  border-radius: 12px; color: var(--fg); padding: 12px 14px;
  font-size: 14px; font-family: inherit; outline: none; transition: border-color 0.2s;
}
.text-input:focus { border-color: #3f3f46; }
.text-input::placeholder { color: #52525b; }

/* Success state (after publish) — demo home */
.result { display: none; text-align: center; animation: fadeIn 0.4s ease; }
.result.show { display: block; }
.result .label { font-size: 13px; color: var(--muted); margin-bottom: 12px; }
.result .url {
  font-size: 18px; font-weight: 500; letter-spacing: -0.01em;
  margin-bottom: 24px; word-break: break-all;
}
.result .url a {
  color: var(--fg); text-decoration: none; border-bottom: 1px solid #3f3f46;
}
.result .actions { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; align-items: center; }
.result .actions button, .result .actions a {
  background: transparent; border: 1px solid var(--border); color: var(--fg);
  border-radius: 999px; padding: 9px 18px; font-size: 13px;
  cursor: pointer; font-family: inherit; transition: background 0.2s; text-decoration: none;
}
.result .actions button:hover, .result .actions a:hover { background: rgba(255,255,255,0.05); }

/* Buttons */
.btn-primary {
  background: var(--fg); color: var(--bg); border: none;
  border-radius: 999px; padding: 10px 22px;
  font-size: 14px; font-weight: 500; cursor: pointer;
  font-family: inherit; transition: opacity 0.2s, transform 0.15s;
}
.btn-primary:hover { opacity: 0.9; }
.btn-primary:active { transform: scale(0.97); }
.btn-primary:disabled { opacity: 0.35; cursor: not-allowed; }

.btn-secondary {
  background: transparent; border: 1px solid var(--border); color: var(--fg);
  border-radius: 999px; padding: 9px 18px; font-size: 13px;
  cursor: pointer; font-family: inherit; transition: all 0.2s;
}
.btn-secondary:hover { border-color: #3f3f46; background: rgba(255,255,255,0.04); }
.btn-secondary:active { transform: scale(0.98); }

/* Seed cards — demo home "Growing Futures" (transparent, border-only) */
.seeds-section { margin-top: 100px; width: 100%; }
.section-label {
  font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase;
  color: #52525b; margin-bottom: 20px; text-align: center;
}
.seeds-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px;
}
.seed-card {
  background: transparent; border: 1px solid var(--border);
  border-radius: 12px; padding: 18px 20px;
  text-decoration: none; color: inherit;
  transition: border-color 0.2s, background 0.2s;
  display: block;
}
.seed-card:hover { border-color: #3f3f46; background: rgba(255,255,255,0.02); }
.seed-card .title { font-size: 15px; font-weight: 400; line-height: 1.4; margin-bottom: 6px; }
.seed-card .meta { font-size: 12px; color: var(--subtle); }

/* Seed detail page */
.seed-meta { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--subtle); margin-bottom: 20px; }
.seed-id { font-variant-numeric: tabular-nums; }
.seed-title {
  font-size: clamp(24px, 5vw, 32px); font-weight: 400;
  letter-spacing: -0.025em; line-height: 1.3; margin-bottom: 24px;
}
.seed-body { font-size: 16.5px; color: #e4e4e7; line-height: 1.75; margin-bottom: 28px; white-space: pre-wrap; }
.seed-footer {
  display: flex; justify-content: space-between; align-items: center;
  padding-bottom: 32px; border-bottom: 1px solid var(--border); margin-bottom: 40px;
  flex-wrap: wrap; gap: 16px;
}
.creator { display: flex; align-items: center; gap: 10px; text-decoration: none; color: inherit; }
.avatar {
  width: 34px; height: 34px; border-radius: 50%; background: #27272a;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 500; color: var(--muted);
}
.creator-name { font-size: 14px; font-weight: 500; }
.creator-date { font-size: 12px; color: var(--subtle); }

/* Explore grid */
.categories { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 40px; }

/* Feed (live activity stream) */
.feed { display: flex; flex-direction: column; gap: 2px; }
.feed-item { display: flex; gap: 12px; padding: 14px 0; border-bottom: 1px solid var(--border); align-items: flex-start; }
.feed-item:last-child { border-bottom: none; }
.feed-item .ic { flex: 0 0 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; background: #27272a; border: 1px solid var(--border); color: var(--muted); }

.cat-btn {
  background: transparent; border: 1px solid var(--border); color: var(--muted);
  border-radius: 999px; padding: 7px 16px; font-size: 13px;
  cursor: pointer; font-family: inherit; transition: all 0.2s;
}
.cat-btn:hover, .cat-btn.active {
  border-color: #3f3f46; color: var(--fg);
  background: rgba(255,255,255,0.03);
}

/* Explore page — demo03 */
.page-title { font-size: 28px; font-weight: 400; letter-spacing: -0.02em; margin-bottom: 8px; }
.page-desc { font-size: 15px; color: var(--muted); margin-bottom: 48px; }
.questions-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px; margin-bottom: 64px;
}
.question-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 22px 20px;
  text-decoration: none; color: inherit;
  transition: all 0.2s; display: flex; flex-direction: column; gap: 10px;
  min-height: 140px;
}
.question-card:hover {
  border-color: #3f3f46; background: var(--hover); transform: translateY(-1px);
}
.question-card .q { font-size: 16px; font-weight: 400; line-height: 1.45; flex: 1; }
.question-card .meta { font-size: 12px; color: var(--subtle); display: flex; justify-content: space-between; }

/* Seed rows (list view) */
.seed-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 18px; border: 1px solid var(--border);
  border-radius: 12px; text-decoration: none; color: inherit;
  transition: all 0.2s; gap: 16px;
}
.seed-row:hover { border-color: #3f3f46; background: rgba(255,255,255,0.02); }
.seed-row .title { font-size: 15px; flex: 1; }
.seed-row .info { font-size: 12px; color: var(--subtle); white-space: nowrap; }

/* "Explore this Future" tile grid — demo seed page */
.explore-label {
  font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--subtle); margin-bottom: 20px;
}
.explore-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
@media (min-width: 560px) { .explore-grid { grid-template-columns: repeat(3, 1fr); } }
.explore-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 22px 20px;
  text-decoration: none; color: inherit; transition: all 0.2s;
  display: flex; flex-direction: column; gap: 6px; min-height: 110px;
}
.explore-card:hover { border-color: #3f3f46; background: var(--hover); transform: translateY(-1px); }
.explore-card .icon { font-size: 18px; margin-bottom: 4px; opacity: 0.7; }
.explore-card .name { font-size: 15px; font-weight: 500; }
.explore-card .count { font-size: 12px; color: var(--subtle); margin-top: auto; }

/* Branches preview — demo seed page */
.branches-section { margin-top: 64px; }
.section-header {
  display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px;
}
.section-link { font-size: 13px; color: var(--muted); text-decoration: none; }
.section-link:hover { color: var(--fg); }
.branch-list { display: flex; flex-direction: column; gap: 8px; }
.branch-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 16px; border: 1px solid var(--border); border-radius: 10px;
  text-decoration: none; color: inherit; transition: all 0.2s; gap: 12px;
}
.branch-item:hover { border-color: #3f3f46; background: rgba(255,255,255,0.02); }
.branch-title { font-size: 14px; }
.branch-meta { font-size: 12px; color: var(--subtle); white-space: nowrap; }

/* World page */
.layout { display: flex; max-width: 1100px; margin: 0 auto; min-height: calc(100vh - 53px); }
.sidebar {
  width: 220px; flex-shrink: 0; padding: 32px 20px 40px;
  border-right: 1px solid var(--border);
  position: sticky; top: 53px; height: calc(100vh - 53px); overflow-y: auto;
}
.sidebar-label {
  font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--subtle); margin-bottom: 12px; padding-left: 10px;
}
.nav-list { list-style: none; display: flex; flex-direction: column; gap: 2px; }
.nav-list a {
  display: block; padding: 8px 10px; font-size: 13.5px; color: var(--muted);
  text-decoration: none; border-radius: 8px; transition: all 0.15s;
}
.nav-list a:hover { color: var(--fg); background: rgba(255,255,255,0.04); }
.nav-list a.active { color: var(--fg); background: rgba(255,255,255,0.06); }
.main-content { flex: 1; padding: 40px 40px 80px; max-width: 680px; }
.world-badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--subtle); margin-bottom: 16px;
}
.world-badge span {
  background: rgba(255,255,255,0.06); padding: 3px 8px;
  border-radius: 999px; font-size: 11px;
}
.world-title {
  font-size: clamp(26px, 4vw, 34px); font-weight: 400;
  letter-spacing: -0.03em; line-height: 1.25; margin-bottom: 8px;
}
.world-tagline { font-size: 17px; color: var(--muted); margin-bottom: 24px; }
.world-meta {
  display: flex; flex-wrap: wrap; gap: 20px; font-size: 13px; color: var(--subtle);
  padding-bottom: 28px; border-bottom: 1px solid var(--border); margin-bottom: 36px;
}
.world-meta strong { color: var(--muted); font-weight: 500; }

/* Sections */
.section { margin-bottom: 44px; }
.section-title {
  font-size: 15px; font-weight: 500; margin-bottom: 16px;
  display: flex; justify-content: space-between; align-items: baseline;
}
.section-title a { font-size: 13px; color: var(--muted); text-decoration: none; }
.section-title a:hover { color: var(--fg); }
.overview-text { font-size: 16px; color: #e4e4e7; line-height: 1.75; margin-bottom: 20px; }

/* Cards grid */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px; text-decoration: none; color: inherit;
  transition: all 0.2s; display: flex; flex-direction: column; gap: 6px;
}
.card:hover { border-color: #3f3f46; background: var(--hover); }
.card .name { font-size: 14px; font-weight: 500; }
.card .desc { font-size: 12.5px; color: var(--subtle); line-height: 1.4; }
.card .meta { font-size: 11.5px; color: #52525b; margin-top: auto; padding-top: 6px; }

/* Timeline */
.timeline { position: relative; padding-left: 20px; }
.timeline::before {
  content: ''; position: absolute; left: 5px; top: 6px; bottom: 6px;
  width: 1px; background: var(--border);
}
.timeline-item { position: relative; padding-bottom: 24px; }
.timeline-item::before {
  content: ''; position: absolute; left: -17px; top: 7px;
  width: 7px; height: 7px; border-radius: 50%;
  background: #3f3f46; border: 2px solid var(--bg);
}
.timeline-item .date { font-size: 12px; color: var(--subtle); margin-bottom: 4px; }
.timeline-item .event { font-size: 14.5px; }

/* Contributors */
.contributors { display: flex; flex-wrap: wrap; gap: 8px; }
.contributor {
  display: flex; align-items: center; gap: 8px; padding: 6px 12px 6px 6px;
  border: 1px solid var(--border); border-radius: 999px;
  text-decoration: none; color: inherit; font-size: 13px; transition: all 0.2s;
}
.contributor:hover { border-color: #3f3f46; background: rgba(255,255,255,0.03); }
.contributor .av {
  width: 24px; height: 24px; border-radius: 50%; background: #27272a;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: var(--muted);
}

/* Profile page */
.profile { display: flex; align-items: flex-start; gap: 20px; margin-bottom: 40px; }
.avatar-lg {
  width: 72px; height: 72px; border-radius: 50%; background: #27272a;
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; font-weight: 500; color: var(--muted); flex-shrink: 0;
}
.stats { display: flex; gap: 28px; flex-wrap: wrap; }
.stat { display: flex; flex-direction: column; gap: 2px; }
.stat-num { font-size: 20px; font-weight: 500; letter-spacing: -0.02em; }
.stat-label { font-size: 12px; color: var(--subtle); }

/* Tabs */
.tabs { display: flex; gap: 24px; border-bottom: 1px solid var(--border); margin-bottom: 24px; }
.tab {
  font-size: 14px; color: var(--subtle); padding-bottom: 12px;
  cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.2s;
  background: none; border-top: none; border-left: none; border-right: none; font-family: inherit;
}
.tab:hover { color: var(--muted); }
.tab.active { color: var(--fg); border-bottom-color: var(--fg); }

/* Item list */
.item-list { display: flex; flex-direction: column; gap: 8px; }
.item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 15px 18px; border: 1px solid var(--border);
  border-radius: 12px; text-decoration: none; color: inherit;
  transition: all 0.2s; gap: 16px;
}
.item:hover { border-color: #3f3f46; background: rgba(255,255,255,0.02); }
.item .title { font-size: 15px; flex: 1; }
.item .meta { font-size: 12px; color: var(--subtle); white-space: nowrap; }

/* Notifications */
.notif {
  display: flex; gap: 12px; padding: 16px 0;
  border-bottom: 1px solid var(--border); text-decoration: none; color: inherit;
}
.notif:last-child { border-bottom: none; }
.notif.unread { background: rgba(255,255,255,0.02); }
.notif .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--fg); margin-top: 7px; flex: 0 0 8px; }
.notif .dot.read { background: transparent; }

/* Comment */
.comment {
  border-left: 2px solid var(--border); padding: 10px 14px;
  margin-top: 10px; background: var(--hover);
  border-radius: 0 10px 10px 0;
}
.comment-form { margin-top: 24px; }
.comment-form textarea {
  min-height: 80px; background: var(--input-bg); border: 1px solid var(--border);
  border-radius: 12px; padding: 12px 14px; font-size: 14px; font-family: inherit;
  color: var(--fg); resize: vertical; width: 100%; outline: none;
}
.comment-form textarea:focus { border-color: #3f3f46; }
.comment-list { margin-top: 20px; display: flex; flex-direction: column; gap: 12px; }

/* Contribute form */
.contribute-types {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 16px 0;
}
.type-btn {
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 8px; text-align: center; cursor: pointer; transition: all 0.2s;
  font-family: inherit; color: var(--muted); font-size: 13px;
}
.type-btn:hover { border-color: #3f3f46; color: var(--fg); background: var(--hover); }
.type-btn.selected { border-color: #3f3f46; color: var(--fg); background: var(--hover); }

/* CTA box */
.cta-box {
  margin-top: 48px; padding: 28px; border: 1px dashed #3f3f46;
  border-radius: 16px; text-align: center;
}
.cta-box p { font-size: 15px; color: var(--muted); margin-bottom: 16px; }

/* Alerts */
.alert {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; font-size: 14px;
}
.alert.err { border-color: #ff7d7d; color: #ff7d7d; }
.alert.ok { border-color: var(--muted); color: var(--muted); }
.alert a { color: var(--fg); }

/* Contributions list */
.contrib-list { display: flex; flex-direction: column; gap: 10px; margin-top: 16px; }
.contrib-item {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px 20px;
  transition: border-color 0.2s;
}
.contrib-item:hover { border-color: #3f3f46; }
.contrib-type {
  font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--subtle); margin-bottom: 6px;
}
.contrib-title { font-size: 15px; font-weight: 400; margin-bottom: 6px; }
.contrib-meta { font-size: 12px; color: var(--subtle); }
.contrib-body { font-size: 14px; color: var(--muted); margin-top: 8px; line-height: 1.6; white-space: pre-wrap; }

/* Footer — demo: quiet, centered, no heavy border */
footer { text-align: center; padding: 24px 40px; font-size: 12px; color: #3f3f46; }

/* Empty state */
.empty { text-align: center; padding: 48px 20px; color: var(--subtle); font-size: 14px; }

/* World badge in header */
.world-indicator {
  font-size: 12px; background: rgba(255,255,255,0.06);
  padding: 3px 10px; border-radius: 999px; color: var(--muted);
}

/* Responsive */
@media (max-width: 800px) {
  .layout { flex-direction: column; }
  .sidebar {
    width: 100%; height: auto; position: static; border-right: none;
    border-bottom: 1px solid var(--border); padding: 20px 16px;
  }
  .nav-list { flex-direction: row; flex-wrap: wrap; gap: 6px; }
  .nav-list a { padding: 6px 12px; font-size: 13px; background: rgba(255,255,255,0.03); }
  .main-content { padding: 32px 20px 60px; }
}
@media (max-width: 640px) {
  header { padding: 14px 16px; }
  .container, .container-wide { padding: 32px 16px 80px; }
  .hero { margin-bottom: 36px; }
  .seeds-section { margin-top: 72px; }
  .seed-footer { flex-direction: column; align-items: flex-start; }
  .profile { flex-direction: column; align-items: center; text-align: center; }
  .stats { justify-content: center; }
  .item { flex-direction: column; align-items: flex-start; gap: 6px; }
  .seed-row { flex-direction: column; align-items: flex-start; gap: 6px; }
  .contribute-types { grid-template-columns: repeat(2, 1fr); }
}

/* Fade in animation */
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.fade-in { animation: fadeIn 0.4s ease; }

/* Toast — top-right transient notifications */
#toast-root { position: fixed; top: 20px; right: 20px; z-index: 1000; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toast { background: var(--card-bg); border: 1px solid var(--border); color: var(--fg); padding: 12px 16px; border-radius: 12px; font-size: 14px; box-shadow: 0 8px 24px rgba(0,0,0,0.3); opacity: 0; transform: translateY(-8px); transition: opacity .25s ease, transform .25s ease; pointer-events: auto; max-width: 320px; }
.toast.show { opacity: 1; transform: translateY(0); }
.toast.ok  { border-color: rgba(120, 200, 130, 0.35); }
.toast.err { border-color: rgba(220, 120, 120, 0.4); }

/* Row-level inline actions (delete, reply) — visible on hover for clarity */
.row-actions { display: inline-flex; gap: 6px; margin-left: 8px; opacity: 0; transition: opacity .15s ease; }
.has-actions:hover .row-actions, .row-actions:focus-within { opacity: 1; }
.icon-btn { background: transparent; border: 0; color: var(--muted); cursor: pointer; padding: 2px 6px; font-size: 12px; border-radius: 6px; font-family: inherit; }
.icon-btn:hover { color: var(--fg); background: rgba(255,255,255,0.06); }
.icon-btn.danger:hover { color: #ff8a8a; }

.reply-form { margin-top: 8px; margin-left: 20px; padding: 12px; background: var(--input-bg); border: 1px solid var(--border); border-radius: 10px; display: none; }
.reply-form.open { display: block; }
.reply-form textarea { width: 100%; background: transparent; border: 0; color: var(--fg); font-family: inherit; font-size: 13px; resize: vertical; min-height: 60px; outline: none; }
.reply-form .reply-actions { display: flex; gap: 6px; margin-top: 8px; }
.reply-form .reply-actions button { padding: 6px 12px; font-size: 12px; border-radius: 8px; cursor: pointer; border: 1px solid var(--border); background: transparent; color: var(--fg); font-family: inherit; }
.reply-form .reply-actions .primary { background: var(--fg); color: var(--bg); border-color: var(--fg); }

.confirm-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: none; align-items: center; justify-content: center; z-index: 999; }
.confirm-overlay.open { display: flex; }
.confirm-box { background: var(--card-bg); border: 1px solid var(--border); border-radius: 16px; padding: 24px; max-width: 400px; width: 90%; box-shadow: 0 12px 32px rgba(0,0,0,0.4); }
.confirm-box h3 { margin: 0 0 8px 0; font-size: 16px; font-weight: 500; }
.confirm-box p { margin: 0 0 20px 0; font-size: 14px; color: var(--muted); }
.confirm-box .actions { display: flex; justify-content: flex-end; gap: 8px; }
.confirm-box button { padding: 8px 16px; border-radius: 10px; border: 1px solid var(--border); background: transparent; color: var(--fg); font-family: inherit; font-size: 14px; cursor: pointer; }
.confirm-box button.primary { background: var(--fg); color: var(--bg); border-color: var(--fg); }
.confirm-box button.danger { background: #ff5757; color: #fff; border-color: #ff5757; }
"""

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

TYPE_EN = {
    "people": "People", "place": "Place", "story": "Story",
    "rule": "Rule", "object": "Object", "branch": "Branch"
}

def avatar_initial(username):
    return esc(username[0].upper()) if username else "?"

# -------------------------------------------------
# Page shell
# -------------------------------------------------
def _shared_js():
    """Client-side interactions shared by every page:
    - toasts for ephemeral feedback
    - confirm() dialog replacement
    - delete buttons (delegated)
    - reply forms (delegated)
    - notifications bell -> mark read on click
    - publish button enable + Ctrl/Cmd+Enter shortcut
    - explore category filter
    - copy-link with feedback
    Keeping it inline keeps the app single-file / zero-build."""
    return """
<script>
(function(){
  const toastRoot = document.getElementById('toast-root');
  window.toast = function(msg, kind) {
    const t = document.createElement('div');
    t.className = 'toast ' + (kind || '');
    t.textContent = msg;
    toastRoot.appendChild(t);
    requestAnimationFrame(() => t.classList.add('show'));
    setTimeout(() => {
      t.classList.remove('show');
      setTimeout(() => t.remove(), 250);
    }, 2200);
  };

  // Confirm dialog (replacement for window.confirm — looks better + non-blocking)
  window.confirmModal = function(title, msg, opts) {
    opts = opts || {};
    return new Promise(resolve => {
      const root = document.getElementById('confirm-root');
      const box  = document.getElementById('confirm-box');
      box.innerHTML = '<h3></h3><p></p><div class="actions"><button data-act="cancel">Cancel</button><button data-act="ok" class="' + (opts.danger ? 'danger' : 'primary') + '">' + (opts.okLabel || 'Confirm') + '</button></div>';
      box.querySelector('h3').textContent = title;
      box.querySelector('p').textContent = msg;
      root.classList.add('open');
      function close(v) {
        root.classList.remove('open');
        box.innerHTML = '';
        resolve(v);
      }
      box.querySelector('[data-act=cancel]').onclick = () => close(false);
      box.querySelector('[data-act=ok]').onclick    = () => close(true);
    });
  };

  // ---------- Notifications bell: mark as read when clicked ----------
  const bell = document.querySelector('a[href="/notifications"]');
  if (bell) bell.addEventListener('click', () => {
    const badge = bell.querySelector('span');
    if (badge) badge.remove();
    fetch('/api/notifications/read', { method: 'GET' }).catch(() => {});
  });

  // ---------- Publish form: enable button + keyboard shortcut ----------
  const fi = document.getElementById('futureInput');
  const pb = document.getElementById('publishBtn');
  if (fi && pb) {
    fi.addEventListener('input', () => { pb.disabled = !fi.value.trim(); });
    fi.addEventListener('keydown', e => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        if (fi.value.trim()) fi.form.submit();
      }
    });
  }

  // ---------- Explore category filter ----------
  document.querySelectorAll('[data-explore-cat]').forEach(btn => {
    btn.addEventListener('click', () => {
      const cat = btn.dataset.exploreCat;
      document.querySelectorAll('[data-explore-cat]').forEach(b => b.classList.toggle('active', b === btn));
      document.querySelectorAll('[data-row-cat]').forEach(row => {
        const cats = (row.dataset.rowCat || '').split(',');
        row.style.display = (cat === 'All' || cats.includes(cat)) ? '' : 'none';
      });
      const empty = document.getElementById('explore-empty');
      const visible = Array.from(document.querySelectorAll('[data-row-cat]')).filter(r => r.style.display !== 'none');
      if (empty) empty.style.display = visible.length ? 'none' : '';
    });
  });

  // ---------- Profile tabs ----------
  document.querySelectorAll('.tab').forEach(t => {
    t.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(x => x.style.display = 'none');
      t.classList.add('active');
      const pane = document.getElementById(t.dataset.tab);
      if (pane) pane.style.display = 'block';
    });
  });

  // ---------- Header scroll shadow ----------
  const hdr = document.getElementById('site-header');
  if (hdr) window.addEventListener('scroll', () => hdr.classList.toggle('scrolled', window.scrollY > 10));

  // ---------- Delegated handlers ----------
  document.body.addEventListener('click', async e => {
    // Copy link buttons
    const copy = e.target.closest('[data-copy]');
    if (copy) {
      const raw = copy.dataset.copy;
      const url = raw.startsWith('http') ? raw : location.origin + raw;
      try {
        await navigator.clipboard.writeText(url);
        toast('Link copied', 'ok');
      } catch(_) {
        toast('Copy failed', 'err');
      }
      return;
    }

    // Delete buttons (redirect for whole-page delete, AJAX for inline)
    const del = e.target.closest('[data-delete]');
    if (del) {
      e.preventDefault();
      const url = del.dataset.delete;
      const what = del.dataset.label || 'this';
      const ok = await confirmModal('Delete ' + what + '?', 'This cannot be undone.', { danger: true, okLabel: 'Delete' });
      if (!ok) return;
      try {
        const r = await fetch(url, { method: 'POST' });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || 'Failed');
        // If the API returned a redirect target, navigate; otherwise remove from DOM.
        if (j.redirect) {
          location.href = j.redirect;
          return;
        }
        const row = del.closest('[data-row],.contrib-item,.comment,.item');
        if (row) { row.style.transition = 'opacity .2s ease'; row.style.opacity = '0'; setTimeout(() => row.remove(), 220); }
        toast('Deleted', 'ok');
      } catch (err) {
        toast(err.message || 'Delete failed', 'err');
      }
      return;
    }

    // Reply toggles
    const rep = e.target.closest('[data-reply-toggle]');
    if (rep) {
      const form = rep.closest('.comment').querySelector('.reply-form');
      if (form) {
        form.classList.toggle('open');
        const ta = form.querySelector('textarea');
        if (form.classList.contains('open') && ta) ta.focus();
      }
      return;
    }

    // Reply submit (cancel + post)
    if (e.target.matches('[data-reply-cancel]')) {
      const f = e.target.closest('.reply-form');
      if (f) f.classList.remove('open');
      return;
    }
    if (e.target.matches('[data-reply-post]')) {
      const f = e.target.closest('.reply-form');
      const ta = f.querySelector('textarea');
      const body = ta.value.trim();
      if (!body) { toast('Empty reply', 'err'); return; }
      const futureId = f.dataset.futureId;
      const parentId = f.dataset.parentId;
      try {
        const r = await fetch('/api/comment', {
          method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded'},
          body: 'future_id=' + encodeURIComponent(futureId)
              + '&parent_id=' + encodeURIComponent(parentId)
              + '&body=' + encodeURIComponent(body)
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || 'Failed');
        toast('Reply posted', 'ok');
        setTimeout(() => location.reload(), 400);
      } catch (err) {
        toast(err.message || 'Reply failed', 'err');
      }
      return;
    }
  });
})();
</script>"""

def page(user, unread, title, body, wide=False, extra_js=""):
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · Duoweilai</title>
<style>{CSS}</style></head>
<body>{_header(user, unread)}{body}<div id="toast-root"></div><div id="confirm-root" class="confirm-overlay"><div class="confirm-box" id="confirm-box"></div></div><script>{_shared_js()}{extra_js}</script></body></html>"""

def _header(user, unread=0):
    """Top navigation. Shows username + bell when signed in; sign-in/sign-up
    CTAs when not."""
    if user:
        right = (f'<a href="/notifications">Notifications'
                 + (f'<span style="background:#ff7d7d;color:#0a0a0b;font-size:10px;border-radius:999px;padding:1px 5px;margin-left:4px">{unread}</span>' if unread else '')
                 + '</a>')
        right += f'<a href="/person/{quote(user["username"])}">{esc(user["username"])}</a>'
        right += '<a href="/logout">Sign out</a>'
    else:
        right = '<a href="/login">Sign in</a><a href="/register" style="color:var(--fg)">Sign up</a>'
    return f"""
<header id="site-header">
  <a href="/" class="logo">Duoweilai</a>
  <div class="header-right">
    <a href="/explore">Explore</a>
    {right}
  </div>
</header>"""

# -------------------------------------------------
# Pages
# -------------------------------------------------
def render_home(user):
    """Home — publish a future seed + live feed."""
    feed = get_feed()

    # Feed
    if feed:
        feed_html = ""
        for it in feed:
            icon = {"future": "✦", "contribution": "＋", "comment": "◉"}.get(it["kind"], "·")
            if it["kind"] == "future":
                action = "published a future seed"
            elif it["kind"] == "contribution":
                t = TYPE_EN.get(it["type"], it["type"])
                action = f'contributed a <em>{t}</em>'
            else:
                action = "left a comment"
            text = esc(it["text"])
            if len(text) > 90: text = text[:90] + "…"
            feed_html += (f'<div class="feed-item"><div class="ic">{icon}</div>'
                          f'<div><b>{esc(it["actor"])}</b> {action} · '
                          f'<a href="/f/{it["short"]}">{text}</a>'
                          f'<div style="font-size:12px;color:var(--subtle);margin-top:2px">{rel_time(it["time"])}</div></div></div>')
    else:
        feed_html = '<div class="empty">No futures yet — be the first to plant one.</div>'

    # Publish form — only for signed-in users. Logged-out visitors see a
    # plain CTA pointing them to register / sign in.
    cats = ["Unknown", "Life", "Cities", "Education", "Culture", "Relationships", "Work", "Civilization", "Technology"]
    cat_opts = "".join(f'<option value="{c}">{c}</option>' for c in cats)
    if user:
        publish = f"""
        <div class="hero fade-in">
          <h1>What future do you imagine?</h1>
          <p>Write down a future. It becomes a permanent seed.</p>
        </div>
        <form method="post" action="/api/future">
          <div class="input-wrapper">
            <textarea name="title" id="futureInput" placeholder="Describe a future..."
                      rows="4"></textarea>
            <div class="form-footer">
              <select name="category" style="background:var(--input-bg);border:1px solid var(--border);border-radius:8px;color:var(--fg);padding:6px 10px;font-size:13px;font-family:inherit;cursor:pointer">
                {cat_opts}
              </select>
              <span class="hint">⌘ Enter to publish</span>
              <button type="submit" class="btn-primary" id="publishBtn" disabled>Publish a Future</button>
            </div>
          </div>
        </form>"""
    else:
        publish = f"""
        <div class="hero fade-in">
          <h1>What future do you imagine?</h1>
          <p>Pick an ID. Set a password. Plant seeds that outlive you.</p>
        </div>
        <div style="display:flex;gap:12px;justify-content:center;margin-bottom:32px">
          <a href="/register" class="btn-primary" style="text-decoration:none">Plant your first seed</a>
          <a href="/login" class="btn-secondary" style="text-decoration:none">Sign in</a>
        </div>
        <div style="text-align:center;color:var(--subtle);font-size:13.5px;max-width:480px;margin:0 auto">
          No phone number needed. Just an email so we can help you recover your account.
        </div>"""

    # Recent seeds for browsing
    futures = list_futures(6)
    if futures:
        cards = ""
        for f in futures:
            world_tag = ' <span class="world-indicator">World</span>' if f["is_world"] else ""
            cards += (f'<a href="/f/{f["short_id"]}" class="seed-card">'
                     f'<div class="title">{esc(f["title"])}</div>'
                     f'<div class="meta">{esc(f["creator"])} · {f["branches"]} branches · {rel_time(f["created_at"])}{world_tag}</div></a>')
        seeds_html = f"""
        <div class="seeds-section">
          <div class="section-label">Recently Published</div>
          <div class="seeds-grid">{cards}</div>
        </div>"""
    else:
        seeds_html = ""

    return page(user, unread_count(user["id"]) if user else 0, "Home",
               f'<div class="container">{publish}{seeds_html}</div>')

def render_explore(user):
    rows = list_futures(100)
    cats = ["All", "Life", "Cities", "Education", "Culture", "Relationships", "Work", "Civilization", "Technology", "Unknown"]
    cat_btns = "".join(
        f'<button class="cat-btn{" active" if c=="All" else ""}" data-explore-cat="{c}">{c}</button>'
        for c in cats)

    if rows:
        # Question cards grid (Future Questions)
        qcards = ""
        for f in rows:
            row_cat = (f["category"] if "category" in f.keys() else None) or "Unknown"
            qcards += (f'<a href="/f/{f["short_id"]}" class="question-card" data-row-cat="{row_cat}">'
                      f'<div class="q">{esc(f["title"])}</div>'
                      f'<div class="meta"><span>{row_cat}</span><span>{f["branches"]} seeds</span></div></a>')
        # Recently Growing list rows
        recent_rows = ""
        for f in rows:
            world_tag = ' <span class="world-indicator">World</span>' if f["is_world"] else ""
            row_cat = (f["category"] if "category" in f.keys() else None) or "Unknown"
            recent_rows += (f'<a href="/f/{f["short_id"]}" class="seed-row" data-row-cat="{row_cat}">'
                           f'<span class="title">{esc(f["title"])}</span>'
                           f'<span class="info">{f["branches"]} branches · {rel_time(f["created_at"])}{world_tag}</span></a>')
    else:
        qcards = '<div class="empty" id="explore-empty">No futures published yet.</div>'
        recent_rows = ""

    return page(user, 0, "Explore",
               f"""
<div class="container-wide">
  <h1 class="page-title">Explore Futures</h1>
  <p class="page-desc">不是按内容类型，而是按我们共同关心的未来问题。</p>
  <div class="categories">{cat_btns}</div>

  <div class="section-label">Future Questions</div>
  <div class="questions-grid">{qcards}</div>

  <div class="section-label">Recently Growing</div>
  <div class="seed-list">{recent_rows}</div>
</div>""")

def render_seed(user, short):
    f = get_future_by_short(short)
    if not f:
        return page(user, 0, "Not Found",
                    f'<div class="container"><div class="empty">This seed doesn\'t exist.</div></div>')
    inc_views(short)
    contribs = get_contributions(f["id"])
    comments = get_comments(f["id"])

    # Contributions grouped by type
    groups = {}
    for c in contribs: groups.setdefault(c["type"], []).append(c)
    contrib_html = ""
    order = ["people", "place", "story", "rule", "object", "branch"]
    for t in order:
        if t not in groups: continue
        label = TYPE_EN.get(t, t)
        contrib_html += f'<div style="margin-top:32px"><div class="section-label">{label}s</div>'
        for c in groups[t]:
            can_del = bool(user and user["id"] == c["author_id"])
            del_btn = (f'<span class="row-actions" style="display:inline-flex;gap:4px;margin-left:8px">'
                       f'<button class="icon-btn danger" data-delete="/api/contribution/{c["id"]}/delete" data-label="this contribution">✕</button>'
                       f'</span>') if can_del else ''
            contrib_html += (f'<div class="contrib-item">'
                            f'<div class="contrib-type">{label}</div>'
                            f'<div class="contrib-title">{esc(c["title"])}</div>'
                            f'<div class="contrib-meta">by {esc(c["creator"])} · {rel_time(c["created_at"])}{del_btn}</div>'
                            + (f'<div class="contrib-body">{esc(c["body"])}</div>' if c["body"] else '')
                            + '</div>')
        contrib_html += '</div>'
    if not contribs:
        contrib_html = '<div class="empty" style="margin-top:16px">No contributions yet. Be the first.</div>'

    # Comments — threaded (parent + replies)
    top_level = [cm for cm in comments if not cm["parent_id"]]
    replies_map = {}
    for cm in comments:
        if cm["parent_id"]: replies_map.setdefault(cm["parent_id"], []).append(cm)

    def render_comment(cm, depth=0):
        can_del = bool(user and user["id"] == cm["author_id"])
        del_btn = (f'<button class="icon-btn danger" data-delete="/api/comment/{cm["id"]}/delete" data-label="this comment" style="margin-left:4px">✕</button>'
                   if can_del else '')
        reply_btn = (f'<button class="icon-btn" data-reply-toggle style="margin-left:4px">↩ reply</button>'
                     if depth == 0 and user else '')
        html = (f'<div class="comment" data-row>'
                f'<div style="font-size:13px;font-weight:500">{esc(cm["username"])}{del_btn}{reply_btn}</div>'
                f'<div style="font-size:12px;color:var(--subtle);margin-bottom:6px">{rel_time(cm["created_at"])}</div>'
                f'<div style="font-size:14px;margin-top:4px">{esc(cm["body"])}</div>'
                f'<div class="reply-form" data-future-id="{short}" data-parent-id="{cm["id"]}">'
                f'<textarea placeholder="Write a reply..."></textarea>'
                f'<div class="reply-actions">'
                f'<button data-reply-cancel class="icon-btn">Cancel</button>'
                f'<button data-reply-post class="icon-btn primary" style="background:var(--fg);color:var(--bg);border-radius:8px;border:1px solid var(--fg)">Post</button>'
                f'</div></div></div>')
        for reply in replies_map.get(cm["id"], []):
            html += render_comment(reply, depth+1)
        return html

    comment_html = "".join(render_comment(cm) for cm in top_level)

    # Explore this Future tiles
    type_map = [("people","People","◎"), ("place","Places","◇"), ("story","Stories","▣"), ("rule","Rules","◈"), ("object","Objects","○"), ("branch","Branches","↗")]
    explore_tiles = ""
    for t, label, icon in type_map:
        cnt = len(groups.get(t, []))
        explore_tiles += f'<a href="#{label.lower()}" class="explore-card"><div class="icon">{icon}</div><div class="name">{label}</div><div class="count">{cnt} {label}</div></a>'

    # Recent Branches list
    branch_contribs = groups.get("branch", [])[:3]
    recent_branches = ""
    if branch_contribs:
        recent_branches = '<div class="branch-list">' + "".join(
            f'<a href="/f/{short}" class="branch-item"><span class="branch-title">{esc(c["title"])}</span><span class="branch-meta">{esc(c["creator"])} · {rel_time(c["created_at"])}</span></a>'
            for c in branch_contribs) + '</div>'
    else:
        recent_branches = '<div class="empty" style="margin-top:16px">No branches yet.</div>'

    # Comment form — only for signed-in users
    if user:
        comment_form = f"""
        <div class="comment-form">
          <form method="post" action="/api/comment">
            <input type="hidden" name="future_id" value="{short}">
            <textarea name="body" placeholder="Share a thought on this future..." rows="3"></textarea>
            <div style="margin-top:10px">
              <button type="submit" class="btn-secondary">Post comment</button>
            </div>
          </form>
        </div>"""
    else:
        comment_form = f"""
        <div style="text-align:center;padding:20px;border:1px dashed #3f3f46;border-radius:12px;margin-top:24px">
          <p style="color:var(--muted);margin-bottom:12px;font-size:14px">Sign in to join the discussion.</p>
          <a href="/login" class="btn-secondary" style="text-decoration:none;display:inline-block">Sign in</a>
        </div>"""

    # Contribute form — only for signed-in users (auto-login no longer bypasses)
    if user:
        type_opts = "".join(f'<option value="{k}">{v}</option>' for k, v in TYPE_EN.items())
        contribute_form = f"""
        <div class="cta-box" style="margin-top:32px">
          <p>Help this future grow. Add something to it.</p>
          <form method="post" action="/api/contribute">
            <input type="hidden" name="future_id" value="{short}">
            <select name="type" style="width:100%;background:var(--input-bg);border:1px solid var(--border);border-radius:12px;color:var(--fg);padding:12px 14px;font-size:14px;font-family:inherit;margin-bottom:12px">
              {type_opts}
            </select>
            <input name="title" placeholder="Title" required style="width:100%;background:var(--input-bg);border:1px solid var(--border);border-radius:12px;color:var(--fg);padding:12px 14px;font-size:14px;font-family:inherit;margin-bottom:10px">
            <textarea name="body" placeholder="Description (optional)" rows="3" style="width:100%;background:var(--input-bg);border:1px solid var(--border);border-radius:12px;color:var(--fg);padding:12px 14px;font-size:14px;font-family:inherit;margin-bottom:10px"></textarea>
            <button type="submit" class="btn-primary">Contribute</button>
          </form>
        </div>"""
    else:
        contribute_form = f"""
        <div class="cta-box" style="margin-top:32px">
          <p>Sign in to add People, Places, Stories, Rules, Objects, or Branches to this future.</p>
          <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
            <a href="/register" class="btn-primary" style="text-decoration:none">Create account</a>
            <a href="/login" class="btn-secondary" style="text-decoration:none">Sign in</a>
          </div>
        </div>"""

    world_cta = ""
    if f["is_world"]:
        world_cta = f'<a href="/world/{short}" class="btn-secondary" style="display:inline-block;text-decoration:none;margin-top:8px">Enter World view →</a>'

    can_edit_seed = bool(user and user["id"] == f["creator_id"])
    seed_del = (f'<a class="icon-btn danger" data-delete="/api/future/{short}/delete" data-label="this seed" '
                f'style="margin-left:8px;color:var(--muted);text-decoration:none">delete</a>'
                if can_edit_seed else '')
    body = f"""
<div class="container">
  <div class="seed-meta">
    <span>Future Seed</span><span>·</span>
    <span class="seed-id">#{f["short_id"]}</span>
    <span>·</span><span>{f["views"]} views</span>
    {'<span>·</span><span style="color:var(--fg)">World</span>' if f["is_world"] else ''}
    {seed_del}
  </div>
  <h1 class="seed-title">{esc(f["title"])}</h1>
  {('<div class="seed-body">'+esc(f["body"])+'</div>' if f["body"] else '')}

  <div class="seed-footer">
    <a href="/person/{quote(f["creator"])}" class="creator">
      <div class="avatar">{avatar_initial(f["creator"])}</div>
      <div>
        <div class="creator-name">{esc(f["creator"])}</div>
        <div class="creator-date">{rel_time(f["created_at"])}</div>
      </div>
    </a>
    <div>
      <button class="btn-secondary" data-copy="/f/{short}">Share</button>
      <button class="btn-secondary">Branch</button>
      {world_cta}
    </div>
  </div>

  <div class="explore-label">Explore this Future</div>
  <div class="explore-grid">{explore_tiles}</div>

  <div class="branches-section">
    <div class="section-header">
      <div class="section-title">Recent Branches</div>
      <a href="/f/{short}" class="section-link">View all →</a>
    </div>
    {recent_branches}
  </div>

  {contribute_form}

  <div style="margin-top:40px">
    <div class="section-label">Growing Content · {len(contribs)}</div>
    {contrib_html}
  </div>

  <div style="margin-top:40px">
    <div class="section-label">Discussion · {len(comments)}</div>
    {comment_form}
    <div class="comment-list">{comment_html}</div>
  </div>
</div>"""
    return page(user, unread_count(user["id"]) if user else 0, f["title"], body)

def render_world(user, short):
    f = get_future_by_short(short)
    if not f:
        return page(user, 0, "Not Found", '<div class="container"><div class="empty">World not found.</div></div>')
    contribs = get_contributions(f["id"])
    groups = {}
    for c in contribs: groups.setdefault(c["type"], []).append(c)
    nav_items = [
        ("#overview","Overview"), ("#history","History"), ("#people","People"),
        ("#places","Places"), ("#stories","Stories"), ("#rules","Rules"),
        ("#objects","Objects"), ("#branches","Branches")
    ]
    sidebar_nav = "".join(f'<li><a href="{href}">{label}</a></li>' for href, label in nav_items)

    # Sections
    sections = ""
    sections += f'<section class="section" id="overview"><div class="section-title">Overview</div>'
    sections += f'<div class="overview-text">{esc(f["body"]) if f["body"] else "No overview yet."}</div></section>'

    for t, label in TYPE_EN.items():
        if t not in groups: continue
        cards = ""
        for c in groups[t]:
            cards += (f'<a href="#" class="card"><div class="name">{esc(c["title"])}</div>'
                      + (f'<div class="desc">{esc(c["body"])}</div>' if c["body"] else '')
                      + '</a>')
        sections += f'<section class="section" id="{label.lower()}s"><div class="section-title">{label}s</div><div class="cards">{cards}</div></section>'

    # Timeline
    timeline_items = ""
    timeline_items += f'<div class="timeline-item"><div class="date">{rel_time(f["created_at"])}</div><div class="event">Seed created by {esc(f["creator"])}</div></div>'
    for c in sorted(contribs, key=lambda x: x["created_at"]):
        timeline_items += f'<div class="timeline-item"><div class="date">{rel_time(c["created_at"])}</div><div class="event">{esc(c["creator"])} added {TYPE_EN.get(c["type"], c["type"])}: {esc(c["title"])}</div></div>'
    timeline_html = f'<section class="section" id="history"><div class="section-title">Timeline</div><div class="timeline">{timeline_items}</div></section>'

    # Contributors
    unique_creators = {}
    for c in contribs:
        if c["creator"] not in unique_creators:
            unique_creators[c["creator"]] = c["creator"]
    contrib_items = ""
    for name in unique_creators:
        contrib_items += f'<a href="/person/{quote(name)}" class="contributor"><span class="av">{avatar_initial(name)}</span> {esc(name)}</a>'
    contributors_html = f'<section class="section"><div class="section-title">Contributors</div><div class="contributors">{contrib_items}</div></section>'

    body = f"""
<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-label">World</div>
    <ul class="nav-list">{sidebar_nav}</ul>
  </aside>
  <main class="main-content">
    <div class="world-badge">World <span>Growing</span></div>
    <h1 class="world-title">{esc(f["title"])}</h1>
    <p class="world-tagline">A future taking shape</p>
    <div class="world-meta">
      <span>From <a href="/f/{short}" style="color:inherit;text-decoration:underline"><strong>Seed {f["short_id"]}</strong></a></span>
      <span><strong>{f["views"]}</strong> views</span>
      <span><strong>{len(contribs)}</strong> contributions</span>
      <span>Since {rel_time(f["created_at"])}</span>
    </div>
    {sections}
    {timeline_html}
    {contributors_html}
    <div class="cta-box">
      <p>Help build this world.</p>
      <a href="/f/{short}" class="btn-primary" style="display:inline-block;text-decoration:none">Contribute</a>
    </div>
  </main>
</div>
<footer>duoweilai.com/world/{short}</footer>"""
    return page(user, 0, f["title"], body)

def render_person(user, username):
    started, contributions_count, worlds_count = get_creator_stats(username)
    conn = get_db()
    futures = conn.execute(
        "SELECT * FROM futures WHERE creator=? ORDER BY created_at DESC", (username,)).fetchall()
    conn.close()
    total_branches = sum(f["branches"] for f in futures)
    worlds = [f for f in futures if f["is_world"]]

    # Fetch recent activity
    recent_contribs = []
    conn = get_db()
    for c in conn.execute(
            "SELECT c.*, f.short_id FROM contributions c JOIN futures f ON f.id=c.future_id "
            "WHERE c.creator=? ORDER BY c.created_at DESC LIMIT 10", (username,)).fetchall():
        recent_contribs.append(c)
    conn.close()

    if futures:
        fut_list = ""
        for fu in futures:
            world_tag = ' <span class="world-indicator">World</span>' if fu["is_world"] else ""
            fut_list += (f'<a href="/f/{fu["short_id"]}" class="item">'
                         f'<span class="title">{esc(fu["title"])}</span>'
                         f'<span class="meta">{fu["branches"]} branches · {rel_time(fu["created_at"])}{world_tag}</span></a>')
    else:
        fut_list = '<div class="empty">No futures started yet.</div>'

    if worlds:
        world_list = ""
        for w in worlds:
            ccount = len(get_contributions(w["id"]))
            world_list += (f'<a href="/world/{w["short_id"]}" class="item">'
                          f'<span class="title">{esc(w["title"])}</span>'
                          f'<span class="meta">{ccount} contributions</span></a>')
    else:
        world_list = '<div class="empty">No worlds built yet.</div>'

    if recent_contribs:
        contrib_list = ""
        for c in recent_contribs:
            t = TYPE_EN.get(c["type"], c["type"])
            contrib_list += (f'<a href="/f/{c["short_id"]}" class="item">'
                            f'<span class="title">Added <em>{t}</em>: {esc(c["title"])}</span>'
                            f'<span class="meta">{rel_time(c["created_at"])}</span></a>')
    else:
        contrib_list = '<div class="empty">No contributions yet.</div>'

    body = f"""
<div class="container">
  <div class="profile">
    <div class="avatar-lg">{avatar_initial(username)}</div>
    <div>
      <h1 style="font-size:22px;font-weight:500;letter-spacing:-0.02em;margin-bottom:8px">{esc(username)}</h1>
      <p style="font-size:15px;color:var(--muted);margin-bottom:16px">A future explorer</p>
      <div class="stats">
        <div class="stat"><span class="stat-num">{started}</span><span class="stat-label">Futures</span></div>
        <div class="stat"><span class="stat-num">{worlds_count}</span><span class="stat-label">Worlds</span></div>
        <div class="stat"><span class="stat-num">{total_branches}</span><span class="stat-label">Branches</span></div>
        <div class="stat"><span class="stat-num">{contributions_count}</span><span class="stat-label">Contributions</span></div>
      </div>
    </div>
  </div>

  <div class="tabs">
    <button class="tab active" data-tab="futures">Futures I Started</button>
    <button class="tab" data-tab="worlds">Worlds I Helped Build</button>
    <button class="tab" data-tab="contribs">Contributions</button>
  </div>

  <div id="futures" class="tab-content">
    <div class="item-list">{fut_list}</div>
  </div>

  <div id="worlds" class="tab-content" style="display:none">
    <div class="item-list">{world_list}</div>
  </div>

  <div id="contribs" class="tab-content" style="display:none">
    <div class="item-list">{contrib_list}</div>
  </div>
</div>
<footer>duoweilai.com/person/{quote(username)}</footer>"""
    return page(user, unread_count(user["id"]) if user else 0, username, body)

def render_notifications(user):
    # user is always set due to auto-login
    notifs = get_notifications(user["id"])
    mark_notifications_read(user["id"])

    if notifs:
        items = ""
        for n in notifs:
            target = f'/f/{n["future_short_id"]}' if n["future_short_id"] else "/"
            items += (f'<a href="{target}" class="notif{" unread" if not n["is_read"] else ""}">'
                      f'<div class="dot{" read" if n["is_read"] else ""}"></div>'
                      f'<div style="flex:1"><b>{esc(n["actor_name"])}</b> {esc(n["text"])}'
                      f'<div style="font-size:12px;color:var(--subtle);margin-top:2px">{rel_time(n["created_at"])}</div></div>'
                      f'<div style="font-size:14px;color:var(--subtle)">→</div></a>')
    else:
        items = '<div class="empty">No notifications yet.</div>'

    return page(user, 0, "Notifications",
                f'<div class="container"><h1 style="font-size:20px;font-weight:500;margin-bottom:24px">Notifications</h1><div>{items}</div></div>')

# Auth pages — three simple forms: register, sign in, recover account.
def render_register(err=None, form=None):
    form = form or {}
    return page(None, 0, "Register", f"""
<div class="container" style="max-width:420px">
  <div style="text-align:center;margin-bottom:32px">
    <h1 style="font-size:24px;font-weight:500;margin-bottom:8px">Join Duoweilai</h1>
    <p style="color:var(--muted);font-size:14px">Pick an ID, set a password. One email — that's all.</p>
  </div>
  {('<div class="alert err" style="margin-bottom:16px">' + esc(err) + '</div>') if err else ''}
  <form method="post" action="/api/register" autocomplete="off">
    <label style="font-size:12px;color:var(--subtle);letter-spacing:0.05em;text-transform:uppercase;display:block;margin-bottom:6px;margin-top:14px">Your ID</label>
    <input name="username" value="{esc(form.get('username',''))}" required minlength="3" maxlength="20"
           pattern="[A-Za-z0-9_]+" title="3-20 letters, digits, underscore"
           placeholder="e.g. alice, futuremaker"
           class="text-input" style="font-size:15px">
    <div style="font-size:12px;color:var(--subtle);margin-top:4px">3–20 letters / digits / underscore. This is how people find you.</div>

    <label style="font-size:12px;color:var(--subtle);letter-spacing:0.05em;text-transform:uppercase;display:block;margin-bottom:6px;margin-top:18px">Email <span style="color:#52525b">(for account recovery only)</span></label>
    <input name="email" type="email" value="{esc(form.get('email',''))}" required
           placeholder="you@example.com" class="text-input" style="font-size:15px">

    <label style="font-size:12px;color:var(--subtle);letter-spacing:0.05em;text-transform:uppercase;display:block;margin-bottom:6px;margin-top:18px">Password</label>
    <input name="password" type="password" required minlength="6"
           placeholder="At least 6 characters" class="text-input" style="font-size:15px">

    <button type="submit" class="btn-primary" style="width:100%;margin-top:24px;padding:13px;font-size:15px">Create my account</button>
  </form>
  <div style="text-align:center;margin-top:24px;font-size:13.5px;color:var(--muted)">
    Already have an account? <a href="/login" style="color:var(--fg);text-decoration:none;border-bottom:1px solid #3f3f46">Sign in</a>
  </div>
</div>""")

def render_login(err=None, form=None):
    form = form or {}
    return page(None, 0, "Sign in", f"""
<div class="container" style="max-width:420px">
  <div style="text-align:center;margin-bottom:32px">
    <h1 style="font-size:24px;font-weight:500;margin-bottom:8px">Welcome back</h1>
    <p style="color:var(--muted);font-size:14px">Sign in to plant seeds and grow worlds.</p>
  </div>
  {('<div class="alert err" style="margin-bottom:16px">' + esc(err) + '</div>') if err else ''}
  <form method="post" action="/api/login" autocomplete="off">
    <label style="font-size:12px;color:var(--subtle);letter-spacing:0.05em;text-transform:uppercase;display:block;margin-bottom:6px">Your ID</label>
    <input name="username" value="{esc(form.get('username',''))}" required
           placeholder="Your ID" class="text-input" style="font-size:15px" autofocus>

    <label style="font-size:12px;color:var(--subtle);letter-spacing:0.05em;text-transform:uppercase;display:block;margin-bottom:6px;margin-top:18px">Password</label>
    <input name="password" type="password" required placeholder="Your password"
           class="text-input" style="font-size:15px">

    <div style="text-align:right;margin-top:8px">
      <a href="/forgot" style="font-size:12.5px;color:var(--subtle);text-decoration:none">Forgot your password?</a>
    </div>

    <button type="submit" class="btn-primary" style="width:100%;margin-top:20px;padding:13px;font-size:15px">Sign in</button>
  </form>
  <div style="text-align:center;margin-top:24px;font-size:13.5px;color:var(--muted)">
    No account yet? <a href="/register" style="color:var(--fg);text-decoration:none;border-bottom:1px solid #3f3f46">Create one</a>
  </div>
</div>""")

def render_forgot(sent_to=None, err=None):
    if sent_to:
        body = f"""
<div class="container" style="max-width:420px;text-align:center">
  <h1 style="font-size:22px;font-weight:500;margin-bottom:12px">Check your inbox</h1>
  <p style="color:var(--muted);font-size:14.5px;line-height:1.7">If an account exists for <b>{esc(sent_to)}</b>, a reset link has been sent.<br>The link expires in 2 hours.</p>
  <div style="margin-top:24px"><a href="/login" class="btn-secondary" style="text-decoration:none;display:inline-block">Back to sign in</a></div>
</div>"""
    else:
        body = f"""
<div class="container" style="max-width:420px">
  <div style="text-align:center;margin-bottom:32px">
    <h1 style="font-size:24px;font-weight:500;margin-bottom:8px">Forgot your password?</h1>
    <p style="color:var(--muted);font-size:14px">Enter the email you used when you signed up.</p>
  </div>
  {('<div class="alert err" style="margin-bottom:16px">' + esc(err) + '</div>') if err else ''}
  <form method="post" action="/api/forgot" autocomplete="off">
    <label style="font-size:12px;color:var(--subtle);letter-spacing:0.05em;text-transform:uppercase;display:block;margin-bottom:6px">Email</label>
    <input name="email" type="email" required placeholder="you@example.com"
           class="text-input" style="font-size:15px" autofocus>
    <button type="submit" class="btn-primary" style="width:100%;margin-top:20px;padding:13px;font-size:15px">Send reset link</button>
  </form>
  <div style="text-align:center;margin-top:24px;font-size:13.5px;color:var(--muted)">
    <a href="/login" style="color:var(--fg);text-decoration:none;border-bottom:1px solid #3f3f46">Back to sign in</a>
  </div>
</div>"""
    return page(None, 0, "Forgot password", body)

def render_reset(token, err=None):
    return page(None, 0, "Reset password", f"""
<div class="container" style="max-width:420px">
  <div style="text-align:center;margin-bottom:32px">
    <h1 style="font-size:24px;font-weight:500;margin-bottom:8px">Set a new password</h1>
    <p style="color:var(--muted);font-size:14px">Choose something you'll remember.</p>
  </div>
  {('<div class="alert err" style="margin-bottom:16px">' + esc(err) + '</div>') if err else ''}
  <form method="post" action="/api/reset" autocomplete="off">
    <input type="hidden" name="token" value="{esc(token)}">
    <label style="font-size:12px;color:var(--subtle);letter-spacing:0.05em;text-transform:uppercase;display:block;margin-bottom:6px">New password</label>
    <input name="password" type="password" required minlength="6" placeholder="At least 6 characters"
           class="text-input" style="font-size:15px" autofocus>
    <button type="submit" class="btn-primary" style="width:100%;margin-top:20px;padding:13px;font-size:15px">Save new password</button>
  </form>
</div>""")

def _reset_success_page():
    return page(None, 0, "Password updated", """
<div class="container" style="max-width:420px;text-align:center">
  <h1 style="font-size:22px;font-weight:500;margin-bottom:12px">Password updated</h1>
  <p style="color:var(--muted);font-size:14.5px">You can now sign in with your new password.</p>
  <div style="margin-top:24px"><a href="/login" class="btn-primary" style="text-decoration:none;display:inline-block">Go to sign in</a></div>
</div>""")

def _need_login_page(next_path="/"):
    return page(None, 0, "Sign in required", f"""
<div class="container" style="max-width:420px;text-align:center">
  <h1 style="font-size:22px;font-weight:500;margin-bottom:12px">Sign in to continue</h1>
  <p style="color:var(--muted);font-size:14.5px">Planting seeds and growing worlds needs an account. It's free and takes 30 seconds.</p>
  <div style="margin-top:24px;display:flex;gap:12px;justify-content:center">
    <a href="/register" class="btn-primary" style="text-decoration:none">Create account</a>
    <a href="/login" class="btn-secondary" style="text-decoration:none">Sign in</a>
  </div>
</div>""")

def log_password_reset(user, reset_url):
    """Print the reset link so an operator can forward it manually.
    Wired up via env vars (DUOWEILAI_SMTP_*) for real sending when ready."""
    host = os.environ.get("DUOWEILAI_SMTP_HOST", "")
    if host:
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(
                f"Hello {user['username']},\n\n"
                f"Someone (hopefully you) asked to reset the password for your Duoweilai account.\n\n"
                f"Reset link (valid for 2 hours): {reset_url}\n\n"
                f"If you didn't ask for this, you can safely ignore this email.\n\n"
                f"— Duoweilai")
            msg["Subject"] = "Reset your Duoweilai password"
            msg["From"] = os.environ.get("DUOWEILAI_SMTP_FROM", "no-reply@duoweilai.com")
            msg["To"] = user["email"]
            port = int(os.environ.get("DUOWEILAI_SMTP_PORT", "587"))
            user_s = os.environ.get("DUOWEILAI_SMTP_USER", "")
            pw = os.environ.get("DUOWEILAI_SMTP_PASSWORD", "")
            with smtplib.SMTP(host, port, timeout=10) as s:
                s.starttls()
                if user_s: s.login(user_s, pw)
                s.send_message(msg)
            return True
        except Exception as e:
            print(f"  [reset-mail] SMTP failed for {user['email']}: {e}")
    # Always log to console + file so the reset URL is recoverable.
    line = (f"\n  [reset-mail] To: {user['email']} ({user['username']})\n"
            f"  [reset-mail] Link: {reset_url}\n")
    print(line, flush=True)
    try:
        with open("reset_link.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception: pass
    return False

# Old redirect stub kept for reference — no longer used now that real auth exists.
def _redirect(loc):
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0;url={loc}"></head><body>'
            f'<a href="{loc}">Redirecting…</a></body></html>')

# -------------------------------------------------
# Handler
# -------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "Duoweilai/0.4"
    protocol_version = "HTTP/1.1"

    def setup(self):
        self._cookies = []
        super().setup()

    def log_message(self, fmt, *args): pass

    def current_user(self):
        """Return the authenticated user, or None if not signed in.
        Real account system: username + password, no auto-login."""
        cookie = self.headers.get("Cookie", "")
        sc = SimpleCookie(); sc.load(cookie)
        tok = sc.get("duoweilai_session")
        if not tok: return None
        user = get_user_by_session(tok.value)
        return user

    def set_session_cookie(self, token):
        sc = SimpleCookie()
        sc["duoweilai_session"] = token
        sc["duoweilai_session"]["path"] = "/"
        sc["duoweilai_session"]["max-age"] = 2592000
        sc["duoweilai_session"]["httponly"] = True
        sc["duoweilai_session"]["samesite"] = "Lax"
        if SECURE_COOKIE: sc["duoweilai_session"]["secure"] = True
        self._cookies.append(sc.output(header="").strip())

    def clear_session_cookie(self):
        self._cookies.append("duoweilai_session=; Path=/; Max-Age=0")

    def _flush_cookies(self):
        for c in self._cookies:
            self.send_header("Set-Cookie", c)
        self._cookies = []

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY: raise ValueError("Request body too large")
        return parse_qs(self.rfile.read(length).decode("utf-8") if length else "")

    def send_html(self, html):
        payload = html.encode("utf-8")
        self.send_response(200)
        self._flush_cookies()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, obj, status=200):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._flush_cookies()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_redirect(self, loc):
        self.send_response(302)
        self._flush_cookies()
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        init_db()
        user = self.current_user()
        path = urlparse(self.path).path
        uc = unread_count(user["id"]) if user else 0

        if path == "/":        return self.send_html(render_home(user))
        if path == "/explore": return self.send_html(render_explore(user))
        if path == "/login":
            if user: return self.send_redirect("/")
            return self.send_html(render_login())
        if path == "/register":
            if user: return self.send_redirect("/")
            return self.send_html(render_register())
        if path == "/forgot":
            return self.send_html(render_forgot())
        m = re.fullmatch(r"/reset/([A-Fa-f0-9]+)", path)
        if m:
            return self.send_html(render_reset(m.group(1)))
        if path == "/logout":
            cookie = self.headers.get("Cookie", "")
            sc = SimpleCookie(); sc.load(cookie)
            tok = sc.get("duoweilai_session")
            if tok: delete_session(tok.value)
            self.clear_session_cookie()
            return self.send_redirect("/")
        if path == "/notifications":
            if not user: return self.send_redirect("/login")
            return self.send_html(render_notifications(user))
        if path.startswith("/f/"):   return self.send_html(render_seed(user, path[3:]))
        if path.startswith("/world/"):return self.send_html(render_world(user, path[7:]))
        if path.startswith("/person/"):return self.send_html(render_person(user, unquote(path[8:])))
        if path == "/api/notifications/read":
            if user: mark_notifications_read(user["id"])
            return self.send_json({"ok": True})

        self.send_html(page(user, uc, "404",
                            '<div class="container"><div class="empty">Page not found.</div></div>'))

    def do_POST(self):
        init_db()
        user = self.current_user()
        path = urlparse(self.path).path
        try: data = self.read_body()
        except ValueError: return self.send_json({"ok": False, "error": "Body too large"}, 413)
        f = lambda k: (data.get(k, [""])[0]).strip()

        # ----- Auth endpoints -----
        import re as _re
        def valid_username(u):
            return bool(u) and 3 <= len(u) <= 20 and _re.fullmatch(r"[A-Za-z0-9_]+", u)
        def valid_email(e):
            return bool(e) and '@' in e and '.' in e.split('@')[-1] and len(e) <= 254
        def re_render_login(err, form):
            self.send_html(render_login(err, form))
        def re_render_register(err, form):
            self.send_html(render_register(err, form))

        if path == "/api/register":
            username = f("username"); email = f("email"); password = f("password")
            form = {"username": username, "email": email}
            if not valid_username(username):
                return self.send_html(render_register("ID must be 3–20 letters, digits, or underscore.", form))
            if not valid_email(email):
                return self.send_html(render_register("Please enter a valid email.", form))
            if len(password) < 6:
                return self.send_html(render_register("Password must be at least 6 characters.", form))
            # Check uniqueness explicitly for cleaner error messages
            if get_user_by_username(username):
                return self.send_html(render_register("That ID is already taken — pick another.", form))
            if get_user_by_email(email):
                return self.send_html(render_register("That email is already registered. Try signing in or using a different email.", form))
            uid = create_user(username, password, email)
            if not uid:
                return self.send_html(render_register("Could not create account — please try a different ID or email.", form))
            # Welcome notification
            add_notification(uid, uid, "welcome", None, f"Welcome to Duoweilai, {username}!")
            # Log them in
            token = create_session(uid)
            self.set_session_cookie(token)
            return self.send_redirect("/")

        if path == "/api/login":
            username = f("username"); password = f("password")
            form = {"username": username}
            if not username or not password:
                return self.send_html(render_login("Enter your ID and password.", form))
            uid = authenticate(username, password)
            if not uid:
                return self.send_html(render_login("ID or password is incorrect.", form))
            token = create_session(uid)
            self.set_session_cookie(token)
            return self.send_redirect("/")

        if path == "/api/logout":
            cookie = self.headers.get("Cookie", "")
            sc = SimpleCookie(); sc.load(cookie)
            tok = sc.get("duoweilai_session")
            if tok: delete_session(tok.value)
            self.clear_session_cookie()
            return self.send_redirect("/")

        if path == "/api/forgot":
            email = f("email")
            if not email:
                return self.send_html(render_forgot(err="Please enter your email."))
            target = get_user_by_email(email)
            if target:
                token = create_password_reset(target["id"])
                reset_url = f"/reset/{token}"
                log_password_reset(target, reset_url)
            # Always show success to avoid revealing whether an account exists
            return self.send_html(render_forgot(sent_to=email))

        m = re.fullmatch(r"/api/reset/([A-Fa-f0-9]+)", path)
        if not m and path == "/api/reset":
            m = re.match(r"/api/reset/([A-Fa-f0-9]+)", f("token"))
        if m:
            token = m.group(1); password = f("password")
            if len(password) < 6:
                return self.send_html(render_reset(token, err="Password must be at least 6 characters."))
            if not get_password_reset(token):
                return self.send_html(render_reset(token, err="This reset link is invalid or has expired."))
            consume_password_reset(token, password)
            return self.send_html(_reset_success_page())

        # All endpoints below require login
        if not user:
            return self.send_html(_need_login_page())

        if path == "/api/future":
            title = f("title")
            if not title: return self.send_json({"ok": False, "error": "Title required"}, 400)
            short = create_future(title, f("body"), user["username"], user["id"],
                                  category=f("category") or "Unknown")
            self.send_redirect(f"/f/{short}"); return

        if path == "/api/contribute":
            future_id, ctype, title = f("future_id"), f("type"), f("title")
            if ctype not in TYPE_EN:
                return self.send_json({"ok": False, "error": "Invalid type"}, 400)
            if not title: return self.send_json({"ok": False, "error": "Title required"}, 400)
            target = get_future_by_short(future_id)
            if not target: return self.send_json({"ok": False, "error": "Future not found"}, 404)
            add_contribution(target["id"], ctype, title, f("body"), user["username"], user["id"])
            maybe_make_world(future_id)
            if target["creator_id"] and target["creator_id"] != user["id"]:
                t = TYPE_EN.get(ctype, ctype)
                add_notification(target["creator_id"], user["id"], "contribute", future_id,
                                 f'contributed a {t}: {title}')
            self.send_redirect(f"/f/{future_id}"); return

        if path == "/api/comment":
            future_id, body = f("future_id"), f("body")
            if not body: return self.send_json({"ok": False, "error": "Comment body required"}, 400)
            target = get_future_by_short(future_id)
            if not target: return self.send_json({"ok": False, "error": "Future not found"}, 404)
            parent_id = int(f("parent_id")) if f("parent_id") else None
            add_comment(target["id"], None, parent_id, user["id"], body)
            if target["creator_id"] and target["creator_id"] != user["id"]:
                add_notification(target["creator_id"], user["id"], "comment", future_id,
                                 "commented on your future")
            self.send_redirect(f"/f/{future_id}"); return

        # ----- Delete endpoints (login required, checked above) -----
        # POST /api/future/<short>/delete — owner only, removes the seed and
        # its contributions/comments.
        m = re.fullmatch(r"/api/future/([A-Za-z0-9_-]+)/delete", path)
        if m:
            target = get_future_by_short(m.group(1))
            if not target: return self.send_json({"ok": False, "error": "Not found"}, 404)
            if target["creator_id"] != user["id"]:
                return self.send_json({"ok": False, "error": "Only the seed creator can delete it"}, 403)
            delete_future(m.group(1))
            return self.send_json({"ok": True, "redirect": "/"})

        # POST /api/contribution/<id>/delete — author only
        m = re.fullmatch(r"/api/contribution/(\d+)/delete", path)
        if m:
            cid = int(m.group(1))
            owner = get_contribution_author(cid)
            if not owner: return self.send_json({"ok": False, "error": "Not found"}, 404)
            if owner["author_id"] != user["id"]:
                return self.send_json({"ok": False, "error": "Only the author can delete this"}, 403)
            short = delete_contribution(cid)
            return self.send_json({"ok": True, "redirect": f"/f/{short}" if short else "/"})

        # POST /api/comment/<id>/delete — author only
        m = re.fullmatch(r"/api/comment/(\d+)/delete", path)
        if m:
            cid = int(m.group(1))
            owner = get_comment_author(cid)
            if not owner: return self.send_json({"ok": False, "error": "Not found"}, 404)
            if owner["author_id"] != user["id"]:
                return self.send_json({"ok": False, "error": "Only the author can delete this"}, 403)
            delete_comment(cid)
            return self.send_json({"ok": True})

        self.send_json({"ok": False, "error": "Unknown endpoint"}, 404)

# -------------------------------------------------
def main():
    init_db()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    srv.daemon_threads = True
    local = "127.0.0.1" if BIND == "127.0.0.1" else BIND
    print(f"\n  Duoweilai v0.4  —  http://{local}:{PORT}")
    print(f"  Database: {DB_PATH}")
    print(f"  Bind: {BIND}  Port: {PORT}\n")
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\n  Stopped.")

if __name__ == "__main__": main()
