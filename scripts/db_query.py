"""
数据库通用查询与写入

所有其他脚本和 Agent 通过此模块操作数据库，
不直接写 SQL。

用法:
    from db_query import (
        get_session_context, update_session_context,
        get_profile_summary, upsert_profile_field, batch_confirm_fields,
        get_active_plan, create_plan, update_plan_status,
        get_pending_tasks, create_task, update_task_status,
        get_sniff_configs, upsert_sniff_config,
        add_asset_record, get_asset_records,
    )
"""

import json
import os
import sqlite3
from datetime import datetime

FP_HOME = os.path.expanduser("~/.financial-planner")
DB_PATH = os.path.join(FP_HOME, "data.db")


def _connect():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════════════════
# 会话上下文
# ═══════════════════════════════════════════════════════════════

def get_session_context():
    """
    返回会话快照 dict，若无记录返回 None。

    返回字段:
        current_stage: new / kyc / planning / executing / monitoring
        active_plan_id: int | None
        last_summary: str (≤200字)
        pending_todos: list[str]
    """
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM session_context WHERE id = 1").fetchone()
        if row is None:
            return None
        return {
            "current_stage": row["current_stage"],
            "active_plan_id": row["active_plan_id"],
            "last_summary": row["last_summary"],
            "pending_todos": json.loads(row["pending_todos"]),
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def update_session_context(stage=None, plan_id=None, summary=None, todos=None):
    """
    更新会话快照。只传需要变更的字段，其余保持不变。

    Args:
        stage: 当前阶段
        plan_id: 活跃方案 ID
        summary: 上次进展简述 (≤200字)
        todos: 待处理事项列表
    """
    conn = _connect()
    try:
        # 确保单行存在
        conn.execute(
            "INSERT OR IGNORE INTO session_context (id) VALUES (1)"
        )

        sets = []
        params = []
        if stage is not None:
            sets.append("current_stage = ?")
            params.append(stage)
        if plan_id is not None:
            sets.append("active_plan_id = ?")
            params.append(plan_id)
        if summary is not None:
            # 截断到 200 字
            summary = summary[:200]
            sets.append("last_summary = ?")
            params.append(summary)
        if todos is not None:
            sets.append("pending_todos = ?")
            params.append(json.dumps(todos, ensure_ascii=False))

        if sets:
            sets.append("updated_at = ?")
            params.append(_now())
            sql = f"UPDATE session_context SET {', '.join(sets)} WHERE id = 1"
            conn.execute(sql, params)

        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 用户画像
# ═══════════════════════════════════════════════════════════════

def get_profile_summary():
    """
    返回画像概要，供 Agent 判断当前 KYC 进度。

    返回:
        exists: bool 是否有画像数据
        total_fields: int
        confirmed_fields: int
        snapshot_fields: int
        categories: dict {category: {total, confirmed}}
        fields: list[dict] 所有字段
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM user_profile ORDER BY category, field_name"
        ).fetchall()

        if not rows:
            return {"exists": False, "total_fields": 0, "confirmed_fields": 0,
                    "snapshot_fields": 0, "categories": {}, "fields": []}

        fields = [dict(r) for r in rows]
        confirmed = sum(1 for f in fields if f["version"] == "confirmed")
        snapshot = sum(1 for f in fields if f["version"] == "snapshot")

        # 按 category 聚合
        categories = {}
        for f in fields:
            cat = f["category"]
            if cat not in categories:
                categories[cat] = {"total": 0, "confirmed": 0}
            categories[cat]["total"] += 1
            if f["version"] == "confirmed":
                categories[cat]["confirmed"] += 1

        return {
            "exists": True,
            "total_fields": len(fields),
            "confirmed_fields": confirmed,
            "snapshot_fields": snapshot,
            "categories": categories,
            "fields": fields,
        }
    finally:
        conn.close()


def upsert_profile_field(field_name, field_value, value_type="exact",
                         category="basic_info", version="snapshot"):
    """
    写入或更新一个画像字段。同一 field_name 覆盖旧值。

    Args:
        field_name: 字段名
        field_value: 字段值（字符串）
        value_type: exact / range / ratio / unknown
        category: basic_info / assets / cashflow / risk / lifecycle
        version: snapshot（默认）/ confirmed
    """
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT id FROM user_profile WHERE field_name = ?", (field_name,)
        ).fetchone()

        now = _now()
        if existing:
            conn.execute(
                """UPDATE user_profile 
                   SET field_value=?, value_type=?, version=?, category=?, updated_at=?
                   WHERE field_name=?""",
                (field_value, value_type, version, category, now, field_name)
            )
        else:
            conn.execute(
                """INSERT INTO user_profile (field_name, field_value, value_type, version, category, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (field_name, field_value, value_type, version, category, now)
            )
        conn.commit()
    finally:
        conn.close()


def batch_confirm_fields(field_names):
    """
    将指定字段批量标记为 confirmed。
    Agent 与用户确认画像后调用。
    """
    if not field_names:
        return

    conn = _connect()
    try:
        placeholders = ",".join(["?"] * len(field_names))
        sql = f"UPDATE user_profile SET version='confirmed', updated_at=? WHERE field_name IN ({placeholders})"
        conn.execute(sql, [_now()] + field_names)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 资产记录
# ═══════════════════════════════════════════════════════════════

def add_asset_record(product_code, product_name, asset_type, holding_amount,
                     platform="", hold_quantity=None, profit_amount=0,
                     record_date=None, notes=""):
    """
    新增一条资产记录。

    Args:
        product_code: 股票代码 / 基金代码 / 保险单号
        product_name: 产品名称
        asset_type: stock / fund / insurance / other
        holding_amount: 持仓市值（元）
        platform: 购买平台
        hold_quantity: 持仓数量（股数/份额），保险类为 None
        profit_amount: 持有收益（元）
        record_date: 记录日期，默认今天
        notes: 备注
    """
    if record_date is None:
        record_date = datetime.now().strftime("%Y-%m-%d")

    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO asset_records 
               (product_code, product_name, type, platform, hold_quantity,
                holding_amount, profit_amount, record_date, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (product_code, product_name, asset_type, platform, hold_quantity,
             holding_amount, profit_amount, record_date, notes)
        )
        conn.commit()
    finally:
        conn.close()


def get_asset_records(asset_type=None, product_code=None):
    """
    查询资产记录，可按类型或代码过滤。

    返回: list[dict]
    """
    conn = _connect()
    try:
        sql = "SELECT * FROM asset_records WHERE 1=1"
        params = []
        if asset_type:
            sql += " AND type = ?"
            params.append(asset_type)
        if product_code:
            sql += " AND product_code = ?"
            params.append(product_code)
        sql += " ORDER BY record_date DESC"

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 财务方案
# ═══════════════════════════════════════════════════════════════

def get_active_plan():
    """
    获取当前活跃方案（status != archived 的最新方案）。
    返回: dict | None
    """
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT * FROM financial_plan 
               WHERE status != 'archived' 
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["target_allocations"] = json.loads(d["target_allocations"])
        return d
    finally:
        conn.close()


def create_plan(model, allocations, status="draft", profile_version=""):
    """
    创建新方案，返回 plan_id。
    如果已有活跃方案，自动将其归档。
    """
    conn = _connect()
    try:
        # 归档旧方案
        conn.execute(
            """UPDATE financial_plan SET status='archived', updated_at=?
               WHERE status != 'archived'""",
            (_now(),)
        )

        cursor = conn.execute(
            """INSERT INTO financial_plan (model, target_allocations, status, profile_version)
               VALUES (?, ?, ?, ?)""",
            (model, json.dumps(allocations, ensure_ascii=False), status, profile_version)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_plan_status(plan_id, status):
    """更新方案状态"""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE financial_plan SET status=?, updated_at=? WHERE id=?",
            (status, _now(), plan_id)
        )
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 执行任务
# ═══════════════════════════════════════════════════════════════

def get_pending_tasks(plan_id=None):
    """
    获取待执行任务。

    返回: list[dict]，按 priority 升序
    """
    conn = _connect()
    try:
        sql = "SELECT * FROM plan_tasks WHERE status IN ('pending', 'in_progress', 'delayed')"
        params = []
        if plan_id is not None:
            sql += " AND plan_id = ?"
            params.append(plan_id)
        sql += " ORDER BY priority ASC, deadline ASC"

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_task(plan_id, task_desc, priority=0, deadline=None, depends_on=None):
    """
    创建执行步骤，返回 task_id。
    """
    conn = _connect()
    try:
        cursor = conn.execute(
            """INSERT INTO plan_tasks (plan_id, task_desc, priority, deadline, depends_on)
               VALUES (?, ?, ?, ?, ?)""",
            (plan_id, task_desc, priority, deadline, depends_on)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_task_status(task_id, status, cron_job_name=None):
    """
    更新任务状态。可选关联定时任务名。

    done 状态会自动记录 completed_at。
    """
    conn = _connect()
    try:
        sets = ["status = ?"]
        params = [status]

        if status == "done":
            sets.append("completed_at = ?")
            params.append(_now())

        if cron_job_name is not None:
            sets.append("cron_job_name = ?")
            params.append(cron_job_name)

        params.append(task_id)
        sql = f"UPDATE plan_tasks SET {', '.join(sets)} WHERE id = ?"
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 风险嗅探
# ═══════════════════════════════════════════════════════════════

def get_sniff_configs(plan_id=None, active_only=True):
    """
    获取风险嗅探配置。

    返回: list[dict]
    """
    conn = _connect()
    try:
        sql = "SELECT * FROM risk_sniff_config WHERE 1=1"
        params = []
        if plan_id is not None:
            sql += " AND plan_id = ?"
            params.append(plan_id)
        if active_only:
            sql += " AND active = 1"
        sql += " ORDER BY priority DESC"

        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["source_urls"] = json.loads(d["source_urls"])
            result.append(d)
        return result
    finally:
        conn.close()


def upsert_sniff_config(plan_id, keyword, source_urls, frequency="daily", priority="medium"):
    """
    写入或更新嗅探配置。同一 plan_id + keyword 去重。
    """
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT id FROM risk_sniff_config WHERE plan_id = ? AND keyword = ?",
            (plan_id, keyword)
        ).fetchone()

        now = _now()
        urls_json = json.dumps(source_urls, ensure_ascii=False)

        if existing:
            conn.execute(
                """UPDATE risk_sniff_config 
                   SET source_urls=?, frequency=?, priority=?, active=1, updated_at=?
                   WHERE plan_id=? AND keyword=?""",
                (urls_json, frequency, priority, now, plan_id, keyword)
            )
        else:
            conn.execute(
                """INSERT INTO risk_sniff_config 
                   (plan_id, keyword, source_urls, frequency, priority)
                   VALUES (?, ?, ?, ?, ?)""",
                (plan_id, keyword, urls_json, frequency, priority)
            )
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 测试入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 快速自检
    print("=== Session Context ===")
    print(get_session_context())

    print("\n=== Profile Summary ===")
    print(get_profile_summary())

    print("\n=== Active Plan ===")
    print(get_active_plan())

    print("\n=== Pending Tasks ===")
    print(get_pending_tasks())

    print("\n=== Asset Records ===")
    print(get_asset_records())

    print("\n=== Sniff Configs ===")
    print(get_sniff_configs())
