#!/usr/bin/env bash
# ============================================================
# Duoweilai Web · 增量远程更新
# ============================================================
# 与 deploy/setup.sh 互补：
#   setup.sh  → 首次部署（安装系统依赖、配 nginx、签证书）
#   deploy.sh → 后续增量更新（同步代码、重启服务、滚动日志）
#
# 用法:
#   ./deploy/deploy.sh user@server
#   make deploy HOST=user@server
#
# 前置条件:
#   - 已有 SSH 公钥在服务器的 ~/.ssh/authorized_keys
#   - 服务器上已经跑过一次 setup.sh（systemd 单元已就位）
# ============================================================
set -euo pipefail

HOST=${1:?"用法: $0 user@server"}
APP_DIR=/opt/duoweilai
SERVICE=duoweilai
REMOTE_TMP=/tmp/duoweilai-deploy

# 本仓库根目录（脚本所在目录的父目录）
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> 目标服务器: $HOST"
echo "==> 应用目录:   $APP_DIR"
echo "==> 本地仓库:   $REPO_ROOT"
echo ""

# ---------- 1. 打包本地变更 ----------
echo "==> 1/5 打包本地源码（排除 .git、__pycache__、测试数据库）"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
tar --exclude='.git' \
    --exclude='.venv' --exclude='venv' \
    --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.test-db-*' --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' \
    --exclude='.mypy_cache' --exclude='.ruff_cache' --exclude='htmlcov' \
    --exclude='node_modules' --exclude='.next' \
    --exclude='archive' \
    -czf "$TMP/duoweilai.tar.gz" -C "$REPO_ROOT" .
echo "    包大小: $(du -h "$TMP/duoweilai.tar.gz" | cut -f1)"

# ---------- 2. 上传到服务器 ----------
echo "==> 2/5 上传到 $HOST:$REMOTE_TMP/"
ssh "$HOST" "mkdir -p $REMOTE_TMP"
rsync -avz --progress "$TMP/duoweilai.tar.gz" "$HOST:$REMOTE_TMP/"

# ---------- 3. 解压并原子化替换 ----------
echo "==> 3/5 在服务器上解压（保留数据库与 secret.env）"
ssh "$HOST" <<EOF
set -e
cd $APP_DIR

# 备份当前版本（5 个快照轮转）
BACKUP_DIR=$APP_DIR/.backups
mkdir -p "\$BACKUP_DIR"
ts=\$(date +%Y%m%d-%H%M%S)
tar -czf "\$BACKUP_DIR/app-\$ts.tar.gz" \\
    --exclude='duoweilai.db' --exclude='secret.env' \\
    --exclude='venv' --exclude='__pycache__' \\
    app/ server.py requirements.txt 2>/dev/null || true

# 只保留最近 5 个备份
ls -1t "\$BACKUP_DIR"/app-*.tar.gz 2>/dev/null | tail -n +6 | xargs -r rm -f
echo "    备份: \$BACKUP_DIR/app-\$ts.tar.gz"

# 提取新代码到临时目录，再原子移动
rm -rf $REMOTE_TMP/extracted
mkdir -p $REMOTE_TMP/extracted
tar -xzf $REMOTE_TMP/duoweilai.tar.gz -C $REMOTE_TMP/extracted

# 整目录替换（删除后重建，避免残留旧文件）
rm -rf $APP_DIR/app
mv $REMOTE_TMP/extracted/app $APP_DIR/app
[ -f $REMOTE_TMP/extracted/server.py ] && mv $REMOTE_TMP/extracted/server.py $APP_DIR/server.py
[ -f $REMOTE_TMP/extracted/requirements.txt ] && mv $REMOTE_TMP/extracted/requirements.txt $APP_DIR/requirements.txt
[ -f $REMOTE_TMP/extracted/pyproject.toml ] && mv $REMOTE_TMP/extracted/pyproject.toml $APP_DIR/pyproject.toml

# 清理临时
rm -rf $REMOTE_TMP
EOF

# ---------- 4. 重启服务 ----------
echo "==> 4/5 重启 systemd 服务"
ssh "$HOST" <<EOF
set -e
sudo systemctl restart $SERVICE
sleep 2
sudo systemctl is-active --quiet $SERVICE && echo "    ✓ 服务已启动"
sudo systemctl status $SERVICE --no-pager | head -8
EOF

# ---------- 5. 健康检查 ----------
echo "==> 5/5 健康检查"
HEALTH=$(ssh "$HOST" "curl -fsS http://127.0.0.1:8090/api/health" 2>&1) && {
    echo "    ✓ /api/health 返回: $HEALTH"
} || {
    echo "    ✗ 健康检查失败！最近日志："
    ssh "$HOST" "sudo journalctl -u $SERVICE -n 30 --no-pager"
    exit 1
}

echo ""
echo "✓ 部署完成"
echo "  - 跟踪日志:    ssh $HOST 'sudo journalctl -u $SERVICE -f'"
echo "  - 状态查看:    ssh $HOST 'sudo systemctl status $SERVICE'"
