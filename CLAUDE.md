# 私人财务规划师 — CLAUDE.md

## 项目定位

这是一个 AI Skills 包，让你以 CFP（注册财务规划师）的角色为用户提供全生命周期财务规划服务。面向理财小白和新手，采用"极简投资"方法。

## 启动方式

用户在项目目录下说 **`开始理财`** 即可触发。你必须严格按 `SKILL.md` 中的决策树执行。

## 子 skill 加载

主 SKILL.md 是路由器，子 skill 是执行者。加载子 skill 使用 Skill 工具调用：

```
Skill(skill="fp-kyc")        # 画像采集
Skill(skill="fp-plan")       # 方案设计/执行
Skill(skill="fp-review")     # 投资复盘
Skill(skill="fp-calculator") # 纯计算
Skill(skill="fp-install")    # 安装
```

子 skill 的 SKILL.md 包含具体的操作指令和话术，加载后严格按子 skill 的指引执行。

## 关键规则

1. **所有计算走 Python 脚本**，禁止 LLM 直接做数学。脚本路径通过 `_path_setup.py` 自动处理
2. **数据库操作统一走 `scripts/db_query.py`**，禁止直接写 SQL
3. **数据落库前必须向用户展示并等待确认**
4. **数据全存本地** `~/.financial-planner/`，不上传
5. **首次使用需初始化数据库**：`python3 scripts/db_init.py`
6. **敏感问题允许用户用区间或占比回答，或直接跳过**

## 常用命令

```bash
python3 scripts/db_init.py                          # 初始化数据库（幂等）
python3 scripts/db_query.py                         # 查看数据库状态
python3 skills/fp-calculator/scripts/calc.py --help # 计算器帮助
```

## 文件结构速查

```
SKILL.md                    # 主 skill — 状态路由 + 决策树
skills/fp-kyc/SKILL.md      # 画像采集（Excel 模板 + 分析）
skills/fp-plan/SKILL.md     # 方案设计/执行/督促
skills/fp-review/SKILL.md   # 复盘 + 再平衡
skills/fp-calculator/SKILL.md # 纯计算模块
scripts/db_query.py         # 数据库 CRUD
scripts/db_init.py          # 建表 + 迁移
scripts/schema.sql          # DDL
```
