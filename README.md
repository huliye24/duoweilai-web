# DUOWEILAI · Web

> **多未来 · Web 原型** —— 把「想象 → 世界」的循环变成可交互的软件。

这是 [多未来（DUOWEILAI）](https://github.com/huliye24/duoweilai) 计划的第一个软件原型。

愿景仓库保存的是「想象 / 世界 / 故事 / 文化」的文本档案馆；这个仓库保存的，是把其中第一个循环变成真实可用产品的最小实现：

> **一个人发布一个 Future Seed（未来种子），另一个人进入它、继续它、分叉它、共建它，直到它长成一个 World。**

---

## 核心循环

```
一个人产生想象
        ↓
Publish a Future Seed（发布未来种子）
        ↓
获得永久 URL
        ↓
另一个人打开它 → Explore
        ↓
Continue / Branch / Contribute（继续 / 分叉 / 贡献）
        ↓
新的 People / Place / Story / Rule / Object 出现
        ↓
Future 开始 Growing（生长）
        ↓
吸引新的参与者
        ↺
```

**不需要钱。** 交换的对象是：想象力 → 注意力 → 创造力 → 更多想象力。

---

## 快速开始

Python 3.8+，仅使用标准库，无需安装任何依赖。

```bash
python server.py
```

访问 `http://localhost:8080`。首次运行会自动创建 `duoweilai.db`。

---

## 页面

| 路径 | 说明 |
|------|------|
| `/` | 首页 — 发布 Future Seed |
| `/f/XXXXX` | Future Seed 详情页（永久链接） |
| `/world/XXXXX` | World — Future 累计 ≥5 条贡献后自动升级 |
| `/explore` | 探索 — 浏览所有正在生长的未来 |

---

## 两个角色（不是固定身份）

| 角色 | 定义 |
|------|------|
| **Initiator / 发起者** | 提出第一个 Future Seed 的人 |
| **Participant / 参与者** | 进入一个 Future 并让它继续生长的人 |

它只是人与某个 Future 的关系，不是账户类型。今天我是某个未来的发起者，明天我就是另一个未来的参与者。

---

## 数据结构

- **futures** — 每颗 Future Seed
- **contributions** — People / Places / Stories / Rules / Objects / Branches
- **first_contribution_at** — 记录「第一个非发起者贡献」的时间（核心指标）

---

## Web 0.1 验证的三个事件

1. 有人发布了 Future Seed。
2. 另一个人进入了这个 Future。
3. 另一个人留下了新的东西。← 最关键

---

## 核心产品指标

> **Seed → First Contribution Conversion**

一颗 Future Seed 发布后，有多少获得了来自其他人的第一个贡献。

```
100 Future Seeds published
  42 Seeds received exploration
    17 Seeds received a first contribution
      8 Seeds received multiple contributors
        3 Seeds began forming a World
```

这不是 DAU 竞赛。我们验证的是：**想象能不能吸引另一个人进入，并让他产生新的想象。**

---

## 设计原则

第一代只做一件事：让人能够创造、打开和继续一个 Future。代码极简，仅标准库，先把循环跑通。

---

## 仓库结构

```
duoweilai-web/
├── README.md
├── server.py            # v0.2 现行版（唯一后端，仅标准库）
└── archive/
    ├── v0.2-README.md   # v0.2 原始 README
    └── v0.1-prototypes/ # v0.1 静态 HTML 原型与旧服务
        ├── duoweilai.html ... duoweilai05.html
        └── v0.1-server/
            ├── server.py
            └── README.md
```

---

## 版本

- **v0.1** — 静态 HTML 原型 + 最简后端（仅发布 / 打开 / 浏览）
- **v0.2** — 身份系统（cookie）+ World 页 + 贡献类型（People / Place / Story / Rule / Object / Branch）

---

## 相关仓库

- [huliye24/duoweilai](https://github.com/huliye24/duoweilai) — 多未来愿景与「未来档案馆」（想象 / 世界 / 故事 / 文化）

---

## License

[Apache License 2.0](./LICENSE)
