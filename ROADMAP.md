# Duoweilai.com 项目路线图（Roadmap）

> 渐进式多语言架构演进路线图
> 策略：**Strangler Fig（绞杀者模式）** —— 不重构，新功能写在新栈里，老功能保留直至退役。
> 上次更新：2026-09-10

---

## 0. 总体战略

### 0.1 现状盘点

| 维度 | 现状 | 评价 |
|---|---|---|
| 后端 | Flask 3.0 + Python 3.11 + SQLite + gunicorn | 生产可用，类型检查薄弱 |
| 前端 | Flask Jinja templates + 原生 JS | 易改易错，无编译期保护 |
| 新前端原型 | Next.js 14 + TypeScript（`duoweilai-web/`） | 已存在但未联调 |
| 测试 | pytest（API/auth/e2e/logging） | 覆盖中等 |
| CI | `.github/workflows/ci.yml` | 已建，未验 |
| 部署 | `deploy/setup.sh` + `deploy/deploy.sh` + systemd + nginx | 已建 |
| 监控/日志 | 自写 `app/logging_setup.py` + nginx log | 够用，待扩 |
| 自动部署 | `.github/workflows/deploy.yml` + webhook | 已建，待配 SSH key |

### 0.2 演进原则

1. **不重构**。所有现有 Flask 代码保持运行。
2. **新功能用新栈**。前端新页面用 Next.js + TS；后端新服务按需用 Go/Rust。
3. **类型安全优先**。任何语言都要开 strict type check。
4. **生产优先**。里程碑完成意味着"用户能看到/用到"，不是"代码写好"。
5. **可回滚**。每次部署保留上一版本可启动。

### 0.3 语言分工

| 层 | 主语言 | 备选 | 引入时机 |
|---|---|---|---|
| 前端 SPA/SSR | TypeScript (Next.js) | — | v0.8 |
| 后端 API 主服务 | Python (Flask) | — | v0.7 硬化 |
| 后端请求/响应校验 | Python (pydantic v2) | — | v0.7 |
| 异步任务/调度 | Python (RQ/Celery) | Go | v0.10 |
| 全文搜索 | Python (SQLite FTS5) → Go (Bleve) | — | v1.2 视规模 |
| 图片处理 | Python (Pillow) | Rust (image crate) | v1.3 视瓶颈 |
| 高 QPS 微服务 | — | Go → Rust | v1.5+ 视流量 |

---

## 1. 里程碑时间表

```
v0.6.1  ●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2026-09 当前（生产）
        │
        ▼
v0.7    里程碑 1：后端硬化（mypy strict + pydantic）        1-2 周
        │
        ▼
v0.8    里程碑 2：Next.js 前端联调，HTML → TS 替换          2-3 周
        │
        ▼
v0.9    里程碑 3：CI/CD 自动化（Actions + SSH key + Secrets） 1 周
        │
        ▼
v1.0    里程碑 4：第一个正式版本（去掉所有 .html 渲染）       2 周
        │
        ▼
v1.1    里程碑 5：性能基线 + 缓存层                          2 周
        │
        ▼
v1.2    里程碑 6：搜索硬化（SQLite FTS5 → 必要时 Go）        1-2 周
        │
        ▼
v1.3    里程碑 7：图片管线（按需 Rust）                       2 周
        │
        ▼
v1.5    里程碑 8：高 QPS 微服务拆分（Go 优先）               2-4 周
        │
        ▼
v2.0    里程碑 9：多语言生态稳定，Flask 退役                  4 周
```

---

## 2. 里程碑详述

### M0 · 当前状态 · v0.6.1

**生产在跑**：Flask 后端 + Jinja templates + SQLite + Cloudflare + nginx + systemd

**已知债务**：
- HTML templates 无类型保护（这是 v0.8 要解决的）
- API endpoint 手写校验（这是 v0.7 要解决的）
- 自动部署未启用（这是 v0.9 要解决的）

**冻结原则**：此阶段**只修 bug，不加新功能**。

---

### M1 · v0.7 · 后端硬化（**优先级：最高**）

**目标**：把现有 Flask 后端的类型安全和校验能力提到 TS 等价水平。

**任务清单**：
- [ ] `pyproject.toml` 加 pydantic v2 依赖（`pydantic[email]>=2.6`）
- [ ] `app/api.py` 所有 endpoint 改用 `BaseModel` 输入/输出
- [ ] `app/web.py` 表单 endpoint 加 pydantic 校验
- [ ] `pyproject.toml` `[tool.mypy]` 加 `strict = true`
- [ ] 修复 mypy 报错（预计 30-80 处，主要是 Flask 装饰器和 `request.json` 类型）
- [ ] CI 加 `mypy app/` 步骤，失败即阻合并
- [ ] CI 加 `ruff check .` 步骤
- [ ] 加 `app/validators/` 子包，统一复用校验器

