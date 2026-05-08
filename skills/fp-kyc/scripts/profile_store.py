"""
fp-kyc 画像采集工作流封装

在 db_query.py 的基础上封装采集流程逻辑：
  - 按轮次管理采集进度
  - 字段校验
  - 判断是否可以进入方案设计

用法：
  from profile_store import (
      get_collection_plan,
      collect_field,
      finalize_round,
      is_ready_for_planning,
  )

依赖：需要 scripts/ 在 sys.path 中，且 db_query.py 可导入。
"""

import sys
import os

# 确保能导入 db_query（从 ~/.financial-planner/scripts/ 或 ../scripts/）
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_scripts = os.path.join(_script_dir, "..", "..", "..", "scripts")
_user_scripts = os.path.expanduser("~/.financial-planner/scripts")
for _p in [_project_scripts, _user_scripts]:
    if _p not in sys.path and os.path.isdir(_p):
        sys.path.insert(0, _p)

import db_query

# ────────────────────────────────────────────────────────────
# 字段定义：14 个字段，按轮次分组
# ────────────────────────────────────────────────────────────

FIELD_DEFS = {
    # 第 1 轮：基本信息
    "age":             {"round": 1, "category": "basic_info", "value_type": "range",   "required": True},
    "city":            {"round": 1, "category": "basic_info", "value_type": "exact",   "required": True},
    "career":          {"round": 1, "category": "basic_info", "value_type": "exact",   "required": True},
    "family":          {"round": 1, "category": "basic_info", "value_type": "exact",   "required": True},

    # 第 2 轮：资产与收支
    "income":          {"round": 2, "category": "cashflow",   "value_type": "range",   "required": True},
    "expense":         {"round": 2, "category": "cashflow",   "value_type": "range",   "required": True},
    "net_worth":       {"round": 2, "category": "assets",     "value_type": "range",   "required": True},
    "has_house":       {"round": 2, "category": "assets",     "value_type": "exact",   "required": True},
    "has_insurance":   {"round": 2, "category": "assets",     "value_type": "exact",   "required": True},

    # 第 3 轮：风险与目标
    "risk_tolerance":  {"round": 3, "category": "risk",       "value_type": "exact",   "required": True},
    "goal_financial":  {"round": 3, "category": "lifecycle",  "value_type": "exact",   "required": True},
    "goal_timeline":   {"round": 3, "category": "lifecycle",  "value_type": "range",   "required": False},
    "goal_education":  {"round": 3, "category": "lifecycle",  "value_type": "ratio",   "required": False},
    "goal_other":      {"round": 3, "category": "lifecycle",  "value_type": "exact",   "required": False},
}

TOTAL_FIELDS = len(FIELD_DEFS)
REQUIRED_FIELDS = {name for name, d in FIELD_DEFS.items() if d["required"]}


# ────────────────────────────────────────────────────────────
# 采集进度
# ────────────────────────────────────────────────────────────

def get_collection_plan():
    """
    返回采集计划和当前进度。

    返回:
        {
            "total_fields": 14,
            "confirmed_count": int,
            "snapshot_count": int,
            "skipped_count": int,
            "rounds": {
                1: {"total": 4, "confirmed": 2, "snapshot": 1, "remaining": ["career", "family"]},
                2: {"total": 5, "confirmed": 0, "snapshot": 0, "remaining": ["income", ...]},
                3: {"total": 5, "confirmed": 0, "snapshot": 0, "remaining": [...], "optional": ["goal_timeline", ...]},
            },
            "current_round": int,          # 下一个需要采集的轮次
            "skip_count": int,             # 已跳过的字段数
            "is_complete": bool,
        }
    """
    summary = db_query.get_profile_summary()
    fields = summary.get("fields", [])

    # 构建已有字段的映射
    existing = {}
    for f in fields:
        if f["field_name"] in FIELD_DEFS:
            existing[f["field_name"]] = f["version"]  # confirmed / snapshot

    # 检查跳过记录（在 session_context 中记录了用户明确跳过的字段）
    skipped = _get_skipped_fields()

    plan = {
        "total_fields": TOTAL_FIELDS,
        "confirmed_count": summary.get("confirmed_fields", 0),
        "snapshot_count": summary.get("snapshot_fields", 0),
        "rounds": {},
        "current_round": None,
        "skip_count": len(skipped),
        "is_complete": summary.get("confirmed_fields", 0) >= TOTAL_FIELDS,
    }

    # 按轮次分组统计
    for rd in [1, 2, 3]:
        rd_fields = [n for n, d in FIELD_DEFS.items() if d["round"] == rd]
        confirmed = [n for n in rd_fields if existing.get(n) == "confirmed"]
        snapshot = [n for n in rd_fields if existing.get(n) == "snapshot"]
        remaining = [n for n in rd_fields if n not in existing and n not in skipped]
        optional_in_rd = [n for n in rd_fields if not FIELD_DEFS[n]["required"]]

        plan["rounds"][rd] = {
            "total": len(rd_fields),
            "confirmed": len(confirmed),
            "snapshot": len(snapshot),
            "remaining": remaining,
            "optional": optional_in_rd,
            "done": len(confirmed) == len(rd_fields) or (
                len(remaining) == 0 and len(snapshot) == 0
            ),
        }

        # 找到第一个还有未完成字段的轮次
        if plan["current_round"] is None and not plan["rounds"][rd]["done"]:
            plan["current_round"] = rd

    return plan


