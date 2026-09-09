# Security Policy

## 支持的版本

| 版本 | 支持状态 |
|------|---------|
| 最新 (`main` 分支) | ✅ 积极维护 |
| 上一稳定版 | ⚠️ 关键安全更新 |
| 其它 | ❌ 不再维护 |

## 报告漏洞

**请勿在公开 Issue 里披露安全漏洞。**

私密报告方式（按推荐顺序）：

1. **GitHub Security Advisories**（推荐）：[新建 advisory](https://github.com/huliye24/duoweilai-web/security/advisories/new)
2. **邮件**：见仓库首页的 contact 链接

请提供：

- 漏洞描述与影响范围
- 复现步骤 / PoC
- 受影响版本
- 是否已自行修复（可选）

我们承诺：

- **24 小时内**确认收到
- **72 小时内**初步评估严重等级
- **修复时间**：critical 7 天 / high 30 天 / medium 90 天 / low 随下次发布

## 安全实践

本项目遵循：

- **CSRF**：双提交 cookie 模式（见 `app/auth.py`）
- **密码哈希**：PBKDF2-SHA256（见 `app/auth.py`）
- **会话**：HttpOnly + Secure + SameSite=Lax cookie，30 天有效
- **速率限制**：基于 IP + token bucket（见 `app/security.py`）
- **CSP / X-Frame / X-Content-Type-Options** 响应头（见 `app/security.py`）
- **依赖审计**：`pip-audit` + Dependabot 自动检测（见 CI workflow）

## 致谢

报告者可在修复发布后选择署名致谢（默认不署名）。
