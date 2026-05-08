"""
任务追踪器：方案执行步骤的拆解、进度核验和统计。

函数：
  generate_tasks(plan, profile) → 将方案拆解为可执行步骤列表
  verify_completion(task, asset_records) → 核验任务是否真的完成了
  get_progress(plan_id) → 统计方案执行进度

依赖：db_query.py
"""

import sys
import os

_script_dir = os.path.dirname(os.path.abspath(__file__))
_user_scripts = os.path.expanduser("~/.financial-planner/scripts")
_project_scripts = os.path.join(_script_dir, "..", "..", "..", "scripts")
for _p in [_project_scripts, _user_scripts]:
    _p = os.path.abspath(_p)
    if _p not in sys.path and os.path.isdir(_p):
        sys.path.insert(0, _p)

import db_query


# ═══════════════════════════════════════════════════════════════
# 任务生成
# ═══════════════════════════════════════════════════════════════

def generate_tasks(plan: dict, profile: dict):
    """
    将方案拆解为可执行步骤列表。

    返回的每个任务为 dict：
      {
        "task_desc": 任务描述,
        "priority": 0=最高 / 1=高 / 2=中 / 3=低,
        "deadline": 建议截止日期（YYYY-MM-DD）或 None,
        "depends_on": 前置任务索引（列表中的位置，从 0 开始）或 None,
        "category": "setup" | "regular" | "review",
      }

    Args:
        plan: generate_plan() 返回的方案 dict
        profile: 用户画像 dict

    返回: list[dict]
    """
    model = plan.get("model", "")

    if model == "four_account":
        return _tasks_four_account(plan, profile)
    elif model == "core_satellite":
        return _tasks_core_satellite(plan, profile)
    elif model == "goal_oriented":
        return _tasks_goal_oriented(plan, profile)
    else:
        return []


def _tasks_four_account(plan, profile):
    """四账户模型任务拆解"""
    from datetime import datetime, timedelta
    today = datetime.now()

    alloc = plan.get("allocations", {})
    emergency_monthly = alloc.get("emergency", {}).get("monthly", 2000)
    emergency_target = emergency_monthly * 6  # 6 个月生活费

    tasks = [
        {
            "task_desc": f"开立应急账户并存入 ¥{emergency_target:,.0f}（可分批完成）——放货币基金或高流动性理财",
            "priority": 0,
            "deadline": (today + timedelta(days=90)).strftime("%Y-%m-%d"),
            "depends_on": None,
            "category": "setup",
        },
        {
            "task_desc": f"配置基础保障：重疾险（建议保额 ¥{_estimate_coverage(profile):,.0f}）+ 百万医疗险 + 意外险",
            "priority": 1,
            "deadline": (today + timedelta(days=30)).strftime("%Y-%m-%d"),
            "depends_on": None,
            "category": "setup",
        },
        {
            "task_desc": f"建立月度定投计划：指数基金 ¥{alloc.get('growth', {}).get('monthly', 5000):,.0f}/月 + 债券基金 ¥{alloc.get('stable', {}).get('monthly', 8000):,.0f}/月",
            "priority": 2,
            "deadline": None,  # 持续性任务
            "depends_on": 0,  # 依赖应急账户开立
            "category": "regular",
        },
        {
            "task_desc": "每季度检查四账户比例，偏离超过 5% 时执行再平衡",
            "priority": 3,
            "deadline": None,  # 定期任务
            "depends_on": 2,
            "category": "review",
        },
    ]

    return tasks


def _tasks_core_satellite(plan, profile):
    """核心-卫星模型任务拆解"""
    from datetime import datetime, timedelta
    today = datetime.now()

    alloc = plan.get("allocations", {})
    core_amount = alloc.get("core", {}).get("amount", 0)
    sat_amount = alloc.get("satellite", {}).get("amount", 0)
    core_desc = alloc.get("core", {}).get("description", "核心仓")
    sat_desc = alloc.get("satellite", {}).get("description", "卫星仓")

    tasks = [
        {
            "task_desc": f"分批建仓核心仓 ¥{core_amount:,.0f}：{core_desc}。建议分 3-4 批入场，降低择时风险",
            "priority": 1,
            "deadline": (today + timedelta(days=60)).strftime("%Y-%m-%d"),
            "depends_on": None,
            "category": "setup",
        },
        {
            "task_desc": f"分批建仓卫星仓 ¥{sat_amount:,.0f}：{sat_desc}。在核心仓建仓完成后开始",
            "priority": 2,
            "deadline": (today + timedelta(days=90)).strftime("%Y-%m-%d"),
            "depends_on": 0,
            "category": "setup",
        },
        {
            "task_desc": "制定再平衡规则：每季度检查，核心/卫星偏离超 5% 时执行再平衡",
            "priority": 3,
            "deadline": None,
            "depends_on": 1,
            "category": "review",
        },
    ]

    return tasks


