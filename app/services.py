"""Business logic: futures, contributions, comments, notifications, feed.

Ported from the v0.5 single-file server (stdlib http.server). New here:
server-side search + pagination, seed branches (parent_short_id), edits
(edited_at), and a force flag so the welcome notification isn't skipped.
All functions use the per-request connection from app.db — no open/close.
"""

import os
import random
import sqlite3
import uuid
from datetime import datetime, timezone

from .db import get_db

TYPE_EN = {
    "people": "People",
    "place": "Place",
    "story": "Story",
    "rule": "Rule",
    "object": "Object",
    "branch": "Branch",
}

CATEGORIES = [
    "Unknown",
    "Life",
    "Cities",
    "Education",
    "Culture",
    "Relationships",
    "Work",
    "Civilization",
    "Technology",
]

SHORT_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# -------------------------------------------------
# Time / display helpers (registered as template globals)
# -------------------------------------------------
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
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    if s < 86400 * 30:
        return f"{s // 86400}d ago"
    return t.strftime("%d %b %Y")


def avatar_initial(username):
    return username[0].upper() if username else "?"


def normalize_category(cat):
    return cat if cat in CATEGORIES else "Unknown"


# -------------------------------------------------
# Futures
# -------------------------------------------------
def gen_short_id():
    return "".join(random.choice(SHORT_ID_ALPHABET) for _ in range(5))


def create_future(title, body, creator, creator_id, category="Unknown", parent_short_id=None):
    """Insert a seed; retry on the (astronomically rare) short_id clash."""
    db = get_db()
    for _ in range(8):
        short, fid = gen_short_id(), str(uuid.uuid4())
        try:
            db.execute(
                "INSERT INTO futures (id,short_id,title,body,category,creator,"
                "creator_id,created_at,parent_short_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    fid,
                    short,
                    title,
                    body,
                    category,
                    creator,
                    creator_id,
                    now_iso(),
                    parent_short_id,
                ),
            )
            db.commit()
            return short
        except sqlite3.IntegrityError:
            db.rollback()
    return None


def get_future_by_short(short):
    return get_db().execute("SELECT * FROM futures WHERE short_id=?", (short,)).fetchone()


def inc_views(short):
    db = get_db()
    db.execute("UPDATE futures SET views=views+1 WHERE short_id=?", (short,))
    db.commit()


def list_futures(limit=100):
    """Legacy: newest N seeds (home page, world checks)."""
    return (
        get_db()
        .execute("SELECT * FROM futures ORDER BY created_at DESC LIMIT ?", (limit,))
        .fetchall()
    )


def search_futures(page=1, per_page=100, category=None, q=None):
    """Explore: category filter + escaped LIKE search + LIMIT/OFFSET paging.
    Returns (rows, total)."""
    where, params = [], []
    if category and category != "All":
        where.append("category=?")
        params.append(category)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
        params += [like, like]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM futures {clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM futures {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*params, per_page, (page - 1) * per_page],
    ).fetchall()
    return rows, total


def get_child_branches(parent_short_id, limit=5):
    """Seeds branched off this one (the new Branch feature)."""
    return (
        get_db()
        .execute(
            "SELECT * FROM futures WHERE parent_short_id=? ORDER BY created_at DESC LIMIT ?",
            (parent_short_id, limit),
        )
        .fetchall()
    )


def edit_future(short, title, body, category):
    db = get_db()
    db.execute(
        "UPDATE futures SET title=?, body=?, category=?, edited_at=? WHERE short_id=?",
        (title, body, category, now_iso(), short),
    )
    db.commit()


def delete_future(short):
    """Owner-only seed deletion: removes the seed + all contributions/comments."""
    db = get_db()
    f = db.execute("SELECT id FROM futures WHERE short_id=?", (short,)).fetchone()
    if not f:
        return False
    fid = f["id"]
    db.execute("DELETE FROM comments     WHERE future_id=?", (fid,))
    db.execute("DELETE FROM contributions WHERE future_id=?", (fid,))
    db.execute("DELETE FROM futures       WHERE id=?", (fid,))
    db.commit()
    return True


def get_futures_by_creator(username):
    return (
        get_db()
        .execute("SELECT * FROM futures WHERE creator=? ORDER BY created_at DESC", (username,))
        .fetchall()
    )


