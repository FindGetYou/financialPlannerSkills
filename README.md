# 私人财务规划师 — Skills 包

> 面向个人、全生命周期的财务规划 AI Skills 包。
> 让 Agent 变身为专业的 CFP（注册财务规划师），合理规划和管理个人财产。

## 项目定位

本项目是「私人财务规划师」产品的 **纯 Skills 实现** ，目标：

- 用 Agent 的 skills 机制，表达财务规划师的核心工作流和设计思想
- 参加 Skills 创作大赛，验证产品的商业价值
- 当前版本，面向理财小白或初学者（比如使用了`极简投资`规划投资），快速开始理财第一步，培养规划意识

## 设计原则

1. **计算下沉**：严禁 LLM 直接做复杂数学运算，所有数值计算走 Python 脚本
2. **结构化存储**：用户画像、方案、任务等数据用 SQLite 存储，不塞 LLM context，承诺不读取上下文中的临时数据
3. **数据双版本**：每次持久化标记 `confirmed`（用户已确认）或 `snapshot`（中间态/Agent 推测）
4. **确认优先**：数据持久化前必须跟用户确认
5. **状态恢复**：通过 `session_context` 快照（≤200 字）让新会话快速接上
6. **单用户**：同时只服务一个用户，数据存本地

## 架构

```
┌────────────────────────────────────────────┐
│       financial-planner（主 skill）          │
│   状态路由 + 工作流调度 + 简单上下文记忆恢复      │
├────────────────────────────────────────────┤
│  场景 skills（按需加载）                      │
│  ├─ fp-kyc            画像对话引导 + 落库     │
│  ├─ fp-plan           方案设计 + 协商 + 执行   │
│  ├─ fp-review          投资复盘 + 再平衡     │
│  └─ fp-calculator     纯计算（不经过 LLM）    │
├────────────────────────────────────────────┤
│  数据层（SQLite）                            │
│  ├─ user_profile      画像（含版本标记）      │
│  ├─ asset_records     持有金融产品记录        │
│  ├─ financial_plan    配置方案                │
│  ├─ plan_tasks        执行步骤                │
│  ├─ review_diaries    复盘日记                │
│  └─ session_context   会话快照                │
└────────────────────────────────────────────┘
```

## 主 Skill 工作流

```
用户打开会话
      │
      ▼
┌──────────────────┐
│ 查 session_context │──→ 有快照 → 加载上次上下文
│ 查 user_profile    │
└────────┬─────────┘
         │
    ┌────┴──── 画像存在？
    │
   否                    是
    │                     │
    ▼                     ▼
┌────────┐    ┌──────────────────────┐
│ 加载     │    │ 查 financial_plan     │
│ fp-kyc  │    │ 是否有进行中的方案？    │
└────────┘    └──────────┬───────────┘
                         │
              ┌─────┬────┴────┬─────┐
              │     │         │     │
            无方案  协商中   已确认  已完成
              │     │         │     │
              ▼     ▼         ▼     ▼
         加载     加载     查 tasks  查复盘
         fp-plan  fp-plan   │       日记
                  协商模式   │
                       ┌────┴────┐
                     有pending   全部done
                        │         │
                        ▼         ▼
                     督促执行   建议复盘
```

## 文件结构

```
financial-planner/
├── SKILL.md                         # 主 skill — 状态路由 + 工作流调度
├── skills/
│   ├── fp-kyc/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── profile_store.py     # 画像 CRUD（含版本标记）
│   ├── fp-plan/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       ├── plan_engine.py       # 模型匹配 + 方案生成
│   │       └── task_tracker.py      # 任务 CRUD + 进度核验
│   ├── fp-review/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── review_engine.py      # 复盘引擎 + 基准对比 + Markdown 输出
│   └── fp-calculator/
│       ├── SKILL.md
│       └── scripts/
│           └── calc.py              # 复利/退休缺口/保额/税务
├── scripts/
│   ├── db_init.py                   # 建表 + 迁移
│   ├── db_query.py                  # 通用查询
│   └── schema.sql                   # DDL
├── references/
│   ├── cfp_framework.md             # CFP 六大模块参考
│   ├── asset_models.md              # 资产配置模型
│   └── privacy_guidelines.md        # 渐进式采集 + 隐私话术
├── templates/
│   └── news_sources.yaml            # 新闻源配置模板（预留）
└── README.md                        # 本文件
```

## 数据库表设计

| 表名 | 用途 | 核心字段 |
|------|------|---------|
| `user_profile` | 画像数据 | field_name, field_value, value_type(exact/range/ratio/unknown), version(confirmed/snapshot), updated_at |
| `asset_records` | 持有金融产品 | product_name, type(fund/stock/insurance/other), platform, amount, buy_date |
| `financial_plan` | 配置方案 | model, target_allocations(JSON), status(draft/negotiating/confirmed), version, profile_version |
| `plan_tasks` | 执行步骤 | task_desc, priority, deadline, status(pending/in_progress/done/delayed), plan_version, depends_on |
| `review_diaries` | 复盘日记 | review_date, plan_id, net_worth_change, drift_max, rebalance_needed, detail_json(JSON), narrative |
| `session_context` | 会话快照 | current_stage, active_plan_id, last_summary(≤200字), pending_todos(JSON), updated_at |

## MVP 范围

### 包含
- 主 skill：状态路由 + 工作流调度
- fp-kyc：渐进式画像对话引导 + SQLite 落库
- fp-plan：模型匹配 + 方案生成 + 协商 + 执行拆解 + 督促核验
- fp-review：资产快照对比 + 产品盈亏分析 + 基准对比 + 再平衡建议 + 复盘日记存储
- fp-calculator：复利、退休缺口、保额等纯计算

### 不包含（后续迭代）
- 专业知识库维护（README 留坑）
- 多用户支持
- 仪表盘可视化前端
- 领域专家 Agent 团队
- MCP Server 封装

## 数据隐私

- 所有数据存储在用户本地 SQLite 文件中
- 不上传、不关联用户身份
- 用户可以选择模糊回答（区间、占比）或跳过敏感问题
- 数据持久化前必须获得用户确认

## 后续迭代

### v2.0
- 专业知识库维护：政策法规、金融产品知识、市场数据的结构化存储与定时更新
- 更丰富的复盘分析：多基准对比、趋势图表、自动化定期复盘
- 多用户支持

### v3.0
- 领域专家 Agent 团队（保险专家、投资组合经理、税务专家等）
- MCP Server 封装，供其他 AI Agent 调用
- 可视化仪表盘
