"""Duoweilai app factory (v0.6 — Flask).

Dev:      python server.py
Prod:     gunicorn -w 4 -b 127.0.0.1:8090 "app:create_app()"

Env vars (same names as v0.5):
  DUOWEILAI_PORT           dev-server port (default 8080)
  DUOWEILAI_BIND           dev-server bind address (default 0.0.0.0)
  DUOWEILAI_DB             sqlite path (default <repo>/duoweilai.db)
  DUOWEILAI_SECURE_COOKIE  "1" to mark cookies Secure (behind HTTPS)
  DUOWEILAI_SMTP_*         password-reset mail (see services.log_password_reset)
  DUOWEILAI_LOG_LEVEL      DEBUG/INFO/WARNING/ERROR (default INFO)
  DUOWEILAI_LOG_FORMAT     human / json (default human; json 便于日志聚合)
"""

import os
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request

from . import auth, db, logging_setup, security, services
from .api import api
from .web import TYPE_SECTIONS, web

VERSION = "0.6"


def create_app():
    root = Path(__file__).resolve().parent.parent
    app = Flask(__name__)

    # 结构化日志（human 彩色 / json 行式），由环境变量控制
    logging_setup.setup_logging()

    app.config.update(
        VERSION=VERSION,
        SECRET_KEY=os.environ.get("DUOWEILAI_SECRET_KEY", "duoweilai-dev"),
        DB_PATH=os.environ.get("DUOWEILAI_DB") or str(root / "duoweilai.db"),
        SECURE_COOKIE=os.environ.get("DUOWEILAI_SECURE_COOKIE", "") == "1",
        MAX_CONTENT_LENGTH=64 * 1024,  # past this -> 413
    )

    # Schema + additive migrations + session cleanup — startup only,
    # never per request (v0.5 did it 200 times a minute).
    db.init_db(app.config["DB_PATH"])

    app.register_blueprint(api)
    app.register_blueprint(web)

    # 请求生命周期日志中间件（g.request_id 可在代码中访问）
    logging_setup.install_request_logging(app)

    # Template globals
    app.jinja_env.globals.update(
        rel_time=services.rel_time,
        avatar_initial=services.avatar_initial,
        csrf_token=auth.csrf_token,
        TYPE_EN=services.TYPE_EN,
        TYPE_SECTIONS=TYPE_SECTIONS,
        CATEGORIES=services.CATEGORIES,
    )

    @app.context_processor
    def inject_user():
        user = dict(g.user) if g.get("user") else None
        unread = services.unread_count(user["id"]) if user else 0
        return {"user": user, "unread": unread}

    # Request pipeline: CSRF token first (verify needs it), then the
    # flood gate, then the CSRF check, then the signed-in user.
    @app.before_request
    def _pipeline():
        if request.path.startswith("/static/"):
            return None
        auth.ensure_csrf()
        blocked = security.rate_limit_check()
        if blocked:
            return blocked
        blocked = auth.verify_csrf()
        if blocked:
            return blocked
        auth.load_user()

    @app.after_request
    def _respond(resp):
        resp = security.add_security_headers(resp)
        resp = auth.set_csrf_cookie(resp)
        resp = auth.apply_session_cookie(resp)
        return resp

    app.teardown_appcontext(db.close_db)

    def _wants_json():
        return request.path.startswith("/api/")

    @app.errorhandler(404)
    def _404(_e):
        if _wants_json():
            return jsonify({"ok": False, "error": "Not found"}), 404
        return render_template("error.html", title="404", message="This page doesn't exist."), 404

    @app.errorhandler(405)
    def _405(_e):
        if _wants_json():
            return jsonify({"ok": False, "error": "Method not allowed"}), 405
        return render_template("error.html", title="405", message="Method not allowed."), 405

    @app.errorhandler(413)
    def _413(_e):
        if _wants_json():
            return jsonify({"ok": False, "error": "Payload too large."}), 413
        return render_template(
            "error.html", title="413", message="That submission is too large."
        ), 413

    @app.errorhandler(500)
    def _500(_e):
        if _wants_json():
            return jsonify({"ok": False, "error": "Internal server error"}), 500
        return render_template(
            "error.html", title="500", message="Something broke on our side."
        ), 500

    return app
