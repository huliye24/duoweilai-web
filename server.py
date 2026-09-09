"""Duoweilai dev server (v0.6 — Flask).

Same launch command as always:
    python server.py

Production (see deploy/):
    gunicorn -w 4 -b 127.0.0.1:8090 "app:create_app()"

Admin helper (靓号 delivery — create an account with a chosen ID):
    python server.py adduser 888888 buyer@example.com their-password
"""
import os
import sys

from app import create_app

PORT = int(os.environ.get("DUOWEILAI_PORT", "8080"))
BIND = os.environ.get("DUOWEILAI_BIND", "0.0.0.0")

app = create_app()


def _adduser(argv):
    """Create an account with a hand-picked ID (靓号, or any reserved
    number). Registration never hands these out automatically."""
    if len(argv) != 3:
        print("Usage: python server.py adduser <id> <email> <password>")
        return 1
    sysid, email, password = argv[0].strip(), argv[1].strip(), argv[2]
    with app.app_context():
        from app import auth
        if not auth.valid_username(sysid):
            print("ID must be 3-20 letters, digits, or underscore.")
            return 1
        if auth.get_user_by_username(sysid):
            print(f"ID {sysid} is already taken.")
            return 1
        uid = auth.create_user(sysid, password, email or None)
        if not uid:
            print("Could not create the account (email already in use?).")
            return 1
        print(f"Created account: ID {sysid}  email {email or '(none)'}  (users.id={uid})")
        return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "adduser":
        sys.exit(_adduser(sys.argv[2:]))
    local = "127.0.0.1" if BIND == "127.0.0.1" else BIND
    print(f"\n  Duoweilai v{app.config['VERSION']}  —  http://{local}:{PORT}")
    print(f"  Database: {app.config['DB_PATH']}")
    print(f"  Bind: {BIND}  Port: {PORT}\n")
    app.run(host=BIND, port=PORT, threaded=True)
