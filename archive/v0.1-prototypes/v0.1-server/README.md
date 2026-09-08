# Duoweilai — First Principles Prototype

一个极度克制的「未来网络」原型。

## 核心循环

打开网页 → 发布 Future Seed → 得到永久链接 → 别人进入 → 继续探索

## 运行方式

需要 Python 3.8+（仅使用标准库，无需安装任何依赖）

```bash
python3 server.py
```

然后打开浏览器访问：

```
http://localhost:8080
```

## 主要页面

- `/` — 首页，发布 Future Seed
- `/f/XXXXX` — Future Seed 详情页（永久链接）
- `/explore` — 浏览所有正在生长的未来

## 数据结构

- `futures` 表：每一颗 Future Seed
- `contributions` 表：People / Places / Stories / Rules / Objects / Branches

数据保存在同目录下的 `duoweilai.db`（SQLite）。

## 设计原则

第一代只做一件事：让人能够创造、打开和继续一个 Future。
