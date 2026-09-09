# Duoweilai · Web

> **Plant a future seed. Watch it grow into a world.**

Duoweilai (多未来 · "Multiple Futures") is a collaborative imagination platform — anyone can publish a **Future Seed**: a "what if" question about a future that could be. Others can explore it, add to it, branch it, and help it grow into something richer.

**Core loop:** Publish a Future Seed → Get a permanent link → Others explore & contribute → The seed grows → Eventually becomes a **World**.

---

## Quick Start

Python 3.10+ and a virtualenv (the only dependency is Flask).

```bash
# Clone and run
git clone https://github.com/huliye24/duoweilai-web.git
cd duoweilai-web

python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# .venv/bin/pip install -r requirements.txt     # macOS / Linux

.venv/Scripts/python server.py                  # Windows
# .venv/bin/python server.py                    # macOS / Linux
```

Then open **http://localhost:8080** in your browser.

> First run automatically creates `duoweilai.db`. Sign up from the **Sign up** link — accounts are real (register / login / password reset).

### Team (same network)

To let teammates access from other machines on the same LAN:

```bash
DUOWEILAI_BIND=0.0.0.0 python server.py
```

Then access via `http://<your-local-ip>:8080`.

### Custom port / database

```bash
DUOWEILAI_PORT=3000 python server.py
DUOWEILAI_DB=/path/to/duoweilai.db python server.py
```

Other env vars: `DUOWEILAI_SECRET_KEY` (session signing), `DUOWEILAI_SECURE_COOKIE=1` (behind HTTPS), `DUOWEILAI_SMTP_*` (password-reset email; without SMTP the reset link is written to `reset_link.log`).

---

## Pages

| Route | Description |
|-------|-------------|
| `/` | Home — publish a future seed |
| `/explore` | Browse futures — full-text search, category filter, pagination |
| `/f/<id>` | Future Seed detail — contribute, comment, branch, edit |
| `/world/<id>` | World view — rich multi-section exploration |
| `/person/<username>` | User profile |
| `/notifications` | Your notifications |
| `/login` `/register` `/forgot` | Account |

---

## Features

- **Real accounts** — register / login / logout, cookie sessions, password reset by email
- **Future Seeds** — permanent, shareable "what if" imagination units
- **Contributions** — add People, Places, Stories, Rules, Objects to a seed
- **Branches** — spin a seed off into its own future; the parent page lists recent branches
- **Comments & replies** — reply to a comment and its author gets notified
- **Editing** — seeds, contributions and comments are editable by their authors (marked "edited")
- **Search & pagination** — server-side full-text search (title + body), category chips, page navigation
- **Worlds** — seeds with 5+ contributions auto-upgrade to World status
- **Notifications** — contributions, comments, branches and replies
- **JSON API** — every page also speaks JSON (see below)

---

## JSON API

All endpoints are under `/api/`. `POST` endpoints accept either form data (redirect responses, what the site's own forms send) or JSON bodies (JSON envelopes, what `app.js` sends). Writes require a session and the CSRF token (the `duoweilai_csrf` cookie echoed back in the `X-CSRF-Token` header or a `csrf` field).

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | `{ok, version, db}` |
| `GET /api/futures?page&per_page&cat&q` | Paginated list: `{ok, items, total, page, pages}` |
| `GET /api/futures/<short>` | Seed detail + contributions + comments + child branches |
| `GET /api/futures/<short>/contributions?type=` | Contributions, optionally filtered by type |
| `GET /api/futures/<short>/comments` | Flat comment list (with `parent_id` for replies) |
| `GET /api/notifications` | Notifications + unread count |
| `GET /api/users/<username>` | Profile stats + recent futures/contributions |
| `GET /api/feed?limit` | Recent activity across the site |
| `POST /api/register` `POST /api/login` `GET /api/logout` | Auth |
| `POST /api/forgot` `POST /api/reset/<token>` | Password reset |
| `POST /api/future` | Publish (`parent=<short>` to branch) |
| `POST /api/future/<short>/edit` | Edit own seed (title / body / category) |
| `POST /api/contribute` · `POST /api/contribution/<id>/edit` | Contribution write/edit |
| `POST /api/comment` · `POST /api/comment/<id>/edit` | Comment / reply write/edit |
| `POST /api/future/<short>/delete` etc. | Deletes (owner-checked, always JSON) |

Limits: POST 60/minute per IP (429), request body 64 KB, title ≤ 500 chars, body ≤ 10000, comment ≤ 5000.

---

## Design

Based on the v0.1 prototype design language:

- **Minimal dark UI** — near-black background (#0a0a0b), light text
- **Inter font** — clean, readable
- **English-first** — optimized for overseas (international) market
- **Pill buttons, dashed CTA boxes** — distinctive visual language

---

## Tech

- **Flask 3** (factory pattern in `app/create_app()`) + Jinja2 templates
- **SQLite** via the stdlib `sqlite3` — WAL mode, one connection per request, no ORM (schema stays 100% compatible with the original single-file version; migrations are additive `ALTER`s at startup)
- **Security**: CSRF double-submit tokens, per-IP POST rate limiting, security headers (CSP / nosniff / frame-deny), input caps, owner-checked edits and deletes
- **Production**: gunicorn + nginx (see `deploy/`)

---

## Project Structure

```
duoweilai-web/
├── server.py              # Dev entry: python server.py
├── requirements.txt       # flask (+ gunicorn off-Windows)
├── app/
│   ├── __init__.py        # create_app() factory + config
│   ├── db.py              # SQLite connection, schema, migrations
│   ├── auth.py            # sessions, register/login/reset, CSRF
│   ├── services.py        # Business logic (futures, contributions, ...)
│   ├── api.py             # /api/* routes (form + JSON negotiation)
│   ├── web.py             # Page routes
│   ├── security.py        # Rate limit, headers, input caps
│   ├── templates/         # Jinja2 pages
│   └── static/            # style.css, app.js
├── tests/                 # e2e / auth / api suites (self-contained)
├── deploy/                # setup.sh, systemd unit, nginx conf
└── archive/v0.1-prototypes/
```

---

## Tests

Each suite spins up its own server on its own port with a scratch database — nothing running beforehand, nothing left behind:

```bash
.venv/Scripts/python tests/e2e_test.py    # user journey over the HTML pages
.venv/Scripts/python tests/auth_test.py   # register / login / reset / CSRF
.venv/Scripts/python tests/api_test.py    # JSON API, edits, branches, limits
```

---

## Related

- [huliye24/duoweilai](https://github.com/huliye24/duoweilai) — Vision repository (imagination/world/story archives)

---

## License

[Apache License 2.0](./LICENSE)