def get_creator_stats(username):
    db = get_db()
    started = db.execute("SELECT COUNT(*) FROM futures WHERE creator=?", (username,)).fetchone()[0]
    contributions = db.execute(
        "SELECT COUNT(*) FROM contributions WHERE creator=?", (username,)
    ).fetchone()[0]
    worlds = db.execute(
        "SELECT COUNT(*) FROM futures WHERE creator=? AND is_world=1", (username,)
    ).fetchone()[0]
    return started, contributions, worlds


# -------------------------------------------------
# Contributions
# -------------------------------------------------
def get_contributions(future_id):
    return (
        get_db()
        .execute(
            "SELECT * FROM contributions WHERE future_id=? ORDER BY created_at ASC", (future_id,)
        )
        .fetchall()
    )


def get_contribution(cid):
    return get_db().execute("SELECT * FROM contributions WHERE id=?", (cid,)).fetchone()


def add_contribution(future_id, ctype, title, body, creator, author_id):
    db = get_db()
    cur = db.execute(
        "INSERT INTO contributions (future_id,type,title,body,creator,author_id,created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (future_id, ctype, title, body, creator, author_id, now_iso()),
    )
    db.execute("UPDATE futures SET branches=branches+1 WHERE id=?", (future_id,))
    db.commit()
    return cur.lastrowid


def maybe_make_world(short):
    db = get_db()
    f = db.execute("SELECT * FROM futures WHERE short_id=?", (short,)).fetchone()
    if not f:
        return
    cnt = db.execute("SELECT COUNT(*) FROM contributions WHERE future_id=?", (f["id"],)).fetchone()[
        0
    ]
    if cnt >= 5 and not f["is_world"]:
        db.execute("UPDATE futures SET is_world=1 WHERE id=?", (f["id"],))
        db.commit()


def edit_contribution(cid, title, body):
    db = get_db()
    db.execute(
        "UPDATE contributions SET title=?, body=?, edited_at=? WHERE id=?",
        (title, body, now_iso(), cid),
    )
    db.commit()


def get_contribution_author(cid):
    """Join row: author_id + future short_id, for the delete/edit owner check."""
    return (
        get_db()
        .execute(
            "SELECT c.author_id, c.future_id, f.short_id "
            "FROM contributions c JOIN futures f ON f.id=c.future_id "
            "WHERE c.id=?",
            (cid,),
        )
        .fetchone()
    )


def delete_contribution(cid):
    """Returns the parent future's short_id for the redirect."""
    db = get_db()
    row = db.execute("SELECT future_id FROM contributions WHERE id=?", (cid,)).fetchone()
    if not row:
        return None
    fid = row["future_id"]
    db.execute("DELETE FROM contributions WHERE id=?", (cid,))
    db.execute("UPDATE futures SET branches = MAX(0, branches-1) WHERE id=?", (fid,))
    short_row = db.execute("SELECT short_id FROM futures WHERE id=?", (fid,)).fetchone()
    db.commit()
    return short_row["short_id"] if short_row else None


def get_contributions_by_creator(username, limit=10):
    return (
        get_db()
        .execute(
            "SELECT c.*, f.short_id FROM contributions c JOIN futures f ON f.id=c.future_id "
            "WHERE c.creator=? ORDER BY c.created_at DESC LIMIT ?",
            (username, limit),
        )
        .fetchall()
    )


# -------------------------------------------------
# Comments
# -------------------------------------------------
def add_comment(future_id, contribution_id, parent_id, author_id, body):
    db = get_db()
    cur = db.execute(
        "INSERT INTO comments (future_id,contribution_id,parent_id,author_id,body,created_at)"
        " VALUES (?,?,?,?,?,?)",
        (future_id, contribution_id, parent_id, author_id, body, now_iso()),
    )
    db.commit()
    return cur.lastrowid


def get_comments(future_id):
    return (
        get_db()
        .execute(
            "SELECT c.*, u.username FROM comments c LEFT JOIN users u ON u.id=c.author_id "
            "WHERE c.future_id=? ORDER BY c.created_at ASC",
            (future_id,),
        )
        .fetchall()
    )


def get_comment(cid):
    return get_db().execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()


