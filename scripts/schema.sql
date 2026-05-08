-- 私人财务规划师 — 数据库 Schema
-- 数据目录: ~/.financial-planner/data.db

-- 会话快照（单行表，新会话快速恢复上下文）
CREATE TABLE IF NOT EXISTS session_context (
    id              INTEGER PRIMARY KEY CHECK (id = 1),   -- 永远只有一行
    current_stage   TEXT NOT NULL DEFAULT 'new',          -- new / kyc / planning / executing / monitoring
    active_plan_id  INTEGER,
    last_summary    TEXT DEFAULT '',                      -- ≤200 字，上次进展简述
    pending_todos   TEXT DEFAULT '[]',                    -- JSON array，待处理事项
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 用户画像（key-value 结构，每字段独立行）
CREATE TABLE IF NOT EXISTS user_profile (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    field_name      TEXT NOT NULL,                        -- 字段名：age, income, city, risk_tolerance ...
    field_value     TEXT NOT NULL,                        -- 字段值
    value_type      TEXT NOT NULL DEFAULT 'exact',        -- exact / range / ratio / unknown
    version         TEXT NOT NULL DEFAULT 'snapshot',     -- snapshot / confirmed
    category        TEXT NOT NULL DEFAULT 'basic_info',   -- basic_info / assets / cashflow / risk / lifecycle
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 持有金融产品记录
CREATE TABLE IF NOT EXISTS asset_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code    TEXT NOT NULL,                         -- 股票代码 / 基金代码 / 保险单号
    product_name    TEXT NOT NULL,
    type            TEXT NOT NULL,                         -- stock / fund / insurance / other
    platform        TEXT NOT NULL DEFAULT '',              -- 购买平台
    hold_quantity   REAL,                                  -- 持仓数量（股数/份额），保险类为 NULL
    holding_amount  REAL NOT NULL,                         -- 持仓市值（元）
    profit_amount   REAL NOT NULL DEFAULT 0,               -- 持有收益（元）
    record_date     TEXT NOT NULL,                         -- 记录日期 YYYY-MM-DD
    notes           TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 财务配置方案
CREATE TABLE IF NOT EXISTS financial_plan (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    model               TEXT NOT NULL,                        -- four_accounts / core_satellite / lifecycle ...
    target_allocations  TEXT NOT NULL DEFAULT '{}',           -- JSON，各资产目标占比
    status              TEXT NOT NULL DEFAULT 'draft',        -- draft / negotiating / confirmed / archived
    version             INTEGER NOT NULL DEFAULT 1,
    profile_version     TEXT DEFAULT '',                      -- 关联的画像版本，方案所基于的画像快照
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 执行步骤
CREATE TABLE IF NOT EXISTS plan_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL REFERENCES financial_plan(id),
    task_desc       TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 0,               -- 0=最高，越大越低
    deadline        TEXT,                                      -- YYYY-MM-DD
    status          TEXT NOT NULL DEFAULT 'pending',           -- pending / in_progress / done / delayed / cancelled
    depends_on      INTEGER,                                   -- 前置任务 ID
    cron_job_name   TEXT,                                      -- 关联的定时提醒 job 名称
    completed_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 风险嗅探配置
CREATE TABLE IF NOT EXISTS risk_sniff_config (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL REFERENCES financial_plan(id),
    keyword         TEXT NOT NULL,                             -- 嗅探关键词
    source_urls     TEXT NOT NULL DEFAULT '[]',                -- JSON，新闻源 URL 列表
    frequency       TEXT NOT NULL DEFAULT 'daily',             -- daily / weekly / monthly
    priority        TEXT NOT NULL DEFAULT 'medium',            -- high / medium / low
    active          INTEGER NOT NULL DEFAULT 1,                -- 0=停用 / 1=启用
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_profile_category ON user_profile(category);
CREATE INDEX IF NOT EXISTS idx_profile_version ON user_profile(version);
CREATE INDEX IF NOT EXISTS idx_assets_type ON asset_records(type);
CREATE INDEX IF NOT EXISTS idx_assets_record_date ON asset_records(record_date);
CREATE INDEX IF NOT EXISTS idx_plan_status ON financial_plan(status);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON plan_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_plan_id ON plan_tasks(plan_id);
CREATE INDEX IF NOT EXISTS idx_sniff_plan_id ON risk_sniff_config(plan_id);
