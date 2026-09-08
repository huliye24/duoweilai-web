# Team Guide · 团队内部使用指南

> English version of the app, designed for overseas market.
> 中文说明，帮你快速上手本地运行和内部测试。

---

## 如何启动（本地运行）

### 1. 安装 Python

确保安装了 Python 3.8+：

```powershell
python --version
```

如果没有，[官网下载](https://www.python.org/downloads/)安装，安装时勾选 **Add Python to PATH**。

### 2. 拉取代码

```bash
git clone https://github.com/huliye24/duoweilai-web.git
cd duoweilai-web
```

### 3. 启动服务

```bash
python server.py
```

打开浏览器访问 **http://localhost:8080**

> 首次运行会自动创建 `duoweilai.db` 数据库文件。

### 4. 让团队成员也能访问

如果团队成员在同一局域网内，可以让他们也访问你的服务：

**Windows 查看本机 IP：**
```powershell
ipconfig
```
找到类似 `192.168.x.x` 的地址。

**启动时指定监听所有网卡：**
```bash
set DUOWEILAI_BIND=0.0.0.0
python server.py
```

然后团队成员通过 `http://你的IP:8080` 访问。

**macOS / Linux：**
```bash
DUOWEILAI_BIND=0.0.0.0 python server.py
```

### 5. 自定义端口

默认端口是 8080，可以改成其他端口：

```bash
set DUOWEILAI_PORT=3000
python server.py
```

---

## 如何注册账号

**当前版本不需要注册。**

每次打开网站，浏览器会自动获得一个 session cookie，你会被标识为 `explorer`。所有团队成员共享这个身份，所以你可以直接发布 future、贡献内容、评论，不用做任何账号操作。

如果你看到任何 "Sign in" / "Sign up" 按钮，那是过期内容，忽略即可——所有功能都可以无登录使用。

> 后续要恢复账号系统时，在 `server.py` 里把 `current_user()` 改回原来的 cookie 验证即可。

---

## 功能一览

| 功能 | 说明 |
|------|------|
| **Publish a Future** | 首页输入框，写下一个"如果..."，发布后获得永久链接 |
| **Explore** | /explore 页面浏览所有已发布的未来 |
| **Contribute** | 在种子详情页，可以添加 People / Place / Story / Rule / Object / Branch |
| **Comment** | 对每个未来发表评论 |
| **World** | 当一个种子获得 5 个以上贡献，会自动升级为 World |
| **Notifications** | 有人评论/贡献你的种子时会收到通知 |
| **Profile** | /person/你的用户名，查看你发起和贡献的内容 |

---

## 设计语言

本次重设计还原了 v0.1 原型的 UI 风格：

- **深色极简**：背景 #0a0a0b，文字 #f4f4f5
- **Inter 字体**：干净、现代
- **英文优先**：面向海外市场
- **药丸按钮、虚线 CTA 框**：标志性的视觉语言

---

## 运行测试

确保服务正在运行（另开一个终端），然后：

```bash
python tests/e2e_test.py
```

测试覆盖：注册 → 登录 → 发布 → 贡献 → 评论 → 通知 → UI 语言检查。

---

## 数据库

数据存储在 `duoweilai.db`（SQLite），每次启动自动初始化。

**重置数据库（清空所有数据）：**

```powershell
# 先停止服务
Remove-Item duoweilai.db -Force
# 重启服务后会自动创建新数据库
python server.py
```

**数据库位置：** `E:\Duoweilai.com\duoweilai.db`（当前项目根目录）

---

## 目录结构

```
E:\Duoweilai.com\
├── server.py              # 服务器主程序
├── duoweilai.db           # SQLite 数据库（不要提交到 git）
├── tests/
│   ├── smoke_test.py      # 快速冒烟测试
│   └── e2e_test.py        # 完整端到端测试
├── archive/
│   └── v0.1-prototypes/  # v0.1 的 5 个原始 UI 设计（参考用）
├── deploy/                # 生产部署配置（Linux + nginx + systemd）
├── README.md              # English 说明文档
├── TEAM_GUIDE.md          # 本文件（中文团队指南）
└── .gitignore
```

---

## 常见问题

**Q: 服务启动报错 "Port already in use"**
> 8080 端口被占用。先 `Get-Process python | Stop-Process -Force`，或改用其他端口 `DUOWEILAI_PORT=3000 python server.py`。

**Q: 注册时提示 "Username already taken"**
> 该用户名已被占用。换一个用户名即可。

**Q: 贡献/评论时提示 "Sign in required"**
> 需要先登录。未登录用户不能发布内容。

**Q: 想清空所有数据重新开始**
> 停止服务，删除 `duoweilai.db`，重新启动 `python server.py`。

---

## 下一步（生产部署）

内部测试稳定后，可使用 `deploy/setup.sh` 在 Linux 服务器上一键部署（含 nginx 反向代理 + Let's Encrypt HTTPS 证书）。

详细说明见 [README.md](./README.md)。

---

*Duoweilai · 多未来 · Plant a future seed. Watch it grow into a world.*