def edit_comment(cid, body):
    db = get_db()
    db.execute("UPDATE comments SET body=?, edited_at=? WHERE id=?", (body, now_iso(), cid))
    db.commit()


def get_comment_author(cid):
    row = get_db().execute("SELECT author_id FROM comments WHERE id=?", (cid,)).fetchone()
    return row


def delete_comment(cid):
    """Delete the comment + its replies."""
    db = get_db()
    db.execute("DELETE FROM comments WHERE id=? OR parent_id=?", (cid, cid))
    db.commit()


# -------------------------------------------------
# Notifications
# -------------------------------------------------
def add_notification(user_id, actor_id, ntype, short, text, force=False):
    """Self-notifications are skipped — except the welcome message (force)."""
    if user_id == actor_id and not force:
        return
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_id,actor_id,type,future_short_id,text,created_at)"
        " VALUES (?,?,?,?,?,?)",
        (user_id, actor_id, ntype, short, text, now_iso()),
    )
    db.commit()


def get_notifications(user_id):
    return (
        get_db()
        .execute(
            "SELECT n.*, u.username AS actor_name FROM notifications n "
            "LEFT JOIN users u ON u.id=n.actor_id WHERE n.user_id=? "
            "ORDER BY n.created_at DESC LIMIT 100",
            (user_id,),
        )
        .fetchall()
    )


def unread_count(user_id):
    return (
        get_db()
        .execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user_id,))
        .fetchone()[0]
    )


def mark_notifications_read(user_id):
    db = get_db()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user_id,))
    db.commit()


# -------------------------------------------------
# Feed
# -------------------------------------------------
def get_feed(limit=30):
    """Merged activity stream (futures + contributions + comments)."""
    db = get_db()
    items = []
    for f in db.execute("SELECT * FROM futures ORDER BY created_at DESC LIMIT 200"):
        items.append(
            {
                "kind": "future",
                "time": f["created_at"],
                "actor": f["creator"],
                "short": f["short_id"],
                "text": f["title"],
                "type": None,
            }
        )
    for c in db.execute(
        "SELECT c.*, f.short_id FROM contributions c JOIN futures f ON f.id=c.future_id "
        "ORDER BY c.created_at DESC LIMIT 200"
    ):
        items.append(
            {
                "kind": "contribution",
                "time": c["created_at"],
                "actor": c["creator"],
                "short": c["short_id"],
                "text": c["title"],
                "type": c["type"],
            }
        )
    for cm in db.execute(
        "SELECT cm.*, u.username, f.short_id FROM comments cm "
        "LEFT JOIN users u ON u.id=cm.author_id JOIN futures f ON f.id=cm.future_id "
        "ORDER BY cm.created_at DESC LIMIT 200"
    ):
        items.append(
            {
                "kind": "comment",
                "time": cm["created_at"],
                "actor": cm["username"] or "Anonymous",
                "short": cm["short_id"],
                "text": cm["body"],
                "type": None,
            }
        )
    items.sort(key=lambda x: x["time"], reverse=True)
    return items[:limit]


# -------------------------------------------------
# Password reset mail
# -------------------------------------------------
def log_password_reset(user, reset_url):
    """Send the reset link via SMTP when configured; always also log it to
    console + reset_link.log so an operator can forward it manually."""
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
                f"— Duoweilai"
            )
            msg["Subject"] = "Reset your Duoweilai password"
            msg["From"] = os.environ.get("DUOWEILAI_SMTP_FROM", "no-reply@duoweilai.com")
            msg["To"] = user["email"]
            port = int(os.environ.get("DUOWEILAI_SMTP_PORT", "587"))
            user_s = os.environ.get("DUOWEILAI_SMTP_USER", "")
            pw = os.environ.get("DUOWEILAI_SMTP_PASSWORD", "")
            with smtplib.SMTP(host, port, timeout=10) as s:
                s.starttls()
                if user_s:
                    s.login(user_s, pw)
                s.send_message(msg)
            return True
        except Exception as e:
            print(f"  [reset-mail] SMTP failed for {user['email']}: {e}")
    line = (
        f"\n  [reset-mail] To: {user['email']} ({user['username']})\n"
        f"  [reset-mail] Link: {reset_url}\n"
    )
    print(line, flush=True)
    try:
        with open("reset_link.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    return False