# ────────────────────────────────────────────────────────────
# 采集字段
# ────────────────────────────────────────────────────────────

def validate_field(field_name, value, value_type):
    """
    校验字段值的合法性。

    返回:
        (valid: bool, error_msg: str)
    """
    if field_name not in FIELD_DEFS:
        return False, f"未知字段: {field_name}"

    if not value or not str(value).strip():
        return False, f"{field_name} 的值不能为空"

    # value_type 校验
    if value_type == "range":
        s = str(value).strip()
        if not any(c in s for c in ["-", "~", "以", "区间", "约", "左右", "以内"]):
            # 如果看起来像纯数字，给个宽松处理（用户可能输入了"30"）
            pass
    elif value_type == "exact":
        pass  # 自由文本不过度校验

    return True, ""


def collect_field(field_name, field_value, value_type=None, round_num=None):
    """
    采集一个字段，写入 snapshot。

    Args:
        field_name: 字段名
        field_value: 字段值
        value_type: exact / range / ratio / unknown，默认从 FIELD_DEFS 推断
        round_num: 所属轮次（可选，用于日志）

    返回:
        (success: bool, message: str)
    """
    if field_name not in FIELD_DEFS:
        return False, f"未知字段: {field_name}"

    fd = FIELD_DEFS[field_name]
    if value_type is None:
        value_type = fd["value_type"]

    # 校验
    valid, err = validate_field(field_name, field_value, value_type)
    if not valid:
        return False, err

    try:
        db_query.upsert_profile_field(
            field_name=field_name,
            field_value=str(field_value),
            value_type=value_type,
            category=fd["category"],
            version="snapshot",
        )
        return True, f"{field_name} 已记录（待确认）"
    except Exception as e:
        return False, f"写入失败: {e}"


def skip_field(field_name):
    """
    记录用户跳过的字段（写入 session_context.pending_todos 标记）。
    跳过的字段不在本轮要求，后续会话提醒。

    返回: True
    """
    skipped = _get_skipped_fields()
    if field_name not in skipped:
        skipped.append(field_name)
    _save_skipped_fields(skipped)
    return True


# ────────────────────────────────────────────────────────────
# 确认轮次
# ────────────────────────────────────────────────────────────

def get_round_snapshot_fields(round_num):
    """
    获取指定轮次所有 snapshot 状态的字段。

    返回: list[dict]  每个字段的 {field_name, field_value, value_type}
    """
    summary = db_query.get_profile_summary()
    fields = summary.get("fields", [])
    rd_field_names = {n for n, d in FIELD_DEFS.items() if d["round"] == round_num}
    return [f for f in fields if f["field_name"] in rd_field_names and f["version"] == "snapshot"]


