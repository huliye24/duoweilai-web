# Duoweilai · Web

> **Plant a future seed. Watch it grow into a world.**

Duoweilai (多未来 · "Multiple Futures") is a collaborative imagination platform — anyone can publish a **Future Seed**: a "what if" question about a future that could be. Others can explore it, add to it, branch it, and help it grow into something richer.

**Core loop:** Publish a Future Seed → Get a permanent link → Others explore & contribute → The seed grows → Eventually becomes a **World**.

---

## Quick Start

**No dependencies.** Python 3.8+ only. No packages to install.

```bash
# Clone and run
git clone https://github.com/huliye24/duoweilai-web.git
cd duoweilai-web
python server.py
```

Then open **http://localhost:8080** in your browser.

> First run automatically creates `duoweilai.db`.

### Team (same network)

To let teammates access from other machines on the same LAN:

```bash
DUOWEILAI_BIND=0.0.0.0 python server.py
```

Then access via `http://<your-local-ip>:8080`.

### Custom port

```bash
DUOWEILAI_PORT=3000 python server.py
```

---

## Pages

| Route | Description |
|-------|-------------|
| `/` | Home — publish a future seed |
| `/explore` | Browse all published futures |
| `/f/<id>` | Future Seed detail — contribute, comment |
| `/world/<id>` | World view — rich multi-section exploration |
| `/person/<username>` | User profile |
| `/notifications` | Your notifications |
| `/login` `/register` | Account |

---

## Features

- **No-auth mode** — every visitor is auto-logged in as `explorer`, no sign-up/sign-in required (great for internal testing)
- **Future Seeds** — permanent, shareable "what if" imagination units
- **Contributions** — add People, Places, Stories, Rules, Objects, or Branches to a seed
- **Comments** — discuss each future
- **Worlds** — seeds with 5+ contributions auto-upgrade to World status
- **Notifications** — know when someone engages with your futures
- **User accounts** — cookie-based sessions, no email required (disabled in current build)

---

## Design

Based on the v0.1 prototype design language:

- **Minimal dark UI** — near-black background (#0a0a0b), light text
- **Inter font** — clean, readable
- **English-first** — optimized for overseas (international) market
- **Pill buttons, dashed CTA boxes** — distinctive visual language

---

## Tech

- **Single file** — `server.py` (~1300 lines), no external dependencies
- **Python stdlib only** — `sqlite3`, `http.server`, `http.cookies`
- **SQLite** — single-file database, no server required
- **Threaded HTTP server** — handles concurrent requests

---

## Project Structure

```
duoweilai-web/
├── server.py              # The app (single file, stdlib only)
├── tests/
│   ├── smoke_test.py       # Quick smoke test
│   └── e2e_test.py        # Full end-to-end API test
├── deploy/
│   ├── setup.sh           # Production deployment script (Linux)
│   ├── duoweilai.service  # systemd unit
│   └── nginx-duoweilai.conf
├── archive/
│   └── v0.1-prototypes/   # v0.1 static HTML designs (5 pages)
├── .gitignore
├── README.md
└── LICENSE
```

---

## Tests

```bash
# Make sure the server is running first
python server.py

# In another terminal
python tests/e2e_test.py
```

---

## Related

- [huliye24/duoweilai](https://github.com/huliye24/duoweilai) — Vision repository (imagination/world/story archives)

---

## License

[Apache License 2.0](./LICENSE)