def _tasks_goal_oriented(plan, profile):
    """目标导向模型任务拆解"""
    from datetime import datetime, timedelta
    today = datetime.now()

    sub = plan.get("sub_accounts", [{}])[0]
    monthly = sub.get("monthly_contribution", 5000)
    goal_type = plan.get("goal", {}).get("type", "目标")
    years = plan.get("goal", {}).get("timeline_years", 5)

    tasks = [
        {
            "task_desc": f"开设「{goal_type}」专属子账户，启动每月定投 ¥{monthly:,.0f}",
            "priority": 1,
            "deadline": (today + timedelta(days=14)).strftime("%Y-%m-%d"),
            "depends_on": None,
            "category": "setup",
        },
        {
            "task_desc": f"配置 {goal_type} 子账户投资组合（见方案详情），首次建仓",
            "priority": 1,
            "deadline": (today + timedelta(days=30)).strftime("%Y-%m-%d"),
            "depends_on": 0,
            "category": "setup",
        },
        {
            "task_desc": f"坚持每月定投 ¥{monthly:,.0f}，保持自律",
            "priority": 2,
            "deadline": None,
            "depends_on": 1,
            "category": "regular",
        },
        {
            "task_desc": f"每年底复盘目标进度，根据实际情况（收入变化、市场情况）调整月存金额和配置",
            "priority": 3,
            "deadline": None,
            "depends_on": 2,
            "category": "review",
        },
        {
            "task_desc": f"距目标剩余 2 年时（约 {years - 2} 年后），逐步降低子账户权益比例，转向低风险配置",
            "priority": 3,
            "deadline": None,
            "depends_on": 2,
            "category": "review",
        },
    ]

    return tasks


def _estimate_coverage(profile):
    """从画像估算建议保额"""
    income_str = profile.get("income", "")
    income = 0
    try:
        income = float(income_str.replace("万", "").split("-")[0]) * 10000
    except (ValueError, IndexError, AttributeError):
        income = 200000
    return income * 5  # 年收入 5 倍


# ═══════════════════════════════════════════════════════════════
# 任务写入
# ═══════════════════════════════════════════════════════════════

def save_tasks(plan_id: int, tasks: list):
    """
    将任务列表写入数据库。

    Args:
        plan_id: 方案 ID
        tasks: generate_tasks() 返回的任务列表

    返回: list[int] 创建的 task_id 列表
    """
    task_ids = []
    for i, task in enumerate(tasks):
        # 解析 depends_on：列表索引 → task_id
        dep_idx = task.get("depends_on")
        dep_id = task_ids[dep_idx] if dep_idx is not None and dep_idx < len(task_ids) else None

        tid = db_query.create_task(
            plan_id=plan_id,
            task_desc=f"[{task.get('category', 'setup')}] {task['task_desc']}",
            priority=task.get("priority", 2),
            deadline=task.get("deadline"),
            depends_on=dep_id,
        )
        task_ids.append(tid)

    return task_ids


# ═══════════════════════════════════════════════════════════════
# 任务核验
# ═══════════════════════════════════════════════════════════════

