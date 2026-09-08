#!/usr/bin/env python3
"""
Duoweilai — First Principles Prototype
Core loop: Publish a Future Seed → Get permanent link → Explore it
"""

import sqlite3
import json
import uuid
import re
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timezone
from pathlib import Path

# Config
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
            views       INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS contributions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            future_id   TEXT NOT NULL,
            type        TEXT NOT NULL,  -- people / places / stories / rules / objects / branches
            title       TEXT NOT NULL,
            body        TEXT,
            creator     TEXT NOT NULL DEFAULT 'Anonymous',
            created_at  TEXT NOT NULL,
            FOREIGN KEY (future_id) REFERENCES futures(id)
        );

        CREATE INDEX IF NOT EXISTS idx_futures_short ON futures(short_id);
        CREATE INDEX IF NOT EXISTS idx_contrib_future ON contributions(future_id);
    """)
    conn.commit()
    conn.close()

def generate_short_id():
    """Generate a short readable ID like 7A92K"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    import random
    return "".join(random.choice(alphabet) for _ in range(5))

def create_future(title: str, body: str, creator: str = "Anonymous") -> dict:
    conn = get_db()
    short_id = generate_short_id()
    # Ensure uniqueness
    while conn.execute("SELECT 1 FROM futures WHERE short_id = ?", (short_id,)).fetchone():
        short_id = generate_short_id()

    future_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Auto-generate a short title if user only wrote one paragraph
    if not title or title == body[:80]:
        title = body.strip().split("\n")[0][:100]
        if len(body.strip()) > 100:
            title = title.rstrip(".,;:") + "…"

    conn.execute(
        "INSERT INTO futures (id, short_id, title, body, creator, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (future_id, short_id, title, body, creator, now)
    )
    conn.commit()
    conn.close()
    return {"id": future_id, "short_id": short_id, "title": title}

