#!/usr/bin/env bash
# 生成 /etc/nginx/conf.d/00-cloudflare-realip.conf —— 从 Cloudflare 官方列表拉取
# IP 段，nginx 依据 CF-Connecting-IP 头还原真实访客 IP。
# 橙云代理后 $remote_addr 全是 CF 边缘 IP（日志失真、应用按 IP 限流会共享额度），
# 本脚本解决该问题；Cloudflare 更新网段后重跑一次即可。
# 用法: bash deploy/cloudflare-realip.sh
set -euo pipefail

CONF=/etc/nginx/conf.d/00-cloudflare-realip.conf

V4=$(curl -fsS --max-time 20 https://www.cloudflare.com/ips-v4 || true)
V6=$(curl -fsS --max-time 20 https://www.cloudflare.com/ips-v6 || true)
[ -n "$V4" ] || { echo "!! 拉取 Cloudflare IPv4 列表失败，保持现有配置不动"; exit 1; }

{
    echo "# 由 deploy/cloudflare-realip.sh 生成（重跑脚本即可刷新网段）"
    echo "# 生效后 \$remote_addr / access log / X-Real-IP 均为真实访客 IP"
    for ip in $V4 $V6; do
        echo "set_real_ip_from $ip;"
    done
    echo "real_ip_header CF-Connecting-IP;"
} > $CONF

nginx -t && systemctl reload nginx
echo "已写入 $CONF（$(echo $V4 $V6 | wc -w) 个网段）并 reload nginx"