**验收标准**：
- `mypy --strict app/` 零报错
- `pytest tests/` 全部通过
- 任何 `request.json["xxx"]` 直接取值**消失**（必须经过 BaseModel）

**风险**：
- Flask `@app.route` 装饰器对 mypy 不友好，需要 `Annotated` + `flask-typing` 或自定义 stub
- pydantic v2 与现有手写校验并存期可能产生行为差异

**估计工时**：3-5 天

---

### M2 · v0.8 · Next.js 前端联调

**目标**：用 Next.js + TS 替换 Flask 渲染的 HTML 页面，但后端 API 保持不变。

**任务清单**：
- [ ] `duoweilai-web/` 项目结构对齐现有路由
- [ ] 实现首页（`/`） → 复用 `app/templates/home.html`
- [ ] 实现登录页（`/login`）
- [ ] 实现注册页（`/register`）
- [ ] 实现忘记密码（`/forgot`）
- [ ] 实现重置密码（`/reset?token=...`）
- [ ] 实现世界页（`/world/[slug]`）
- [ ] 实现个人页（`/person/[username]`）
- [ ] 实现探索页（`/explore`）
- [ ] 实现通知页（`/notifications`）
- [ ] 实现 seed 创建（`/seed/new`）
- [ ] `tsconfig.json` 开 `strict: true`
- [ ] Next.js API 路由转发到 Flask（避免 CORS 复杂）
- [ ] 同一域名下用 nginx 区分路径：`/api/*` → Flask，`/*` → Next.js
- [ ] 关闭 Flask 模板渲染（`render_template` 调用保留但前端不再用）

**验收标准**：
- 所有页面在 Next.js 下渲染一致（视觉 diff < 5%）
- `tsc --noEmit` 零报错
- `next build` 成功
- 所有 API 调用走 Next.js API 路由（客户端不直接连 Flask）

**风险**：
- Session/Cookie 跨服务需要 same-site=None; Secure
- 静态资源路径需要重定向

**估计工时**：10-15 天

---

### M3 · v0.9 · CI/CD 自动化

**目标**：push 到 main 后自动部署到服务器，全程无人值守。

**任务清单**：
- [ ] 服务器端跑 `bash deploy/setup.sh`（一次性）
- [ ] 生成专用 SSH key 给 GitHub Actions：
  ```bash
  ssh-keygen -t ed25519 -C "github-actions-deploy" -f /root/.ssh/github_actions
  cat /root/.ssh/github_actions.pub >> /root/.ssh/authorized_keys
  ```
- [ ] 把 `/root/.ssh/github_actions`（私钥）内容贴到 GitHub Secret `SSH_KEY`
- [ ] 把服务器地址贴到 GitHub Secret `HOST`
- [ ] 把部署用户名贴到 GitHub Secret `USER`（通常 `deploy` 或 `root`）
- [ ] GitHub Actions workflow 启用 `.github/workflows/deploy.yml`
- [ ] 测试推送触发部署
- [ ] 失败回滚：保留上一版本的 systemd unit / Docker tag

**验收标准**：
- push 到 main → 服务器 60 秒内自动重启服务
- 失败时自动回滚到上一版本
- 部署日志可在 GitHub Actions 页面查看

**风险**：
- SSH key 泄露 → 必须 `chmod 600`，GitHub Secret 启用环境保护
- 数据库迁移方向错误 → 部署前必须备份 SQLite

**估计工时**：2-3 天

---

### M4 · v1.0 · 第一个正式版本

**目标**：所有用户可见页面都在 Next.js 上；Flask 只剩 JSON API。

**任务清单**：
- [ ] 删除所有 Flask `render_template` 调用
- [ ] 删除 `app/templates/*.html`
- [ ] 移除 Flask `static/` 静态资源
- [ ] API 文档自动生成（OpenAPI via pydantic + flask-openapi3）
- [ ] 版本号写入 `app/__init__.py` 和 `package.json`
- [ ] 发版说明自动生成（git-cliff 或 release-please）
- [ ] 域名切换到主域名（如果之前用临时域名）

**验收标准**：
- 用户访问 `https://duoweilai.com` 看到的全 TS/React 渲染
- HTML 模板代码 0 行
- 测试覆盖率 ≥ 70%
- 文档站点上线

**估计工时**：5-7 天

---

### M5 · v1.1 · 性能基线 + 缓存

**目标**：建立性能基线，识别瓶颈。

**任务清单**：
- [ ] 加 `prometheus-client` Python 指标暴露
- [ ] nginx 加 `nginx-prometheus-exporter`
- [ ] Grafana 仪表板（vps 上跑一个 docker）
- [ ] 加 Redis 做 session/缓存层（Flask-Session + Flask-Caching）
- [ ] 静态资源加 Cloudflare Cache
- [ ] ETag / Last-Modified 头
- [ ] 慢查询日志（SQLite `PRAGMA log_duration`）

**验收标准**：
- 首页 P95 < 200ms（Cloudflare 后）
- API P95 < 100ms
- Prometheus 抓取 9 个核心指标（QPS/P95/error%）

