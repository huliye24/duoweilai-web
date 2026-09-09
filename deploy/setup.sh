#!/usr/bin/env bash
# Duoweilai 一键部署脚本（在 Linux 服务器上以 root 运行）
# 用法: 在仓库根目录执行  bash deploy/setup.sh
set -euo pipefail

APP_DIR=/opt/duoweilai
DOMAIN=duoweilai.com

echo "==> 1/8 安装依赖 (nginx, python3, venv)"
if command -v apt-get >/dev/null; then
    apt-get update -y && apt-get install -y nginx python3 python3-venv certbot python3-certbot-nginx
elif command -v dnf >/dev/null; then
    dnf install -y nginx python3 python3-pip certbot python3-certbot-nginx || {
        dnf install -y epel-release && dnf install -y certbot python3-certbot-nginx nginx python3 python3-pip; }
else
    echo "未识别的包管理器，请手动安装 nginx / python3 / certbot" && exit 1
fi

echo "==> 2/8 创建运行用户与目录"
id -u duoweilai >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin --home $APP_DIR duoweilai
mkdir -p $APP_DIR
# 注意：不要动 $APP_DIR/duoweilai.db —— 重复部署保留线上数据
cp -f server.py $APP_DIR/server.py
cp -f requirements.txt $APP_DIR/requirements.txt
rm -rf $APP_DIR/app          # 整目录替换，避免残留已删除的旧模块
cp -rf app $APP_DIR/app

echo "==> 3/8 Python 虚拟环境 + 安装依赖"
python3 -m venv $APP_DIR/venv
$APP_DIR/venv/bin/pip install --upgrade pip >/dev/null
$APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt

echo "==> 4/8 生成 session 密钥（已有则保留）"
if [ ! -f $APP_DIR/secret.env ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "DUOWEILAI_SECRET_KEY=$SECRET" > $APP_DIR/secret.env
fi
chown -R duoweilai:duoweilai $APP_DIR
chmod 755 $APP_DIR                      # nginx(www-data) 需要进入目录读取 /static/
chmod 600 $APP_DIR/secret.env
chmod 640 $APP_DIR/duoweilai.db 2>/dev/null || true   # 数据库不开放其他用户读

echo "==> 5/8 安装 systemd 服务"
cp -f deploy/duoweilai.service /etc/systemd/system/duoweilai.service
systemctl daemon-reload
systemctl enable --now duoweilai
systemctl restart duoweilai   # 重复部署时加载新代码

echo "==> 6/8 配置 nginx 反向代理"
# 只在首次安装时复制：certbot 之后会在该文件里追加 443/301 配置，重复部署不能覆盖
if [ ! -f /etc/nginx/conf.d/duoweilai.conf ]; then
    cp -f deploy/nginx-duoweilai.conf /etc/nginx/conf.d/duoweilai.conf
else
    echo "   /etc/nginx/conf.d/duoweilai.conf 已存在，保留（含 certbot 修改）"
fi
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
nginx -t && systemctl reload nginx

echo "==> 7/8 防火墙放行 80/443"
if command -v ufw >/dev/null && ufw status | grep -q active; then
    ufw allow 80/tcp && ufw allow 443/tcp
elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-service=http --add-service=https && firewall-cmd --reload
fi
# 云厂商安全组需自行放行 80/443

echo "==> 8/8 签发 HTTPS 证书 (Let's Encrypt)"
certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos \
    --register-unsafely-without-email --redirect || \
    echo "!! certbot 失败：请确认 DNS 已把 $DOMAIN 指向本机公网 IP 后重试: certbot --nginx -d $DOMAIN"

echo
echo "完成。检查："
echo "  systemctl status duoweilai --no-pager"
echo "  curl -s http://127.0.0.1:8090/api/health"
echo "  浏览器访问 https://$DOMAIN"
