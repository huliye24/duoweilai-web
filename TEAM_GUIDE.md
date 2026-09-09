# Team Guide · 团队内部使用指南

> English version of the app, designed for overseas market.
> 中文说明，帮你快速上手本地运行和内部测试。

---

## 如何启动（本地运行）

### 1. 安装 Python

确保安装了 Python 3.10+：

```powershell
python --version
```

如果没有，[官网下载](https://www.python.org/downloads/)安装，安装时勾选 **Add Python to PATH**。

### 2. 拉取代码

```bash
git clone https://github.com/huliye24/duoweilai-web.git
cd duoweilai-web
```

### 3. 安装依赖（v0.6 起需要 Flask）

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

> 只需做一次。以后拉取新代码后如果 requirements.txt 有变化，再跑一遍第 2 条命令即可。

### 4. 启动服务

```powershell
.venv\Scripts\python server.py
```

打开浏览器访问 **http://localhost:8080**

> 首次运行会自动创建 `duoweilai.db` 数据库文件。

### 5. 让团队成员也能访问

如果团队成员在同一局域网内，可以让他们也访问你的服务：

**Windows 查看本机 IP：**
```powershell
ipconfig
```
找到类似 `192.168.x.x` 的地址。

**启动时指定监听所有网卡：**
```powershell
set DUOWEILAI_BIND=0.0.0.0
.venv\Scripts\python server.py
```

然后团队成员通过 `http://你的IP:8080` 访问。

**macOS / Linux：**
```bash
DUOWEILAI_BIND=0.0.0.0 .venv/bin/python server.py
```

### 6. 自定义端口

默认端口是 8080，可以改成其他端口：

```powershell
set DUOWEILAI_PORT=3000
.venv\Scripts\python server.py
```

---

## 账号系统

**需要注册账号。** 点击右上角 **Sign up** 注册（用户名 3–20 位字母数字，邮箱可用来找回密码）。

- 注册后自动登录，浏览器记住你 30 天
- 忘记密码：登录页点 **Forgot password?**，未配置邮件服务时，重置链接会写到项目根目录的 `reset_link.log` 里，打开即可重置
- 所有成员各自有账号，发布/贡献/评论都记在自己名下

> v0.4 时期的"免注册 explorer 模式"已在 v0.5 移除，现在和公网版本行为一致。

---

## 功能一览

| 功能 | 说明 |
|------|------|
| **Publish a Future** | 首页输入框，写下一个"如果..."，发布后获得永久链接 |
| **Explore** | /explore 页面，支持**搜索**、**分类筛选**、**翻页** |
| **Contribute** | 在种子详情页，可以添加 People / Place / Story / Rule / Object |
| **Branch** | 从一个种子派生出新的未来，父种子页会列出 Recent Branches |
| **Comment & Reply** | 对未来发表评论，回复别人的评论 |
| **Edit** | 自己发布的种子/贡献/评论都可以编辑（显示 "edited"） |
| **World** | 当一个种子获得 5 个以上贡献，会自动升级为 World |
| **Notifications** | 有人贡献/评论/回复/Branch 你的内容时会收到通知 |
| **Profile** | /person/你的用户名，查看你发起和贡献的内容 |
| **JSON API** | 所有数据都有 /api/ 接口，方便做客户端或集成（见 README） |

---

## 设计语言

UI 延续 v0.1 原型的风格：

- **深色极简**：背景 #0a0a0b，文字 #f4f4f5
- **Inter 字体**：干净、现代
- **英文优先**：面向海外市场
- **药丸按钮、虚线 CTA 框**：标志性的视觉语言

---

## 运行测试

测试**自动启动自己的服务**（独立端口 + 一次性数据库），不需要先手动启动服务：

```powershell
.venv\Scripts\python tests\e2e_test.py    # 完整用户旅程
.venv\Scripts\python tests\auth_test.py   # 注册/登录/找回密码/CSRF
.venv\Scripts\python tests\api_test.py    # JSON API/编辑/Branch/限流
```

三个文件互相独立，可以任何顺序跑。

---

## 数据库

数据存储在 `duoweilai.db`（SQLite），首次启动自动创建；以后每次启动自动补齐新字段（增量迁移，不动已有数据）。

**重要：`duoweilai.db` 不要提交到 git，也不要随手删除——里面是所有人的数据。**

**重置数据库（清空所有数据，慎用）：**

```powershell
# 先停止服务，建议先备份
Copy-Item duoweilai.db duoweilai.db.bak
Remove-Item duoweilai.db -Force
# 重启服务后会自动创建新数据库
.venv\Scripts\python server.py
```

**数据库位置：** `E:\Duoweilai.com\duoweilai.db`（当前项目根目录）

---

## 目录结构

```
E:\Duoweilai.com\
├── server.py              # 启动入口（python server.py）
├── requirements.txt       # 依赖（flask）
├── app/                   # v0.6 后端（Flask）
│   ├── __init__.py        # create_app() 工厂
│   ├── db.py              # 数据库连接/建表/增量迁移
│   ├── auth.py            # 会话、注册登录、CSRF
│   ├── services.py        # 业务逻辑
│   ├── api.py             # /api/ 路由
│   ├── web.py             # 页面路由
│   ├── security.py        # 限流、安全头、长度上限
│   ├── templates/         # 页面模板
│   └── static/            # style.css / app.js
├── duoweilai.db           # SQLite 数据库（不要提交到 git）
├── tests/                 # e2e / auth / api 三套测试
├── archive/
│   └── v0.1-prototypes/  # v0.1 的 5 个原始 UI 设计（参考用）
├── deploy/                # 生产部署（Linux + nginx + systemd + gunicorn）
├── README.md              # English 说明文档（含 API 文档）
├── TEAM_GUIDE.md          # 本文件（中文团队指南）
└── .gitignore
```

---

## 常见问题

**Q: 服务启动报错 "Port already in use"**
> 8080 端口被占用。先 `Get-Process python | Stop-Process -Force`，或改用其他端口 `set DUOWEILAI_PORT=3000` 再启动。

**Q: 启动报错 ModuleNotFoundError: No module named 'flask'**
> 忘了装依赖，或没用 venv。执行 `python -m venv .venv` + `.venv\Scripts\pip install -r requirements.txt`，然后用 `.venv\Scripts\python server.py` 启动。

**Q: 注册时提示 "Username already taken"**
> 该用户名已被占用。换一个用户名即可。

**Q: 贡献/评论时提示 "Sign in required"**
> 需要先登录。未登录用户不能发布内容。

**Q: 找回密码点提交后说 "Check your inbox"，但没收到邮件**
> 本地没配 SMTP 时，重置链接写在项目根目录 `reset_link.log`，打开文件里的链接即可重置。

**Q: 想清空所有数据重新开始**
> 停止服务（建议先备份），删除 `duoweilai.db`，重新启动。

---

## 下一步（生产部署）

内部测试稳定后，在 Linux 服务器上进入仓库根目录执行：

```bash
bash deploy/setup.sh
```

包含：nginx 反向代理 + Let's Encrypt HTTPS 证书 + systemd 服务（gunicorn 4 worker）。重复执行即可更新版本，线上数据库不会被覆盖。

详细说明见 [README.md](./README.md)。

---

*Duoweilai · 多未来 · Plant a future seed. Watch it grow into a world.*