def finalize_round(round_num):
    """
    将该轮所有 snapshot 字段批量标记为 confirmed。
    调用前应先向用户展示字段列表并等待确认。

    返回:
        (success: bool, message: str, confirmed_fields: list, skipped_in_round: list)
    """
    snapshot_fields = get_round_snapshot_fields(round_num)
    if not snapshot_fields:
        # 检查：是否所有可选字段都被跳过了
        rd_fields = {n for n, d in FIELD_DEFS.items() if d["round"] == round_num}
        skipped = _get_skipped_fields()
        skipped_in_rd = [n for n in rd_fields if n in skipped]
        return True, f"第 {round_num} 轮没有待确认的字段", [], skipped_in_rd

    field_names = [f["field_name"] for f in snapshot_fields]
    db_query.batch_confirm_fields(field_names)

    skipped = _get_skipped_fields()
    rd_fields = {n for n, d in FIELD_DEFS.items() if d["round"] == round_num}
    skipped_in_rd = [n for n in rd_fields if n in skipped]

    return True, f"第 {round_num} 轮 {len(field_names)} 个字段已确认", field_names, skipped_in_rd


# ────────────────────────────────────────────────────────────
# 进入方案设计的判断
# ────────────────────────────────────────────────────────────

def is_ready_for_planning():
    """
    判断当前数据是否满足方案设计的最低门槛。

    返回:
        (ready: bool, level: 'full' | 'good' | 'basic' | 'not_ready', message: str)

    门槛规则：
        full:   14/14 全部 confirmed
        good:   至少 10 个 confirmed，且包含 income + risk_tolerance
        basic:  至少 6 个 confirmed，且满足下面任一：
                (income AND risk_tolerance) OR (age AND goal_financial)
        not_ready: 以上都不满足
    """
    summary = db_query.get_profile_summary()
    fields = summary.get("fields", [])

    confirmed_fields = {f["field_name"]: f["field_value"] for f in fields if f["version"] == "confirmed"}
    confirmed_count = len(confirmed_fields)

    # Full
    if confirmed_count >= TOTAL_FIELDS:
        return True, "full", "画像采集完成，可以输出最完整的规划方案。"

    # Good（10+ confirmed, income + risk_tolerance）
    if (confirmed_count >= 10
            and "income" in confirmed_fields
            and "risk_tolerance" in confirmed_fields):
        return True, "good", "信息比较充分，可以设计完整的方案。"

    # Basic（6+ confirmed, 两种组合至少满足一种）
    has_income_risk = "income" in confirmed_fields and "risk_tolerance" in confirmed_fields
    has_age_goal = "age" in confirmed_fields and "goal_financial" in confirmed_fields

    if confirmed_count >= 6 and (has_income_risk or has_age_goal):
        return True, "basic", "目前信息可以出一个基础方案。提供更详细的信息可以得到更精准的规划。"

    # Not ready
    hints = []
    if "income" not in confirmed_fields and "income" not in [f["field_name"] for f in fields]:
        hints.append("年收入")
    if "risk_tolerance" not in confirmed_fields and "risk_tolerance" not in [f["field_name"] for f in fields]:
        hints.append("风险偏好")
    if "goal_financial" not in confirmed_fields and "goal_financial" not in [f["field_name"] for f in fields]:
        hints.append("财务目标")

    hint_str = "、".join(hints[:3])
    return False, "not_ready", f"目前信息还不太够做规划，至少需要提供 {hint_str}。要不要先补充一下？"


# ────────────────────────────────────────────────────────────
# 跳过字段的存储（复用 session_context.pending_todos 的 JSON）
# ────────────────────────────────────────────────────────────

def _get_skipped_fields():
    """从 session_context 读取跳过的字段列表。"""
    ctx = db_query.get_session_context()
    if ctx is None:
        return []
    # 利用 pending_todos 字段存储跳过的字段名，格式为 "skip:field_name"
    todos = ctx.get("pending_todos", [])
    return [t.replace("skip:", "") for t in todos if t.startswith("skip:")]


def _save_skipped_fields(skipped_list):
    """将跳过的字段列表存入 session_context。"""
    # 保留非 skip 前缀的 todo
    ctx = db_query.get_session_context()
    existing_todos = ctx.get("pending_todos", []) if ctx else []
    other_todos = [t for t in existing_todos if not t.startswith("skip:")]
    skip_todos = [f"skip:{f}" for f in skipped_list]
    db_query.update_session_context(todos=other_todos + skip_todos)


# ────────────────────────────────────────────────────────────
# 自检
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Collection Plan ===")
    import json
    plan = get_collection_plan()
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    print("\n=== Ready for Planning? ===")
    ready, level, msg = is_ready_for_planning()
    print(f"Ready: {ready}, Level: {level}")
    print(f"Message: {msg}")
