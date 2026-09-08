#!/usr/bin/env python3
"""
Duoweilai — First Principles Prototype (v0.2)
Core loop: Publish a Future Seed → Get permanent link → Explore deeper → Build identity through creation
"""

import sqlite3
import json
import uuid
import random
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote, quote
from datetime import datetime, timezone
from pathlib import Path
from http.cookies import SimpleCookie

# -------------------------------------------------
# Config
# -------------------------------------------------
PORT = 8080
DB_PATH = Path(__file__).parent / "duoweilai.db"
BASE_URL = f"http://localhost:{PORT}"

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
            id          TEXT PRIMARY KEY,
            short_id    TEXT UNIQUE NOT NULL,
            title       TEXT NOT NULL,
            body        TEXT NOT NULL,
            creator     TEXT NOT NULL DEFAULT 'Anonymous',
            created_at  TEXT NOT NULL,
            branches    INTEGER DEFAULT 0,
            views       INTEGER DEFAULT 0,
            is_world    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS contributions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            future_id   TEXT NOT NULL,
            type        TEXT NOT NULL,
            title       TEXT NOT NULL,
            body        TEXT,
            creator     TEXT NOT NULL DEFAULT 'Anonymous',
            created_at  TEXT NOT NULL,
            FOREIGN KEY (future_id) REFERENCES futures(id)
        );

        CREATE INDEX IF NOT EXISTS idx_futures_short ON futures(short_id);
        CREATE INDEX IF NOT EXISTS idx_futures_creator ON futures(creator);
        CREATE INDEX IF NOT EXISTS idx_contrib_future ON contributions(future_id);
        CREATE INDEX IF NOT EXISTS idx_contrib_creator ON contributions(creator);
    """)
    # migration for existing DBs
    try:
        conn.execute("ALTER TABLE futures ADD COLUMN is_world INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    conn.close()

def generate_short_id():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(5))

def create_future(title: str, body: str, creator: str = "Anonymous") -> dict:
    conn = get_db()
    short_id = generate_short_id()
    while conn.execute("SELECT 1 FROM futures WHERE short_id = ?", (short_id,)).fetchone():
        short_id = generate_short_id()

    future_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    if not title:
        title = body.strip().split("\n")[0][:100]
        if len(body.strip()) > 100:
            title = title.rstrip(".,;:!?") + "…"

    conn.execute(
        "INSERT INTO futures (id, short_id, title, body, creator, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (future_id, short_id, title, body, creator, now)
    )
    conn.commit()
    conn.close()
    return {"id": future_id, "short_id": short_id, "title": title}

def get_future_by_short(short_id: str, inc_view=True):
    conn = get_db()
    row = conn.execute("SELECT * FROM futures WHERE short_id = ?", (short_id.upper(),)).fetchone()
    if row and inc_view:
        conn.execute("UPDATE futures SET views = views + 1 WHERE short_id = ?", (short_id.upper(),))
        conn.commit()
    conn.close()
    return dict(row) if row else None

def list_futures(limit=30):
    conn = get_db()
    rows = conn.execute(
        "SELECT short_id, title, creator, created_at, branches, views, is_world FROM futures ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_contributions(future_id: str, type_filter=None):
    conn = get_db()
    if type_filter:
        rows = conn.execute(
            "SELECT * FROM contributions WHERE future_id = ? AND type = ? ORDER BY created_at DESC",
            (future_id, type_filter)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM contributions WHERE future_id = ? ORDER BY created_at DESC",
            (future_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_contribution(future_id: str, type_: str, title: str, body: str = "", creator: str = "Anonymous"):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO contributions (future_id, type, title, body, creator, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (future_id, type_, title, body, creator, now)
    )
    if type_ == "branches":
        conn.execute("UPDATE futures SET branches = branches + 1 WHERE id = ?", (future_id,))
    # Auto-promote to World when it has enough substance
    counts = conn.execute(
        "SELECT COUNT(*) FROM contributions WHERE future_id = ?", (future_id,)
    ).fetchone()[0]
    if counts >= 5:
        conn.execute("UPDATE futures SET is_world = 1 WHERE id = ?", (future_id,))
    conn.commit()
    conn.close()

def get_creator_stats(name: str):
    conn = get_db()
    futures = conn.execute(
        "SELECT short_id, title, created_at, branches, is_world FROM futures WHERE creator = ? ORDER BY created_at DESC",
        (name,)
    ).fetchall()
    contribs = conn.execute(
        "SELECT c.*, f.short_id, f.title as future_title FROM contributions c "
        "JOIN futures f ON c.future_id = f.id WHERE c.creator = ? ORDER BY c.created_at DESC LIMIT 50",
        (name,)
    ).fetchall()
    worlds = conn.execute(
        "SELECT short_id, title, branches FROM futures WHERE creator = ? AND is_world = 1",
        (name,)
    ).fetchall()
    # Also count worlds they contributed to
    helped_worlds = conn.execute(
        "SELECT DISTINCT f.short_id, f.title, f.branches FROM futures f "
        "JOIN contributions c ON c.future_id = f.id "
        "WHERE c.creator = ? AND f.is_world = 1 AND f.creator != ?",
        (name, name)
    ).fetchall()
    conn.close()
    return {
        "futures": [dict(r) for r in futures],
        "contributions": [dict(r) for r in contribs],
        "worlds_started": [dict(r) for r in worlds],
        "worlds_helped": [dict(r) for r in helped_worlds],
        "stats": {
            "futures": len(futures),
            "worlds": len(worlds),
            "branches": sum(1 for c in contribs if c["type"] == "branches"),
            "contributions": len(contribs),
        }
    }

def get_all_creators():
    conn = get_db()
    rows = conn.execute(
        "SELECT creator, COUNT(*) as cnt FROM futures GROUP BY creator ORDER BY cnt DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def esc(s):
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

def format_date(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except Exception:
        return (iso or "")[:10]

def format_relative(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        if secs < 604800:
            return f"{secs // 86400}d ago"
        return format_date(iso)
    except Exception:
        return format_date(iso)

# -------------------------------------------------
# Shared CSS
# -------------------------------------------------
COMMON_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Noto+Sans+SC:wght@300;400;500&display=swap');
:root {
  --bg:#0a0a0b; --fg:#f4f4f5; --muted:#a1a1aa; --subtle:#71717a;
  --border:#27272a; --card:#111113; --hover:#18181b; --input-bg:#18181b;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:'Inter','Noto Sans SC',system-ui,sans-serif;
  background:var(--bg); color:var(--fg); min-height:100vh;
  display:flex; flex-direction:column; line-height:1.5;
}
header {
  padding:20px 32px; display:flex; justify-content:space-between; align-items:center;
  border-bottom:1px solid transparent; position:sticky; top:0; z-index:50;
  background:rgba(10,10,11,0.88); backdrop-filter:blur(12px);
}
.logo { font-size:14px; font-weight:500; letter-spacing:0.12em; text-transform:uppercase; color:var(--fg); text-decoration:none; }
.nav { display:flex; gap:20px; align-items:center; }
.nav a { font-size:13px; color:var(--muted); text-decoration:none; transition:color .2s; }
.nav a:hover, .nav a.active { color:var(--fg); }
.identity {
  font-size:13px; color:var(--muted); display:flex; align-items:center; gap:8px;
}
.identity a { color:var(--fg); text-decoration:none; border-bottom:1px solid #3f3f46; }
.identity button {
  background:transparent; border:1px solid var(--border); color:var(--muted);
  border-radius:999px; padding:5px 12px; font-size:12px; cursor:pointer; font-family:inherit;
}
.identity button:hover { color:var(--fg); border-color:#3f3f46; }
footer { padding:28px 32px; text-align:center; font-size:12px; color:#3f3f46; margin-top:auto; }
@media (max-width:640px) {
  header { padding:14px 16px; }
  .nav { gap:12px; }
}
"""