**估计工时**：7-10 天

---

### M6 · v1.2 · 搜索硬化

**触发条件**：种子数据 > 5000 行，或探索页 P95 > 300ms。

**任务清单**：
- [ ] 短期：SQLite FTS5 虚拟表 + 触发器同步
- [ ] 中期：若仍不够，Go 微服务跑 Bleve，独立仓库 `duoweilai-search/`
- [ ] Flask 用 HTTP 调用，gRPC 留给 v1.5

**验收标准**：
- 10000 行数据下，探索页 P95 < 100ms

---

### M7 · v1.3 · 图片管线

**触发条件**：用户上传头像/封面，Pillow 处理成为瓶颈。

**任务清单**：
- [ ] 短期：Pillow + asyncio
- [ ] 中期：Rust 独立服务 `duoweilai-image/`，用 `image` crate + `axum`
- [ ] Docker 多阶段构建，最小化镜像
- [ ] CDN 接管静态资源

**估计工时**：5-7 天

---

### M8 · v1.5 · 高 QPS 微服务拆分

**触发条件**：单一 endpoint QPS > 500/s。

**任务清单**：
- [ ] 用 Go 写 `duoweilai-feed/`，承载"首页推荐"流
- [ ] gRPC 内部通信，HTTP 公开
- [ ] 读写分离：Flask 写，Go 读
- [ ] 渐进迁移：双写期 → 切读 → 停写

**估计工时**：10-15 天

---

### M9 · v2.0 · 多语言生态稳定

**目标**：Flask 退役或仅保留边缘接口。

**任务清单**：
- [ ] 拆分后的微服务清单：
  - `duoweilai-web`        — Next.js 前端（TS）
  - `duoweilai-api`        — 主 API（Go）
  - `duoweilai-search`     — 搜索（Go）
  - `duoweilai-image`      — 图片（Rust）
  - `duoweilai-feed`       — Feed（Go/Rust）
  - `duoweilai-notify`     — 通知（Go）
- [ ] 统一 monorepo（pnpm workspace + Bazel 或 Turborepo）
- [ ] API gateway（Kong / Traefik / 自写 nginx 路由）
- [ ] 集中日志（Loki / ELK）
- [ ] 集中 metrics（Prometheus + Grafana）

**验收标准**：
- 所有服务独立部署
- 单服务崩溃不影响全局
- p99 < 50ms 核心 API

---

## 3. 风险登记

| 风险 | 等级 | 缓解措施 |
|---|---|---|
| Flask 后端 mypy 报错过多 | 中 | 渐进开启 strict，分文件加 `# type: ignore` |
| Next.js CORS/Session 问题 | 中 | 用同源反向代理，不要让浏览器跨域 |
| SSH key 泄露 | 高 | GitHub Secret 环境保护 + 定期轮换 + `from-where` 限制 |
| SQLite 写并发瓶颈 | 低-中 | v0.10 评估迁移到 PostgreSQL |
| 团队只有 1 人（你） | 高 | 每个里程碑明确"如果中断，能恢复" |
| 时间估计偏乐观 | 中 | 每个里程碑留 50% buffer |

---

## 4. 决策记录（ADR）

### ADR-001 · 不用 Node.js 后端

**日期**：2026-09-10
**状态**：已接受

**背景**：用户提到多语言，没排除 Node。

**决定**：后端主服务**不**用 Node.js/Express。原因：
- Python 已有生态（pydantic, flask, sqlalchemy）无需重置
- Node.js 性能优势在 v1.5+ 才需要（届时选 Go 性能更好）

### ADR-002 · 多语言策略：Strangler Fig

**日期**：2026-09-10
**状态**：已接受

**决定**：不重构，按层渐进替换。

### ADR-003 · 微服务时机由数据触发，不由时间触发

**日期**：2026-09-10
**状态**：已接受

**决定**：不预设"明年上 Go"。每次拆分前必须有可观测的瓶颈证据（CPU/P95/QPS）。

---

## 5. 立即可做清单（今天）

按依赖顺序，今天能推进的：

- [ ] **M1 启动**：本地 `pip install pydantic[email]`，新建 `app/validators/` 目录
- [ ] **M3 准备**：在服务器跑 `bash deploy/setup.sh`，生成 SSH key
- [ ] **GitHub Secrets 填值**：`SSH_KEY` / `HOST` / `USER`
- [ ] **文档同步**：把这份 ROADMAP.md commit 到 `duoweilai-web-github/`
- [ ] **CI 验证**：本地跑 `pytest tests/`，看 CI 是否在 main 上绿

---

## 6. 度量与回顾

每完成一个里程碑，做一次回顾：
- 完成度 = 已验收任务 / 总任务
- 实际工时 vs 估计工时
- 新增技术债务条目
- 决策是否需要调整

---

> **维护者**：项目所有者
> **审阅周期**：每两周一次
> **下一次审阅**：v0.7 完成时
