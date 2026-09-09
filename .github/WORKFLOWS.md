# CI/CD 流水线状态

## 工作流

| Workflow | 触发条件 | 作用 |
|----------|---------|------|
| `ci.yml` | PR + push | lint + typecheck + test 矩阵 (Python 3.10/3.11/3.12) + security audit |
| `deploy.yml` | push main | 自动部署到生产服务器（需配置 SSH secrets） |
| `release.yml` | push tag `v*` + 手动 | 校验版本 + 构建 + 创建 GitHub Release（可选手动部署） |

## 部署流程

```
开发者 push / merge PR 到 main
        ↓
   ┌────────┴────────┐
   │                  │
   ▼                  ▼
ci.yml         deploy.yml
(并行)           (等待 CI 通过)
   │                  │
   │                  ▼
   │            SSH 到服务器
   │                  │
   │                  ├─ git pull
   │                  ├─ 备份当前版本
   │                  ├─ 同步代码（保留 db / secret.env）
   │                  ├─ pip install（仅 requirements 变化时）
   │                  ├─ systemctl restart duoweilai
   │                  └─ /api/health 健康检查
   │                       │
   │                       ├─ 通过 ✓ → 部署完成
   │                       └─ 失败 ✗ → 自动回滚到上一备份
   ▼
PR 状态检查
```

## Secrets 配置（仓库 Settings → Secrets and variables → Actions）

| 名称 | 必填 | 说明 |
|------|------|------|
| `SSH_PRIVATE_KEY` | ✅ | GitHub Actions 与服务器通讯的 SSH 私钥 |
| `DEPLOY_HOST` | ✅ | 形如 `root@1.2.3.4` 或 `ubuntu@my.server.com` |
| `DEPLOY_PATH` | ⚠️ 推荐 | 服务器上应用目录，默认 `/opt/duoweilai` |
| `PIP_AUDIT_TOKEN` | ❌ 可选 | 私有 PyPI 索引 token（如有） |

## Variables（仓库 Settings → Variables）

| 名称 | 默认 | 说明 |
|------|------|------|
| `DEPLOY_HOST` | — | 用于显示部署目标（不暴露到日志） |
| `DEPLOY_PATH` | `/opt/duoweilai` | 应用目录 |

## 本地调试

```bash
make ci-locally    # 模拟 CI：lint + typecheck + test
make deploy HOST=user@server   # 手动 rsync 部署（不走 Actions）
```