def header_html(current_user=None, active=""):
    identity = ""
    if current_user and current_user != "Anonymous":
        identity = f'''
        <div class="identity">
          <a href="/person/{quote(current_user)}">{esc(current_user)}</a>
          <button onclick="clearIdentity()">切换</button>
        </div>'''
    else:
        identity = '''
        <div class="identity">
          <button onclick="setIdentity()">设置名字</button>
        </div>'''

    return f'''
    <header>
      <a href="/" class="logo">Duoweilai</a>
      <div class="nav">
        <a href="/explore" class="{'active' if active=='explore' else ''}">Explore</a>
        <a href="/" class="{'active' if active=='create' else ''}">Create</a>
        {identity}
      </div>
    </header>
    <script>
      function setIdentity() {{
        const name = prompt("你的名字（用于署名创造）");
        if (name && name.trim()) {{
          document.cookie = "duoweilai_name=" + encodeURIComponent(name.trim()) + "; path=/; max-age=31536000";
          location.reload();
        }}
      }}
      function clearIdentity() {{
        document.cookie = "duoweilai_name=; path=/; max-age=0";
        location.reload();
      }}
    </script>
    '''

# -------------------------------------------------
# Page Renderers
# -------------------------------------------------
def render_home(futures, current_user):
    seeds_html = ""
    for f in futures:
        world_badge = ' <span style="font-size:11px;color:#71717a;">· World</span>' if f.get("is_world") else ""
        seeds_html += f'''
        <a href="/f/{f['short_id']}" class="seed-card">
          <div class="title">{esc(f['title'])}{world_badge}</div>
          <div class="meta">{esc(f['creator'])} · {format_relative(f['created_at'])} · {f['branches']} branches</div>
        </a>'''

    user_value = current_user if current_user != "Anonymous" else ""

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Duoweilai — What future do you imagine?</title>
  <style>{COMMON_CSS}
    main {{ flex:1; display:flex; flex-direction:column; justify-content:center; align-items:center; padding:40px 24px 80px; max-width:720px; margin:0 auto; width:100%; }}
    .hero {{ text-align:center; margin-bottom:40px; }}
    .hero h1 {{ font-size:clamp(28px,5vw,36px); font-weight:400; letter-spacing:-0.02em; margin-bottom:12px; }}
    .hero p {{ font-size:16px; color:var(--muted); font-weight:300; }}
    .seed-form {{ width:100%; }}
    .input-wrapper {{ background:var(--input-bg); border:1px solid var(--border); border-radius:16px; padding:20px 20px 16px; transition:border-color .2s; }}
    .input-wrapper:focus-within {{ border-color:#3f3f46; box-shadow:0 0 0 4px rgba(255,255,255,0.03); }}
    textarea {{ width:100%; background:transparent; border:none; outline:none; color:var(--fg); font-size:17px; font-family:inherit; resize:none; min-height:110px; line-height:1.6; }}
    textarea::placeholder {{ color:#52525b; }}
    .form-footer {{ display:flex; justify-content:space-between; align-items:center; margin-top:12px; gap:12px; flex-wrap:wrap; }}
    .hint {{ font-size:13px; color:#52525b; }}
    .name-input {{ background:var(--input-bg); border:1px solid var(--border); border-radius:8px; padding:6px 12px; color:var(--fg); font-size:13px; font-family:inherit; width:140px; }}
    button.publish {{ background:var(--fg); color:var(--bg); border:none; border-radius:999px; padding:10px 22px; font-size:14px; font-weight:500; cursor:pointer; font-family:inherit; }}
    button.publish:hover {{ opacity:.9; }}
    button.publish:disabled {{ opacity:.4; cursor:not-allowed; }}
    .seeds-section {{ margin-top:80px; width:100%; }}
    .seeds-label {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:#52525b; margin-bottom:20px; text-align:center; }}
    .seeds-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px; }}
    .seed-card {{ background:transparent; border:1px solid var(--border); border-radius:12px; padding:18px 20px; text-decoration:none; color:inherit; transition:all .2s; display:block; }}
    .seed-card:hover {{ border-color:#3f3f46; background:rgba(255,255,255,0.02); }}
    .seed-card .title {{ font-size:15px; margin-bottom:6px; line-height:1.4; }}
    .seed-card .meta {{ font-size:12px; color:#71717a; }}
    .result {{ display:none; text-align:center; animation:fadeIn .4s ease; }}
    .result.show {{ display:block; }}
    .result .label {{ font-size:13px; color:var(--muted); margin-bottom:12px; }}
    .result .url {{ font-size:18px; font-weight:500; margin-bottom:24px; word-break:break-all; }}
    .result .url a {{ color:var(--fg); text-decoration:none; border-bottom:1px solid #3f3f46; }}
    .result .actions {{ display:flex; gap:12px; justify-content:center; flex-wrap:wrap; }}
    .result button {{ background:transparent; border:1px solid var(--border); color:var(--fg); border-radius:999px; padding:9px 18px; font-size:13px; cursor:pointer; font-family:inherit; }}
    @keyframes fadeIn {{ from{{opacity:0;transform:translateY(8px)}} to{{opacity:1;transform:translateY(0)}} }}
  </style>
</head>
<body>
  {header_html(current_user, "create")}
  <main>
    <div class="hero" id="hero">
      <h1>What future do you imagine?</h1>
      <p>写下你想象的未来，它会成为一颗永久的种子。</p>
    </div>
    <div class="seed-form" id="form">
      <div class="input-wrapper">
        <textarea id="futureInput" placeholder="Describe a future..." rows="4"></textarea>
        <div class="form-footer">
          <div style="display:flex;align-items:center;gap:10px;">
            <input class="name-input" id="creatorName" placeholder="你的名字" value="{esc(user_value)}" />
            <span class="hint">署名（可选）</span>
          </div>
          <button class="publish" id="publishBtn" disabled>Publish a Future</button>
        </div>
      </div>
    </div>
    <div class="result" id="result">
      <div class="label">Future Seed created</div>
      <div class="url"><a href="#" id="seedUrl"></a></div>
      <div class="actions">
        <button onclick="copyUrl()">Copy link</button>
        <button onclick="location.href=document.getElementById('seedUrl').href">Open it</button>
        <button onclick="location.reload()">Create another</button>
      </div>
    </div>
    <section class="seeds-section" id="seeds">
      <div class="seeds-label">Growing Futures</div>
      <div class="seeds-grid">{seeds_html or '<p style="text-align:center;color:#52525b;font-size:14px;">还没有 Future Seed。成为第一个吧。</p>'}</div>
    </section>
  </main>
  <footer>The Duoweilai Web · An open network of imagined futures</footer>
  <script>
    const input = document.getElementById('futureInput');
    const btn = document.getElementById('publishBtn');
    input.addEventListener('input', () => btn.disabled = !input.value.trim());
    input.addEventListener('keydown', e => {{ if ((e.metaKey||e.ctrlKey) && e.key==='Enter') publish(); }});
    btn.addEventListener('click', publish);

    async function publish() {{
      const text = input.value.trim();
      if (!text) return;
      const name = document.getElementById('creatorName').value.trim() || 'Anonymous';
      if (name !== 'Anonymous') {{
        document.cookie = "duoweilai_name=" + encodeURIComponent(name) + "; path=/; max-age=31536000";
      }}
      btn.disabled = true;
      btn.textContent = 'Publishing…';
      try {{
        const res = await fetch('/api/future', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ body: text, creator: name }})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed');
        const url = location.origin + '/f/' + data.short_id;
        document.getElementById('seedUrl').textContent = url;
        document.getElementById('seedUrl').href = '/f/' + data.short_id;
        document.getElementById('form').style.display = 'none';
        document.getElementById('hero').style.display = 'none';
        document.getElementById('seeds').style.display = 'none';
        document.getElementById('result').classList.add('show');
      }} catch (e) {{
        alert('发布失败: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Publish a Future';
      }}
    }}
    function copyUrl() {{
      navigator.clipboard.writeText(document.getElementById('seedUrl').href).then(() => {{
        event.target.textContent = 'Copied';
        setTimeout(() => event.target.textContent = 'Copy link', 1500);
      }});
    }}
  </script>
</body>
</html>'''

def render_seed(future, contributions, current_user):
    groups = {"people": [], "places": [], "stories": [], "rules": [], "objects": [], "branches": []}
    for c in contributions:
        if c["type"] in groups:
            groups[c["type"]].append(c)

    def count(t): return len(groups.get(t, []))

    explore_cards = ""
    for key, label, icon in [
        ("people", "People", "◎"), ("places", "Places", "◇"),
        ("stories", "Stories", "▣"), ("rules", "Rules", "◈"),
        ("objects", "Objects", "○"), ("branches", "Branches", "↗")
    ]:
        explore_cards += f'''
        <div class="explore-card">
          <div class="icon">{icon}</div>
          <div class="name">{label}</div>
          <div class="count">{count(key)} {key}</div>
        </div>'''

    branches_html = ""
    for b in groups["branches"][:8]:
        branches_html += f'''
        <div class="branch-item">
          <span class="branch-title">{esc(b['title'])}</span>
          <span class="branch-meta"><a href="/person/{quote(b['creator'])}" style="color:inherit;text-decoration:none;">{esc(b['creator'])}</a> · {format_relative(b['created_at'])}</span>
        </div>'''

    world_link = ""
    if future.get("is_world") or sum(count(t) for t in groups) >= 3:
        world_link = f'<a href="/world/{future["short_id"]}" class="action-btn" style="text-decoration:none;">Open as World</a>'

    user_value = current_user if current_user != "Anonymous" else ""

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc(future['title'])} — Duoweilai</title>
  <style>{COMMON_CSS}
    .container {{ max-width:720px; margin:0 auto; padding:40px 24px 100px; }}
    .seed-meta {{ display:flex; align-items:center; gap:8px; font-size:13px; color:var(--subtle); margin-bottom:18px; }}
    .seed-title {{ font-size:clamp(26px,5vw,34px); font-weight:400; letter-spacing:-0.025em; line-height:1.3; margin-bottom:24px; }}
    .seed-body {{ font-size:17px; color:#e4e4e7; line-height:1.75; margin-bottom:32px; white-space:pre-wrap; }}
    .seed-footer {{ display:flex; justify-content:space-between; align-items:center; padding-bottom:36px; border-bottom:1px solid var(--border); margin-bottom:40px; flex-wrap:wrap; gap:16px; }}
    .creator {{ display:flex; align-items:center; gap:10px; text-decoration:none; color:inherit; }}
    .avatar {{ width:34px; height:34px; border-radius:50%; background:#27272a; display:flex; align-items:center; justify-content:center; font-size:14px; font-weight:500; color:var(--muted); }}
    .creator-name {{ font-size:14px; font-weight:500; }}
    .creator-date {{ font-size:12px; color:var(--subtle); }}
    .actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .action-btn {{ background:transparent; border:1px solid var(--border); color:var(--muted); border-radius:999px; padding:7px 14px; font-size:13px; cursor:pointer; font-family:inherit; }}
    .action-btn:hover {{ border-color:#3f3f46; color:var(--fg); background:rgba(255,255,255,0.03); }}
    .explore-label {{ font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--subtle); margin-bottom:16px; }}
    .explore-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; }}
    @media(min-width:560px){{ .explore-grid{{ grid-template-columns:repeat(3,1fr); }} }}
    .explore-card {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:20px; display:flex; flex-direction:column; gap:6px; min-height:100px; }}
    .explore-card .icon {{ font-size:17px; opacity:.7; }}
    .explore-card .name {{ font-size:15px; font-weight:500; }}
    .explore-card .count {{ font-size:12px; color:var(--subtle); margin-top:auto; }}
    .branches-section {{ margin-top:56px; }}
    .section-title {{ font-size:15px; font-weight:500; margin-bottom:14px; }}
    .branch-list {{ display:flex; flex-direction:column; gap:8px; }}
    .branch-item {{ display:flex; justify-content:space-between; align-items:center; padding:14px 16px; border:1px solid var(--border); border-radius:10px; gap:12px; }}
    .branch-title {{ font-size:14px; }}
    .branch-meta {{ font-size:12px; color:var(--subtle); white-space:nowrap; }}
    .contribute {{ margin-top:56px; padding:28px; border:1px dashed #3f3f46; border-radius:16px; text-align:center; }}
    .contribute p {{ font-size:15px; color:var(--muted); margin-bottom:16px; }}
    .contribute button {{ background:var(--fg); color:var(--bg); border:none; border-radius:999px; padding:11px 24px; font-size:14px; font-weight:500; cursor:pointer; font-family:inherit; }}
    .modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:100; align-items:center; justify-content:center; padding:20px; }}
    .modal.show {{ display:flex; }}
    .modal-box {{ background:var(--bg); border:1px solid var(--border); border-radius:16px; padding:28px; max-width:480px; width:100%; }}
    .modal-box h3 {{ font-size:18px; font-weight:500; margin-bottom:16px; }}
    .modal-box select, .modal-box input, .modal-box textarea {{ width:100%; background:var(--input-bg); border:1px solid var(--border); border-radius:10px; padding:12px; color:var(--fg); font-size:14px; font-family:inherit; margin-bottom:12px; }}
    .modal-box textarea {{ min-height:80px; resize:vertical; }}
    .modal-actions {{ display:flex; gap:10px; justify-content:flex-end; }}
    .modal-actions button {{ border-radius:999px; padding:9px 18px; font-size:13px; cursor:pointer; font-family:inherit; }}
    .modal-actions .cancel {{ background:transparent; border:1px solid var(--border); color:var(--muted); }}
    .modal-actions .submit {{ background:var(--fg); color:var(--bg); border:none; }}
  </style>
</head>
<body>
  {header_html(current_user)}
  <div class="container">
    <div class="seed-meta">
      <span>Future Seed</span><span>·</span>
      <span>#{future['short_id']}</span>
      {"<span>·</span><span style='color:#a1a1aa;'>World</span>" if future.get("is_world") else ""}
    </div>
    <h1 class="seed-title">{esc(future['title'])}</h1>
    <div class="seed-body">{esc(future['body'])}</div>
    <div class="seed-footer">
      <a href="/person/{quote(future['creator'])}" class="creator">
        <div class="avatar">{esc(future['creator'][0].upper() if future['creator'] else '?')}</div>
        <div>
          <div class="creator-name">{esc(future['creator'])}</div>
          <div class="creator-date">{format_date(future['created_at'])} · 启动了这个未来</div>
        </div>
      </a>
      <div class="actions">
        <button class="action-btn" onclick="navigator.clipboard.writeText(location.href).then(()=>this.textContent='Copied')">Share</button>
        {world_link}
        <button class="action-btn" onclick="openContribute('branches')">Branch</button>
      </div>
    </div>
    <div class="explore-label">Explore this Future</div>
    <div class="explore-grid">{explore_cards}</div>
    <div class="branches-section">
      <div class="section-title">Recent Branches</div>
      <div class="branch-list">{branches_html or '<p style="color:#52525b;font-size:14px;">还没有分支。成为第一个继续这个未来的人。</p>'}</div>
    </div>
    <div class="contribute">
      <p>这个未来还在生长。你可以继续它。</p>
      <button onclick="openContribute()">Continue this Future</button>
    </div>
  </div>
  <footer>{BASE_URL}/f/{future['short_id']}</footer>

  <div class="modal" id="modal">
    <div class="modal-box">
      <h3>Continue this Future</h3>
      <select id="contribType">
        <option value="branches">Branch — 开一个新方向</option>
        <option value="people">People — 添加一个人物</option>
        <option value="places">Places — 添加一个地点</option>
        <option value="stories">Stories — 写下一段故事</option>
        <option value="rules">Rules — 定义一条规则</option>
        <option value="objects">Objects — 添加一个物件</option>
      </select>
      <input type="text" id="contribTitle" placeholder="标题 / 名称" />
      <textarea id="contribBody" placeholder="描述（可选）"></textarea>
      <input type="text" id="contribCreator" placeholder="你的名字" value="{esc(user_value)}" />
      <div class="modal-actions">
        <button class="cancel" onclick="closeModal()">Cancel</button>
        <button class="submit" onclick="submitContribute()">Add</button>
      </div>
    </div>
  </div>
  <script>
    function openContribute(type) {{
      if (type) document.getElementById('contribType').value = type;
      document.getElementById('modal').classList.add('show');
    }}
    function closeModal() {{ document.getElementById('modal').classList.remove('show'); }}
    async function submitContribute() {{
      const type = document.getElementById('contribType').value;
      const title = document.getElementById('contribTitle').value.trim();
      const body = document.getElementById('contribBody').value.trim();
      const creator = document.getElementById('contribCreator').value.trim() || 'Anonymous';
      if (!title) {{ alert('请填写标题'); return; }}
      if (creator !== 'Anonymous') {{
        document.cookie = "duoweilai_name=" + encodeURIComponent(creator) + "; path=/; max-age=31536000";
      }}
      const res = await fetch('/api/contribute', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ future_id: '{future["id"]}', type, title, body, creator }})
      }});
      if (res.ok) location.reload();
      else alert('Failed');
    }}
    document.getElementById('modal').addEventListener('click', e => {{ if (e.target.id==='modal') closeModal(); }});
  </script>
</body>
</html>'''

def render_world(future, contributions, current_user):
    groups = {"people": [], "places": [], "stories": [], "rules": [], "objects": [], "branches": []}
    for c in contributions:
        if c["type"] in groups:
            groups[c["type"]].append(c)

    def cards(items, empty="还没有"):
        if not items:
            return f'<p style="color:#52525b;font-size:14px;">{empty}</p>'
        html = '<div class="cards">'
        for it in items:
            desc = esc(it.get("body") or "")[:80]
            html += f'''
            <div class="card">
              <div class="name">{esc(it["title"])}</div>
              <div class="desc">{desc}</div>
              <div class="by"><a href="/person/{quote(it["creator"])}">{esc(it["creator"])}</a></div>
            </div>'''
        html += '</div>'
        return html

    timeline = f'''
    <div class="timeline-item">
      <div class="date">{format_date(future["created_at"])}</div>
      <div class="event"><a href="/person/{quote(future["creator"])}">{esc(future["creator"])}</a> 发布了原始 Future Seed</div>
    </div>'''
    for c in sorted(contributions, key=lambda x: x["created_at"])[:12]:
        timeline += f'''
        <div class="timeline-item">
          <div class="date">{format_relative(c["created_at"])}</div>
          <div class="event"><a href="/person/{quote(c["creator"])}">{esc(c["creator"])}</a> 添加了 {c["type"]}: {esc(c["title"])}</div>
        </div>'''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc(future['title'])} — World — Duoweilai</title>
  <style>{COMMON_CSS}
    .layout {{ display:flex; max-width:1100px; margin:0 auto; min-height:calc(100vh - 60px); }}
    .sidebar {{ width:200px; flex-shrink:0; padding:32px 16px; border-right:1px solid var(--border); position:sticky; top:60px; height:calc(100vh - 60px); overflow-y:auto; }}
    .sidebar-label {{ font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:var(--subtle); margin-bottom:12px; padding-left:10px; }}
    .nav-list {{ list-style:none; display:flex; flex-direction:column; gap:2px; }}
    .nav-list a {{ display:block; padding:8px 10px; font-size:13.5px; color:var(--muted); text-decoration:none; border-radius:8px; }}
    .nav-list a:hover, .nav-list a.active {{ color:var(--fg); background:rgba(255,255,255,0.05); }}
    .main {{ flex:1; padding:36px 36px 80px; max-width:700px; }}
    .world-badge {{ font-size:12px; color:var(--subtle); margin-bottom:12px; }}
    .world-badge span {{ background:rgba(255,255,255,0.06); padding:3px 8px; border-radius:999px; margin-left:6px; }}
    .world-title {{ font-size:clamp(26px,4vw,34px); font-weight:400; letter-spacing:-0.03em; margin-bottom:8px; }}
    .world-tagline {{ font-size:16px; color:var(--muted); margin-bottom:24px; }}
    .world-meta {{ display:flex; flex-wrap:wrap; gap:16px; font-size:13px; color:var(--subtle); padding-bottom:28px; border-bottom:1px solid var(--border); margin-bottom:32px; }}
    .section {{ margin-bottom:44px; }}
    .section-title {{ font-size:15px; font-weight:500; margin-bottom:14px; display:flex; justify-content:space-between; }}
    .section-title a {{ font-size:13px; color:var(--muted); text-decoration:none; font-weight:400; }}
    .overview-text {{ font-size:16px; color:#e4e4e7; line-height:1.75; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:10px; }}
    .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:14px; }}
    .card .name {{ font-size:14px; font-weight:500; margin-bottom:4px; }}
    .card .desc {{ font-size:12.5px; color:var(--subtle); line-height:1.4; margin-bottom:6px; }}
    .card .by {{ font-size:11px; color:#52525b; }}
    .card .by a {{ color:#71717a; text-decoration:none; }}
    .timeline {{ position:relative; padding-left:20px; }}
    .timeline::before {{ content:''; position:absolute; left:5px; top:6px; bottom:6px; width:1px; background:var(--border); }}
    .timeline-item {{ position:relative; padding-bottom:20px; }}
    .timeline-item::before {{ content:''; position:absolute; left:-17px; top:7px; width:7px; height:7px; border-radius:50%; background:#3f3f46; border:2px solid var(--bg); }}
    .timeline-item .date {{ font-size:12px; color:var(--subtle); margin-bottom:3px; }}
    .timeline-item .event {{ font-size:14px; }}
    .timeline-item .event a {{ color:var(--muted); text-decoration:none; }}
    .world-cta {{ margin-top:48px; padding:24px; border:1px dashed #3f3f46; border-radius:14px; text-align:center; }}
    .world-cta p {{ font-size:14px; color:var(--muted); margin-bottom:14px; }}
    .world-cta a {{ display:inline-block; background:var(--fg); color:var(--bg); border-radius:999px; padding:10px 20px; font-size:13px; font-weight:500; text-decoration:none; }}
    @media (max-width:800px) {{
      .layout {{ flex-direction:column; }}
      .sidebar {{ width:100%; height:auto; position:static; border-right:none; border-bottom:1px solid var(--border); padding:16px; }}
      .nav-list {{ flex-direction:row; flex-wrap:wrap; gap:6px; }}
      .nav-list a {{ padding:6px 12px; background:rgba(255,255,255,0.03); }}
      .main {{ padding:28px 16px 60px; }}
    }}
  </style>
</head>
<body>
  {header_html(current_user)}
  <div class="layout">
    <aside class="sidebar">
      <div class="sidebar-label">World</div>
      <ul class="nav-list">
        <li><a href="#overview" class="active">Overview</a></li>
        <li><a href="#people">People ({len(groups["people"])})</a></li>
        <li><a href="#places">Places ({len(groups["places"])})</a></li>
        <li><a href="#stories">Stories ({len(groups["stories"])})</a></li>
        <li><a href="#rules">Rules ({len(groups["rules"])})</a></li>
        <li><a href="#objects">Objects ({len(groups["objects"])})</a></li>
        <li><a href="#branches">Branches ({len(groups["branches"])})</a></li>
        <li><a href="#timeline">Timeline</a></li>
      </ul>
    </aside>
    <main class="main">
      <div class="world-badge">World <span>Growing</span></div>
      <h1 class="world-title">{esc(future['title'])}</h1>
      <p class="world-tagline">A World grown from Future Seed #{future['short_id']}</p>
      <div class="world-meta">
        <span>Started by <a href="/person/{quote(future['creator'])}" style="color:var(--muted);">{esc(future['creator'])}</a></span>
        <span>{len(contributions)} contributions</span>
        <span>{future['views']} views</span>
        <span>Since {format_date(future['created_at'])}</span>
      </div>

      <section class="section" id="overview">
        <div class="section-title">Overview</div>
        <div class="overview-text">{esc(future['body'])}</div>
      </section>

      <section class="section" id="people">
        <div class="section-title">People</div>
        {cards(groups["people"], "还没有人物")}
      </section>

      <section class="section" id="places">
        <div class="section-title">Places</div>
        {cards(groups["places"], "还没有地点")}
      </section>

      <section class="section" id="stories">
        <div class="section-title">Stories</div>
        {cards(groups["stories"], "还没有故事")}
      </section>

      <section class="section" id="rules">
        <div class="section-title">Rules</div>
        {cards(groups["rules"], "还没有规则")}
      </section>

      <section class="section" id="objects">
        <div class="section-title">Objects</div>
        {cards(groups["objects"], "还没有物件")}
      </section>

      <section class="section" id="branches">
        <div class="section-title">Branches</div>
        {cards(groups["branches"], "还没有分支")}
      </section>

      <section class="section" id="timeline">
        <div class="section-title">Timeline</div>
        <div class="timeline">{timeline}</div>
      </section>

      <div class="world-cta">
        <p>这个世界还在生长。你可以继续建造它。</p>
        <a href="/f/{future['short_id']}">Back to Seed · Continue</a>
      </div>
    </main>
  </div>
  <footer>duoweilai.com/world/{future['short_id']}</footer>
</body>
</html>'''

def render_creator(name, data, current_user):
    stats = data["stats"]
    futures_html = ""
    for f in data["futures"]:
        badge = " · World" if f.get("is_world") else ""
        futures_html += f'''
        <a href="/f/{f['short_id']}" class="item">
          <span class="title">{esc(f['title'])}{badge}</span>
          <span class="meta">{f['branches']} branches · {format_relative(f['created_at'])}</span>
        </a>'''

    worlds_html = ""
    for w in data["worlds_started"] + data["worlds_helped"]:
        worlds_html += f'''
        <a href="/world/{w['short_id']}" class="item">
          <span class="title">{esc(w['title'])}</span>
          <span class="meta">{w['branches']} branches</span>
        </a>'''

    contribs_html = ""
    for c in data["contributions"][:20]:
        contribs_html += f'''
        <a href="/f/{c['short_id']}" class="item">
          <span class="title">{c['type'].title()}: {esc(c['title'])}</span>
          <span class="meta">{esc(c.get('future_title',''))[:30]} · {format_relative(c['created_at'])}</span>
        </a>'''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc(name)} — Duoweilai</title>
  <style>{COMMON_CSS}
    .container {{ max-width:720px; margin:0 auto; padding:40px 24px 100px; }}
    .profile {{ display:flex; align-items:flex-start; gap:20px; margin-bottom:36px; }}
    .avatar-lg {{ width:72px; height:72px; border-radius:50%; background:#27272a; display:flex; align-items:center; justify-content:center; font-size:28px; font-weight:500; color:var(--muted); flex-shrink:0; }}
    .profile-info h1 {{ font-size:24px; font-weight:500; letter-spacing:-0.02em; margin-bottom:6px; }}
    .bio {{ font-size:15px; color:var(--muted); margin-bottom:16px; }}
    .stats {{ display:flex; gap:28px; flex-wrap:wrap; }}
    .stat {{ display:flex; flex-direction:column; gap:2px; }}
    .stat-num {{ font-size:20px; font-weight:500; }}
    .stat-label {{ font-size:12px; color:var(--subtle); }}
    .tabs {{ display:flex; gap:24px; border-bottom:1px solid var(--border); margin-bottom:24px; }}
    .tab {{ font-size:14px; color:var(--subtle); padding-bottom:12px; cursor:pointer; border:none; background:none; border-bottom:2px solid transparent; font-family:inherit; }}
    .tab.active {{ color:var(--fg); border-bottom-color:var(--fg); }}
    .item-list {{ display:flex; flex-direction:column; gap:8px; }}
    .item {{ display:flex; justify-content:space-between; align-items:center; padding:16px 18px; border:1px solid var(--border); border-radius:12px; text-decoration:none; color:inherit; transition:all .2s; gap:16px; }}
    .item:hover {{ border-color:#3f3f46; background:rgba(255,255,255,0.02); }}
    .item .title {{ font-size:15px; flex:1; }}
    .item .meta {{ font-size:12px; color:var(--subtle); white-space:nowrap; }}
    .empty {{ text-align:center; padding:40px; color:var(--subtle); font-size:14px; }}
    @media (max-width:640px) {{
      .profile {{ flex-direction:column; align-items:center; text-align:center; }}
      .stats {{ justify-content:center; }}
      .item {{ flex-direction:column; align-items:flex-start; gap:6px; }}
    }}
  </style>
</head>
<body>
  {header_html(current_user)}
  <div class="container">
    <div class="profile">
      <div class="avatar-lg">{esc(name[0].upper() if name else '?')}</div>
      <div class="profile-info">
        <h1>{esc(name)}</h1>
        <p class="bio">用创造建立身份，而不是粉丝数。</p>
        <div class="stats">
          <div class="stat"><span class="stat-num">{stats['futures']}</span><span class="stat-label">Futures</span></div>
          <div class="stat"><span class="stat-num">{stats['worlds']}</span><span class="stat-label">Worlds</span></div>
          <div class="stat"><span class="stat-num">{stats['branches']}</span><span class="stat-label">Branches</span></div>
          <div class="stat"><span class="stat-num">{stats['contributions']}</span><span class="stat-label">Contributions</span></div>
        </div>
      </div>
    </div>

    <div class="tabs">
      <button class="tab active" data-tab="started">Futures I Started</button>
      <button class="tab" data-tab="worlds">Worlds</button>
      <button class="tab" data-tab="contribs">Contributions</button>
    </div>

    <div id="started" class="tab-content">
      <div class="item-list">{futures_html or '<div class="empty">还没有启动过 Future</div>'}</div>
    </div>
    <div id="worlds" class="tab-content" style="display:none;">
      <div class="item-list">{worlds_html or '<div class="empty">还没有参与过 World</div>'}</div>
    </div>
    <div id="contribs" class="tab-content" style="display:none;">
      <div class="item-list">{contribs_html or '<div class="empty">还没有贡献</div>'}</div>
    </div>
  </div>
  <footer>duoweilai.com/person/{quote(name)}</footer>
  <script>
    document.querySelectorAll('.tab').forEach(tab => {{
      tab.addEventListener('click', () => {{
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
        document.getElementById(tab.dataset.tab).style.display = 'block';
      }});
    }});
  </script>
</body>
</html>'''

def render_explore(futures, current_user):
    rows = ""
    for f in futures:
        badge = " · World" if f.get("is_world") else ""
        rows += f'''
        <a href="/f/{f['short_id']}" class="seed-row">
          <span class="title">{esc(f['title'])}{badge}</span>
          <span class="info">{esc(f['creator'])} · {f['branches']} branches</span>
        </a>'''
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Explore Futures — Duoweilai</title>
  <style>{COMMON_CSS}
    .container {{ max-width:720px; margin:0 auto; padding:40px 24px 100px; }}
    .page-title {{ font-size:28px; font-weight:400; letter-spacing:-0.02em; margin-bottom:8px; }}
    .page-desc {{ font-size:15px; color:var(--muted); margin-bottom:36px; }}
    .section-label {{ font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--subtle); margin-bottom:16px; }}
    .seeds-list {{ display:flex; flex-direction:column; gap:8px; }}
    .seed-row {{ display:flex; justify-content:space-between; align-items:center; padding:16px 18px; border:1px solid var(--border); border-radius:12px; text-decoration:none; color:inherit; transition:all .2s; gap:16px; }}
    .seed-row:hover {{ border-color:#3f3f46; background:rgba(255,255,255,0.02); }}
    .seed-row .title {{ font-size:15px; flex:1; }}
    .seed-row .info {{ font-size:12px; color:var(--subtle); white-space:nowrap; }}
  </style>
</head>
<body>
  {header_html(current_user, "explore")}
  <div class="container">
    <h1 class="page-title">Explore Futures</h1>
    <p class="page-desc">所有正在生长的 Future Seeds 与 Worlds。</p>
    <div class="section-label">Recently Growing</div>
    <div class="seeds-list">{rows or '<p style="color:#52525b;">还没有种子。</p>'}</div>
  </div>
  <footer>The Duoweilai Web</footer>
</body>
</html>'''

# -------------------------------------------------
# HTTP Handler
# -------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    def get_current_user(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if "duoweilai_name" in cookie:
            name = unquote(cookie["duoweilai_name"].value).strip()
            if name:
                return name[:40]
        return "Anonymous"

    def send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path.rstrip("/") or "/")
        user = self.get_current_user()

        if path == "/":
            self.send_html(render_home(list_futures(12), user))
        elif path == "/explore":
            self.send_html(render_explore(list_futures(50), user))
        elif path.startswith("/f/"):
            short_id = path[3:].upper()
            future = get_future_by_short(short_id)
            if not future:
                self.send_html("<h1>Future Seed not found</h1><p><a href='/'>Back home</a></p>", 404)
                return
            contribs = get_contributions(future["id"])
            self.send_html(render_seed(future, contribs, user))
        elif path.startswith("/world/"):
            short_id = path[7:].upper()
            future = get_future_by_short(short_id, inc_view=False)
            if not future:
                self.send_html("<h1>World not found</h1><p><a href='/'>Back home</a></p>", 404)
                return
            contribs = get_contributions(future["id"])
            self.send_html(render_world(future, contribs, user))
        elif path.startswith("/person/"):
            name = path[8:].strip()
            if not name:
                self.send_html("<h1>Not found</h1>", 404)
                return
            data = get_creator_stats(name)
            self.send_html(render_creator(name, data, user))
        else:
            self.send_html("<h1>404</h1><p><a href='/'>Home</a></p>", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/future":
            data = self.read_json()
            body = (data.get("body") or "").strip()
            if not body:
                self.send_json({"error": "body required"}, 400)
                return
            creator = (data.get("creator") or "Anonymous").strip()[:40] or "Anonymous"
            title = body.split("\n")[0][:120]
            result = create_future(title, body, creator)
            self.send_json(result)
        elif path == "/api/contribute":
            data = self.read_json()
            future_id = data.get("future_id")
            type_ = data.get("type")
            title = (data.get("title") or "").strip()
            if not future_id or not type_ or not title:
                self.send_json({"error": "missing fields"}, 400)
                return
            if type_ not in ("people", "places", "stories", "rules", "objects", "branches"):
                self.send_json({"error": "invalid type"}, 400)
                return
            body = (data.get("body") or "").strip()
            creator = (data.get("creator") or "Anonymous").strip()[:40] or "Anonymous"
            add_contribution(future_id, type_, title, body, creator)
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "not found"}, 404)

# -------------------------------------------------
# Main
# -------------------------------------------------
if __name__ == "__main__":
    init_db()
    print(f"Duoweilai v0.2 running at {BASE_URL}")
    print("Pages: /  /f/XXXXX  /world/XXXXX  /person/Name  /explore")
    print("Identity: cookie-based name")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