def get_future_by_short(short_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM futures WHERE short_id = ?", (short_id.upper(),)).fetchone()
    if row:
        # Increment views
        conn.execute("UPDATE futures SET views = views + 1 WHERE short_id = ?", (short_id.upper(),))
        conn.commit()
    conn.close()
    return dict(row) if row else None

def list_futures(limit=20):
    conn = get_db()
    rows = conn.execute(
        "SELECT short_id, title, creator, created_at, branches, views FROM futures ORDER BY created_at DESC LIMIT ?",
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
    conn.commit()
    conn.close()

# -------------------------------------------------
# HTML Templates (minimal, embedded for single-file simplicity)
# -------------------------------------------------
def render_home(futures):
    seeds_html = ""
    for f in futures:
        seeds_html += f"""
        <a href="/f/{f['short_id']}" class="seed-card">
          <div class="title">{esc(f['title'])}</div>
          <div class="meta">{esc(f['creator'])} · {format_date(f['created_at'])} · {f['branches']} branches</div>
        </a>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Duoweilai — What future do you imagine?</title>
  <style>{COMMON_CSS}
    main {{ flex:1; display:flex; flex-direction:column; justify-content:center; align-items:center; padding:40px 24px 80px; max-width:720px; margin:0 auto; width:100%; }}
    .hero {{ text-align:center; margin-bottom:48px; }}
    .hero h1 {{ font-size:clamp(28px,5vw,36px); font-weight:400; letter-spacing:-0.02em; margin-bottom:12px; }}
    .hero p {{ font-size:16px; color:var(--muted); font-weight:300; }}
    .seed-form {{ width:100%; }}
    .input-wrapper {{ background:var(--input-bg); border:1px solid var(--border); border-radius:16px; padding:20px 20px 16px; transition:border-color .2s,box-shadow .2s; }}
    .input-wrapper:focus-within {{ border-color:#3f3f46; box-shadow:0 0 0 4px rgba(255,255,255,0.03); }}
    textarea {{ width:100%; background:transparent; border:none; outline:none; color:var(--fg); font-size:17px; font-family:inherit; resize:none; min-height:120px; line-height:1.6; }}
    textarea::placeholder {{ color:#52525b; }}
    .form-footer {{ display:flex; justify-content:space-between; align-items:center; margin-top:12px; padding:0 4px; gap:12px; flex-wrap:wrap; }}
    .hint {{ font-size:13px; color:#52525b; }}
    button.publish {{ background:var(--fg); color:var(--bg); border:none; border-radius:999px; padding:10px 22px; font-size:14px; font-weight:500; cursor:pointer; transition:opacity .2s,transform .15s; font-family:inherit; }}
    button.publish:hover {{ opacity:.9; }}
    button.publish:disabled {{ opacity:.4; cursor:not-allowed; }}
    .seeds-section {{ margin-top:100px; width:100%; }}
    .seeds-label {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:#52525b; margin-bottom:20px; text-align:center; }}
    .seeds-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px; }}
    .seed-card {{ background:transparent; border:1px solid var(--border); border-radius:12px; padding:18px 20px; text-decoration:none; color:inherit; transition:border-color .2s,background .2s; display:block; }}
    .seed-card:hover {{ border-color:#3f3f46; background:rgba(255,255,255,0.02); }}
    .seed-card .title {{ font-size:15px; font-weight:400; margin-bottom:6px; line-height:1.4; }}
    .seed-card .meta {{ font-size:12px; color:#71717a; }}
    .result {{ display:none; text-align:center; animation:fadeIn .4s ease; }}
    .result.show {{ display:block; }}
    .result .label {{ font-size:13px; color:var(--muted); margin-bottom:12px; }}
    .result .url {{ font-size:18px; font-weight:500; letter-spacing:-0.01em; margin-bottom:24px; word-break:break-all; }}
    .result .url a {{ color:var(--fg); text-decoration:none; border-bottom:1px solid #3f3f46; }}
    .result .actions {{ display:flex; gap:12px; justify-content:center; flex-wrap:wrap; }}
    .result button {{ background:transparent; border:1px solid var(--border); color:var(--fg); border-radius:999px; padding:9px 18px; font-size:13px; cursor:pointer; font-family:inherit; }}
    .result button:hover {{ background:rgba(255,255,255,0.05); }}
    @keyframes fadeIn {{ from{{opacity:0;transform:translateY(8px)}} to{{opacity:1;transform:translateY(0)}} }}
  </style>
</head>
<body>
  <header>
    <a href="/" class="logo">Duoweilai</a>
    <a href="/explore" class="nav-link">Explore</a>
  </header>
  <main>
    <div class="hero" id="hero">
      <h1>What future do you imagine?</h1>
      <p>写下你想象的未来，它会成为一颗永久的种子。</p>
    </div>
    <div class="seed-form" id="form">
      <div class="input-wrapper">
        <textarea id="futureInput" placeholder="Describe a future..." rows="4"></textarea>
        <div class="form-footer">
          <span class="hint">例如：如果大学没有固定校园，而是在世界各地不断移动呢？</span>
          <button class="publish" id="publishBtn" disabled>Publish a Future</button>
        </div>
      </div>
    </div>
    <div class="result" id="result">
      <div class="label">Future Seed created</div>
      <div class="url"><a href="#" id="seedUrl"></a></div>
      <div class="actions">
        <button onclick="copyUrl()">Copy link</button>
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
      btn.disabled = true;
      btn.textContent = 'Publishing…';
      try {{
        const res = await fetch('/api/future', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ body: text }})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed');
        document.getElementById('seedUrl').textContent = location.origin + '/f/' + data.short_id;
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
      const url = document.getElementById('seedUrl').href;
      navigator.clipboard.writeText(url).then(() => {{
        event.target.textContent = 'Copied';
        setTimeout(() => event.target.textContent = 'Copy link', 1500);
      }});
    }}
  </script>
</body>
</html>"""

def render_seed(future, contributions):
    # Group contributions
    groups = {"people": [], "places": [], "stories": [], "rules": [], "objects": [], "branches": []}
    for c in contributions:
        t = c["type"]
        if t in groups:
            groups[t].append(c)

    def count(t): return len(groups.get(t, []))

    explore_cards = ""
    for key, label, icon in [
        ("people", "People", "◎"), ("places", "Places", "◇"),
        ("stories", "Stories", "▣"), ("rules", "Rules", "◈"),
        ("objects", "Objects", "○"), ("branches", "Branches", "↗")
    ]:
        explore_cards += f"""
        <a href="#/{key}" class="explore-card" onclick="showSection('{key}');return false;">
          <div class="icon">{icon}</div>
          <div class="name">{label}</div>
          <div class="count">{count(key)} {key}</div>
        </a>"""

    branches_html = ""
    for b in groups["branches"][:5]:
        branches_html += f"""
        <div class="branch-item">
          <span class="branch-title">{esc(b['title'])}</span>
          <span class="branch-meta">{esc(b['creator'])} · {format_date(b['created_at'])}</span>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc(future['title'])} — Duoweilai</title>
  <style>{COMMON_CSS}
    .container {{ max-width:720px; margin:0 auto; padding:48px 24px 120px; }}
    .seed-meta {{ display:flex; align-items:center; gap:8px; font-size:13px; color:var(--subtle); margin-bottom:20px; }}
    .seed-title {{ font-size:clamp(26px,5vw,34px); font-weight:400; letter-spacing:-0.025em; line-height:1.3; margin-bottom:28px; }}
    .seed-body {{ font-size:17px; color:#e4e4e7; line-height:1.75; margin-bottom:36px; white-space:pre-wrap; }}
    .seed-footer {{ display:flex; justify-content:space-between; align-items:center; padding-bottom:40px; border-bottom:1px solid var(--border); margin-bottom:48px; flex-wrap:wrap; gap:16px; }}
    .creator {{ display:flex; align-items:center; gap:10px; text-decoration:none; color:inherit; }}
    .avatar {{ width:32px; height:32px; border-radius:50%; background:#27272a; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:500; color:var(--muted); }}
    .creator-name {{ font-size:14px; font-weight:500; }}
    .creator-date {{ font-size:12px; color:var(--subtle); }}
    .actions {{ display:flex; gap:8px; }}
    .action-btn {{ background:transparent; border:1px solid var(--border); color:var(--muted); border-radius:999px; padding:7px 14px; font-size:13px; cursor:pointer; font-family:inherit; }}
    .action-btn:hover {{ border-color:#3f3f46; color:var(--fg); background:rgba(255,255,255,0.03); }}
    .explore-label {{ font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--subtle); margin-bottom:20px; }}
    .explore-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; }}
    @media(min-width:560px){{ .explore-grid{{ grid-template-columns:repeat(3,1fr); }} }}
    .explore-card {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:22px 20px; text-decoration:none; color:inherit; transition:all .2s; display:flex; flex-direction:column; gap:6px; min-height:110px; }}
    .explore-card:hover {{ border-color:#3f3f46; background:var(--hover); transform:translateY(-1px); }}
    .explore-card .icon {{ font-size:18px; margin-bottom:4px; opacity:.7; }}
    .explore-card .name {{ font-size:15px; font-weight:500; }}
    .explore-card .count {{ font-size:12px; color:var(--subtle); margin-top:auto; }}
    .branches-section {{ margin-top:64px; }}
    .section-header {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:16px; }}
    .section-title {{ font-size:15px; font-weight:500; }}
    .branch-list {{ display:flex; flex-direction:column; gap:8px; }}
    .branch-item {{ display:flex; justify-content:space-between; align-items:center; padding:14px 16px; border:1px solid var(--border); border-radius:10px; gap:12px; }}
    .branch-title {{ font-size:14px; }}
    .branch-meta {{ font-size:12px; color:var(--subtle); white-space:nowrap; }}
    .contribute {{ margin-top:64px; padding:28px; border:1px dashed #3f3f46; border-radius:16px; text-align:center; }}
    .contribute p {{ font-size:15px; color:var(--muted); margin-bottom:16px; }}
    .contribute button {{ background:var(--fg); color:var(--bg); border:none; border-radius:999px; padding:11px 24px; font-size:14px; font-weight:500; cursor:pointer; font-family:inherit; }}
    .contribute button:hover {{ opacity:.9; }}
    .modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:100; align-items:center; justify-content:center; padding:20px; }}
    .modal.show {{ display:flex; }}
    .modal-box {{ background:var(--bg); border:1px solid var(--border); border-radius:16px; padding:28px; max-width:480px; width:100%; }}
    .modal-box h3 {{ font-size:18px; font-weight:500; margin-bottom:16px; }}
    .modal-box select, .modal-box input, .modal-box textarea {{ width:100%; background:var(--input-bg); border:1px solid var(--border); border-radius:10px; padding:12px; color:var(--fg); font-size:14px; font-family:inherit; margin-bottom:12px; }}
    .modal-box textarea {{ min-height:80px; resize:vertical; }}
    .modal-actions {{ display:flex; gap:10px; justify-content:flex-end; margin-top:8px; }}
    .modal-actions button {{ border-radius:999px; padding:9px 18px; font-size:13px; cursor:pointer; font-family:inherit; }}
    .modal-actions .cancel {{ background:transparent; border:1px solid var(--border); color:var(--muted); }}
    .modal-actions .submit {{ background:var(--fg); color:var(--bg); border:none; }}
  </style>
</head>
<body>
  <header>
    <a href="/" class="logo">Duoweilai</a>
    <div class="header-right">
      <a href="/explore" class="nav-link">Explore</a>
    </div>
  </header>
  <div class="container">
    <div class="seed-meta">
      <span>Future Seed</span><span>·</span>
      <span>#{future['short_id']}</span>
    </div>
    <h1 class="seed-title">{esc(future['title'])}</h1>
    <div class="seed-body">{esc(future['body'])}</div>
    <div class="seed-footer">
      <div class="creator">
        <div class="avatar">{esc(future['creator'][0].upper())}</div>
        <div>
          <div class="creator-name">{esc(future['creator'])}</div>
          <div class="creator-date">{format_date(future['created_at'])} · 启动了这个未来</div>
        </div>
      </div>
      <div class="actions">
        <button class="action-btn" onclick="navigator.clipboard.writeText(location.href).then(()=>alert('Link copied'))">Share</button>
        <button class="action-btn" onclick="openContribute('branches')">Branch</button>
      </div>
    </div>
    <div class="explore-label">Explore this Future</div>
    <div class="explore-grid">{explore_cards}</div>
    <div class="branches-section">
      <div class="section-header">
        <div class="section-title">Recent Branches</div>
      </div>
      <div class="branch-list">{branches_html or '<p style="color:#52525b;font-size:14px;">还没有分支。成为第一个继续这个未来的人。</p>'}</div>
    </div>
    <div class="contribute">
      <p>这个未来还在生长。你可以继续它。</p>
      <button onclick="openContribute()">Continue this Future</button>
    </div>
  </div>
  <footer style="text-align:center;padding:32px;font-size:12px;color:#3f3f46;">
    {BASE_URL}/f/{future['short_id']}
  </footer>

  <!-- Contribute Modal -->
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
      <input type="text" id="contribCreator" placeholder="你的名字（可选）" value="Anonymous" />
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
</html>"""

def render_explore(futures):
    rows = ""
    for f in futures:
        rows += f"""
        <a href="/f/{f['short_id']}" class="seed-row">
          <span class="title">{esc(f['title'])}</span>
          <span class="info">{esc(f['creator'])} · {f['branches']} branches</span>
        </a>"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Explore Futures — Duoweilai</title>
  <style>{COMMON_CSS}
    .container {{ max-width:720px; margin:0 auto; padding:48px 24px 100px; }}
    .page-title {{ font-size:28px; font-weight:400; letter-spacing:-0.02em; margin-bottom:8px; }}
    .page-desc {{ font-size:15px; color:var(--muted); margin-bottom:40px; }}
    .section-label {{ font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--subtle); margin-bottom:20px; }}
    .seeds-list {{ display:flex; flex-direction:column; gap:8px; }}
    .seed-row {{ display:flex; justify-content:space-between; align-items:center; padding:16px 18px; border:1px solid var(--border); border-radius:12px; text-decoration:none; color:inherit; transition:all .2s; gap:16px; }}
    .seed-row:hover {{ border-color:#3f3f46; background:rgba(255,255,255,0.02); }}
    .seed-row .title {{ font-size:15px; flex:1; }}
    .seed-row .info {{ font-size:12px; color:var(--subtle); white-space:nowrap; }}
  </style>
</head>
<body>
  <header>
    <a href="/" class="logo">Duoweilai</a>
    <a href="/explore" class="nav-link">Explore</a>
  </header>
  <div class="container">
    <h1 class="page-title">Explore Futures</h1>
    <p class="page-desc">所有正在生长的 Future Seeds。</p>
    <div class="section-label">Recently Growing</div>
    <div class="seeds-list">{rows or '<p style="color:#52525b;">还没有种子。</p>'}</div>
  </div>
  <footer style="text-align:center;padding:32px;font-size:12px;color:#3f3f46;">The Duoweilai Web</footer>
</body>
</html>"""

# Shared CSS
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
  padding:28px 40px; display:flex; justify-content:space-between; align-items:center;
}
.logo { font-size:15px; font-weight:500; letter-spacing:0.12em; text-transform:uppercase; color:var(--fg); text-decoration:none; }
.nav-link { font-size:13px; color:var(--muted); text-decoration:none; transition:color .2s; }
.nav-link:hover { color:var(--fg); }
.header-right { display:flex; gap:20px; align-items:center; }
footer { padding:24px 40px; text-align:center; font-size:12px; color:#3f3f46; }
@media (max-width:640px) {
  header { padding:20px 20px; }
}
"""

def esc(s):
    if s is None: return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

def format_date(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except:
        return iso[:10]

# -------------------------------------------------
# HTTP Handler
# -------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    def send_html(self, html, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(html.encode("utf-8")))
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

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
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            futures = list_futures(12)
            self.send_html(render_home(futures))
        elif path == "/explore":
            futures = list_futures(50)
            self.send_html(render_explore(futures))
        elif path.startswith("/f/"):
            short_id = path[3:].upper()
            future = get_future_by_short(short_id)
            if not future:
                self.send_html("<h1>Future Seed not found</h1><a href='/'>Back</a>", 404)
                return
            contribs = get_contributions(future["id"])
            self.send_html(render_seed(future, contribs))
        else:
            self.send_html("<h1>404</h1><a href='/'>Home</a>", 404)

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
            # Use first line as title
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
    print(f"Duoweilai running at {BASE_URL}")
    print("Core loop: Publish → Permanent link → Explore")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