def verify_completion(task: dict, asset_records: list = None):
    """
    核验任务是否真的完成了（通过检查资产记录或其他证据）。

    Args:
        task: 任务 dict（从 db_query.get_pending_tasks 获取）
        asset_records: 用户的资产记录列表（可选，从 db_query.get_asset_records 获取）

    返回:
        {
            "verified": True / False / "uncertain",
            "evidence": "核验依据说明",
            "suggestion": "建议下一步操作",
        }
    """
    desc = task.get("task_desc", "").lower()

    # 应急账户开立 - 检查是否有活期/货币基金类资产
    if "应急" in desc or "活期" in desc or "货币基金" in desc:
        if asset_records:
            liquid = [a for a in asset_records if a.get("type") in ("fund", "other")]
            if liquid:
                return {
                    "verified": True,
                    "evidence": f"已有 {len(liquid)} 条基金/其他类资产记录，应急账户可能已建立",
                    "suggestion": "如果已开立应急账户，可以标记此任务为完成",
                }
            else:
                return {
                    "verified": "uncertain",
                    "evidence": "资产记录中未找到流动性资产",
                    "suggestion": "建议确认应急账户是否已开立，或补充资产记录",
                }
        return {
            "verified": "uncertain",
            "evidence": "暂无资产记录可供核验",
            "suggestion": "如果已完成应急账户开立，可以直接标记完成。也可以先录入资产记录",
        }

    # 保险配置 - 检查是否有保险类资产
    if "保险" in desc or "保障" in desc:
        if asset_records:
            insurance = [a for a in asset_records if a.get("type") == "insurance"]
            if insurance:
                return {
                    "verified": True,
                    "evidence": f"已有 {len(insurance)} 条保险记录",
                    "suggestion": "确认保险配置是否齐全，可以标记为完成",
                }
            else:
                return {
                    "verified": "uncertain",
                    "evidence": "资产记录中未找到保险类记录",
                    "suggestion": "如果已购买保险，建议录入保单信息；否则建议尽快配置",
                }
        return {
            "verified": "uncertain",
            "evidence": "暂无资产记录",
            "suggestion": "已配置保险的话可以标记完成并录入保单信息",
        }

    # 定投/建仓 - 检查是否有对应的基金/股票记录
    if "定投" in desc or "建仓" in desc or "指数" in desc or "基金" in desc or "股票" in desc:
        if asset_records:
            funds = [a for a in asset_records if a.get("type") in ("fund", "stock")]
            if funds:
                return {
                    "verified": True,
                    "evidence": f"已有 {len(funds)} 条基金/股票记录",
                    "suggestion": "如果已按方案配置，可以标记完成",
                }
            else:
                return {
                    "verified": "uncertain",
                    "evidence": "资产记录中未找到基金/股票持仓",
                    "suggestion": "已建仓的话建议录入持仓记录",
                }
        return {
            "verified": "uncertain",
            "evidence": "暂无资产记录",
            "suggestion": "首月定投完成后录入持仓记录即可核验",
        }

    # 日常/定期任务 - 通常标记为完成即核验
    return {
        "verified": "uncertain",
        "evidence": "此任务的完成情况主要依赖用户确认",
        "suggestion": "可以和用户确认一下完成情况",
    }


# ═══════════════════════════════════════════════════════════════
# 进度统计
# ═══════════════════════════════════════════════════════════════

def get_progress(plan_id: int = None):
    """
    统计方案执行进度。

    返回:
        {
            "total": 总任务数,
            "done": 已完成,
            "in_progress": 进行中,
            "pending": 待开始,
            "delayed": 已延期,
            "completion_rate": 完成率 (0-1),
            "next_task": 下一个优先任务（dict 或 None）,
            "summary": 进度摘要,
        }
    """
    all_tasks = db_query.get_pending_tasks(plan_id=plan_id)

    # 补充：也查询已完成的
    if plan_id is not None:
        conn = db_query._connect()
        try:
            done_rows = conn.execute(
                "SELECT * FROM plan_tasks WHERE plan_id = ? AND status = 'done'", (plan_id,)
            ).fetchall()
            done_tasks = [dict(r) for r in done_rows]
        finally:
            conn.close()
    else:
        done_tasks = []

    total = len(all_tasks) + len(done_tasks)
    done = len(done_tasks)
    in_progress = sum(1 for t in all_tasks if t["status"] == "in_progress")
    pending = sum(1 for t in all_tasks if t["status"] == "pending")
    delayed = sum(1 for t in all_tasks if t["status"] == "delayed")

    rate = done / total if total > 0 else 0

    # 下一个优先任务
    next_task = None
    if all_tasks:
        sorted_tasks = sorted(all_tasks, key=lambda t: (t["priority"], t.get("deadline") or "9999"))
        next_task = sorted_tasks[0] if sorted_tasks else None

    summary = (
        f"进度 {done}/{total}（{rate*100:.0f}%），"
        f"进行中 {in_progress}，待开始 {pending}"
        + (f"，延期 {delayed}" if delayed > 0 else "")
    )

    return {
        "total": total,
        "done": done,
        "in_progress": in_progress,
        "pending": pending,
        "delayed": delayed,
        "completion_rate": round(rate, 4),
        "next_task": next_task,
        "summary": summary,
    }


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 模拟方案
    plan_four = {
        "model": "four_account",
        "allocations": {
            "emergency": {"monthly": 2000},
            "growth": {"monthly": 7000},
            "stable": {"monthly": 8000},
        },
    }

    profile = {"income": "20-30万"}

    print("=== 四账户任务 ===")
    tasks = generate_tasks(plan_four, profile)
    for i, t in enumerate(tasks):
        print(f"  {i}. [{t['category']}] P{t['priority']} {t['task_desc']}")

    print("\n=== 任务核验 ===")
    # 模拟资产记录
    print(verify_completion(tasks[0], asset_records=[]))
    print(verify_completion(tasks[1], asset_records=[]))
