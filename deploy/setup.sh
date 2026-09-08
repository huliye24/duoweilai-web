#!/usr/bin/env bash
# Duoweilai 一键部署脚本（在 Linux 服务器上以 root 运行）
# 用法: bash setup.sh
set -euo pipefail

APP_DIR=/opt/duoweilai
DOMAIN=duoweilai.com

echo "==> 1/6 安装依赖 (nginx, python3)"
if command -v apt-get >/dev/null; then
    apt-get update -y && apt-get install -y nginx python3 certbot python3-certbot-nginx
elif command -v dnf >/dev/null; then
    dnf install -y nginx python3 certbot python3-certbot-nginx || {
        dnf install -y epel-release && dnf install -y certbot python3-certbot-nginx nginx python3; }
else
    echo "未识别的包管理器，请手动安装 nginx / python3 / certbot" && exit 1
fi

echo "==> 2/6 创建运行用户与目录"
id -u duoweilai >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin --home $APP_DIR duoweilai
mkdir -p $APP_DIR
cp -f server.py $APP_DIR/server.py
chown -R duoweilai:duoweilai $APP_DIR
chmod 750 $APP_DIR

echo "==> 3/6 安装 systemd 服务"
cp -f deploy/duoweilai.service /etc/systemd/system/duoweilai.service
systemctl daemon-reload
systemctl enable --now duoweilai

echo "==> 4/6 配置 nginx 反向代理"
cp -f deploy/nginx-duoweilai.conf /etc/nginx/conf.d/duoweilai.conf
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
nginx -t && systemctl reload nginx

echo "==> 5/6 防火墙放行 80/443"
if command -v ufw >/dev/null && ufw status | grep -q active; then
    ufw allow 80/tcp && ufw allow 443/tcp
elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-service=http --add-service=https && firewall-cmd --reload
fi
# 云厂商安全组需自行放行 80/443

echo "==> 6/6 签发 HTTPS 证书 (Let's Encrypt)"
certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos \
    --register-unsafely-without-email --redirect || \
    echo "!! certbot 失败：请确认 DNS 已把 $DOMAIN 指向本机公网 IP 后重试: certbot --nginx -d $DOMAIN"

echo
echo "完成。检查："
echo "  systemctl status duoweilai --no-pager"
echo "  curl -sI http://127.0.0.1:8080 | head -1"
echo "  浏览器访问 https://$DOMAIN"
