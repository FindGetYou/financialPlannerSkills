---
name: fp-install
description: 安装私人财务规划师——复制 skills 到 AI 平台目录，初始化数据和公共组件
---

# 安装财务规划师（fp-install）

## 你在做什么

你是用户的 AI 助手。用户给了你一个"私人财务规划师"的 skills 包，需要你帮忙安装。本文件告诉你完整流程，但具体路径由你根据自己的运行环境自行判断。

---

## 第一步：让用户选择使用方式

先用以下话术让用户选择：

> "这个项目有两种使用方式——"
>
> **🅰️ 项目目录内使用（零安装）**
> 直接在项目目录下和我对话即可，不用安装任何东西。现在就可以说「开始理财」。
>
> **🅱️ 安装到 AI 平台（推荐）**
> 安装后在任何目录都能触发，我会把 skills 复制到系统目录。适用于 Hermes Agent / Claude Code / Codex / Open Claw 等主流 AI 平台。
>
> 你选哪个？

- 用户选 A → "好的，现在就可以开始。试试说「开始理财」？"
- 用户选 B → 继续第二步。

---

## 第二步：确认 skills 目录

**你需要自己判断你的 skills 目录在哪。** 常见位置（仅参考，以你的实际环境为准）：

| 平台 | skills 目录参考 |
|------|----------------|
| Hermes Agent | `~/.hermes/skills/` |
| Claude Code | `~/.claude/skills/` 或项目 `CLAUDE.md` 所在目录 |
| Codex | `~/.codex/skills/` 或项目配置中指定的目录 |
| Open Claw / 其他 | 取决于平台的 skill 加载机制 |

**判断方法：**
- 如果你能读取和写入文件，尝试常见的 `~/.hermes/skills/`、`~/.claude/skills/` 等
- 如果这些都不存在，选一个你知道的路径
- 如果不确定，问用户："你的 AI 平台 skills 通常放在哪个目录？"

确定后，告知用户：
> "检测到你的 skills 目录是 `——`，我把财务规划师的 skills 安装到这里。确认吗？"

---

## 第三步：复制文件

### 需要复制的文件

从项目根目录（`financialPlannerSkills/`）复制到两部分：

**A. Skills（复制到你的 skills 目录）：**

```
financial-planner/SKILL.md          → <skills_dir>/financial-planner/SKILL.md
skills/fp-kyc/SKILL.md              → <skills_dir>/fp-kyc/SKILL.md
skills/fp-kyc/scripts/              → <skills_dir>/fp-kyc/scripts/
skills/fp-plan/SKILL.md             → <skills_dir>/fp-plan/SKILL.md
skills/fp-plan/scripts/             → <skills_dir>/fp-plan/scripts/
skills/fp-calculator/SKILL.md       → <skills_dir>/fp-calculator/SKILL.md
skills/fp-calculator/scripts/       → <skills_dir>/fp-calculator/scripts/
skills/fp-risk-sniff/SKILL.md       → <skills_dir>/fp-risk-sniff/SKILL.md
skills/fp-risk-sniff/scripts/       → <skills_dir>/fp-risk-sniff/scripts/
skills/fp-install/SKILL.md          → <skills_dir>/fp-install/SKILL.md
```

**B. 公共组件（复制到 `~/.financial-planner/`）：**

```
scripts/schema.sql                  → ~/.financial-planner/scripts/schema.sql
scripts/db_init.py                  → ~/.financial-planner/scripts/db_init.py
scripts/db_query.py                 → ~/.financial-planner/scripts/db_query.py
references/cfp_framework.md         → ~/.financial-planner/references/cfp_framework.md
references/asset_models.md          → ~/.financial-planner/references/asset_models.md
references/privacy_guidelines.md    → ~/.financial-planner/references/privacy_guidelines.md
templates/news_sources.yaml         → ~/.financial-planner/templates/news_sources.yaml
```

### ⚠️ 路径更新

子 skill 的 Python 脚本通过 `sys.path` 自动查找 `~/.financial-planner/scripts/` 和项目 `scripts/`，安装后两种路径都生效。**无需手动修改 import 语句。**

---

## 第四步：初始化数据库

```bash
python3 ~/.financial-planner/scripts/db_init.py
```

如果成功，输出：
> [OK] 数据库初始化完成: ~/.financial-planner/data.db

如果报错（如缺少 sqlite3 模块），按以下顺序排查：
1. python3 是否可用
2. sqlite3 是否内置（Python 3 默认包含）

---

## 第五步：验证安装

检查以下内容：

```
□ <skills_dir>/financial-planner/SKILL.md  存在
□ <skills_dir>/fp-kyc/SKILL.md              存在
□ <skills_dir>/fp-plan/SKILL.md             存在
□ <skills_dir>/fp-calculator/SKILL.md       存在
□ <skills_dir>/fp-risk-sniff/SKILL.md       存在
□ ~/.financial-planner/data.db              存在
□ ~/.financial-planner/scripts/db_query.py  存在
```

全部通过后：

> ✅ **安装完成！**
>
> 现在可以在任何目录说「开始理财」启动你的私人财务规划师。
>
> 如果需要彻底卸载，删除两个目录即可：
> - `<skills_dir>/financial-planner/` + `fp-kyc/` `fp-plan/` `fp-calculator/` `fp-risk-sniff/` `fp-install/`
> - `~/.financial-planner/`（含数据库）

---

## 注意事项

- **不要修改任何 skill 文件的内容**，除非你判断有必要（比如平台路径差异导致脚本无法运行）
- **不要修改 `~/.financial-planner/` 下的文件结构**，所有子 skill 脚本依赖该路径
- 如果用户之前安装过旧版本，建议先备份或删除旧文件再重新复制
- 安装完成后，用户说「开始理财」等触发词即可自动加载主 skill
