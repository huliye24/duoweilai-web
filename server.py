"""Duoweilai dev server (v0.6 — Flask).

Same launch command as always:
    python server.py

Production (see deploy/):
    gunicorn -w 4 -b 127.0.0.1:8090 "app:create_app()"
"""
import os

from app import create_app

PORT = int(os.environ.get("DUOWEILAI_PORT", "8080"))
BIND = os.environ.get("DUOWEILAI_BIND", "0.0.0.0")

app = create_app()

if __name__ == "__main__":
    local = "127.0.0.1" if BIND == "127.0.0.1" else BIND
    print(f"\n  Duoweilai v{app.config['VERSION']}  —  http://{local}:{PORT}")
    print(f"  Database: {app.config['DB_PATH']}")
    print(f"  Bind: {BIND}  Port: {PORT}\n")
    app.run(host=BIND, port=PORT, threaded=True)
