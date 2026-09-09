#!/usr/bin/env python3
"""
GitHub webhook listener for Duoweilai (v0.6).
Listens on port 9000, deploys on push to main.

v0.6 起应用跑在 /opt/duoweilai（gunicorn），仓库只是分发渠道：
push 到 main 后 = git pull + 把代码同步到 /opt/duoweilai + 重启服务。
线上数据库 /opt/duoweilai/duoweilai.db 与 session 密钥 secret.env 永远不动。
deploy/setup.sh / systemd 单元有改动时需手动执行 bash deploy/setup.sh。
"""
import http.server
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

PORT = 9000
LOG = Path("/var/log/duoweilai-deploy.log")
REPO_DIR = "/root/duoweilai-web"
APP_DIR = "/opt/duoweilai"
SERVICE_NAME = "duoweilai"
# 同步到 /opt/duoweilai 的内容（duoweilai.db / secret.env / venv 除外）
CODE_ITEMS = ["server.py", "requirements.txt", "app"]


def log(msg):
    ts = datetime.now().isoformat()
    with LOG.open("a") as f:
        f.write(f"[{ts}] {msg}\n")


def run(cmd, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    log(f"{' '.join(cmd)} -> exit={r.returncode}")
    if r.stdout and r.stdout.strip():
        log(f"  stdout: {r.stdout.strip()[:2000]}")
    if r.stderr and r.stderr.strip():
        log(f"  stderr: {r.stderr.strip()[:2000]}")
    return r


def deploy():
    log("Starting deploy...")
    pull = run(["git", "-C", REPO_DIR, "pull", "origin", "main"], timeout=60)
    if pull.returncode != 0:
        log("Deploy aborted: git pull failed")
        return False

    # 同步代码到运行目录（与 setup.sh 第 2/3 步一致，但不动 db/密钥/venv）
    for item in CODE_ITEMS:
        src = Path(REPO_DIR) / item
        dst = Path(APP_DIR) / item
        if dst.is_dir():
            shutil.rmtree(dst)  # 整目录替换，避免残留已删除的旧模块
        try:
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except OSError as e:
            log(f"Deploy aborted: copy {item} failed: {e}")
            return False
    run(["chown", "-R", "duoweilai:duoweilai", APP_DIR], timeout=60)
    run([f"{APP_DIR}/venv/bin/pip", "install", "-q", "-r",
         f"{APP_DIR}/requirements.txt"], timeout=300)
    run(["systemctl", "restart", SERVICE_NAME], timeout=30)
    status = run(["systemctl", "is-active", SERVICE_NAME], timeout=10)
    ok = status.returncode == 0
    log(f"Deploy finished, service active={ok}")
    return ok


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="ignore")
        event = self.headers.get("X-GitHub-Event", "")
        log(f"Received event: {event}, body len={length}")
        if event == "push" and "refs/heads/main" in body:
            log("Push to main detected, deploying...")
            ok = deploy()
            code = 200 if ok else 500
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"Deploy triggered.\n" if ok else b"Deploy failed.\n")
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Ignored.\n")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Duoweilai webhook listener alive.\n")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    log("Webhook listener starting...")
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
