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

_exec_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_exec_dir, "..", "..", "..", "scripts"))
if _scripts_dir not in sys.path and os.path.isdir(_scripts_dir):
    sys.path.insert(0, _scripts_dir)
from _path_setup import init
init()

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


def save_balance_sheet(balance_sheet: dict, record_date: str = None):
    """
    将 load_forms 解析出的资产负债表写入 asset_records 表。

    同一 record_date 的产品先删后插（幂等），避免重复导入。

    Args:
        balance_sheet: load_forms 返回的 balance_sheet dict，
                       结构: {"assets": {"现金池": {"total": ..., "items": [...]}, ...},
                              "liabilities": {...}, "total_assets": ..., ...}
        record_date: 记录日期，默认今天

    返回:
        {"saved": int, "record_date": str}
    """
    import datetime as _dt
    if record_date is None:
        record_date = _dt.date.today().strftime("%Y-%m-%d")

    items = []
    for pool_name, pool_data in balance_sheet.get("assets", {}).items():
        for item in pool_data.get("items", []):
            product_name = item.get("product", "").strip()
            if not product_name:
                continue
            product_code = item.get("code", "") or _product_name_to_code(product_name)
            platform = item.get("platform", "").strip()
            amount = float(item.get("amount", 0))
            profit = float(item.get("profit_amount", 0))
            rate = item.get("return_rate")  # may be None
            items.append({
                "product_code": product_code,
                "product_name": product_name,
                "asset_type": _classify_asset_type(product_name, pool_name),
                "platform": platform,
                "holding_amount": amount,
                "profit_amount": profit,
                "return_rate": rate,
                "pool": pool_name,
            })

    if not items:
        return {"saved": 0, "record_date": record_date}

    # 先删掉同一 record_date 的所有记录（幂等）
    conn = db_query._connect()
    try:
        conn.execute(
            "DELETE FROM asset_records WHERE record_date = ?", (record_date,)
        )
        for item in items:
            conn.execute(
                """INSERT INTO asset_records
                   (product_code, product_name, type, platform, holding_amount,
                    profit_amount, return_rate, record_date, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item["product_code"], item["product_name"], item["asset_type"],
                 item["platform"], item["holding_amount"],
                 item["profit_amount"], item["return_rate"],
                 record_date, item["pool"]),
            )
        conn.commit()
    finally:
        conn.close()

    return {"saved": len(items), "record_date": record_date}


def compare_balance_sheet(new_balance_sheet: dict):
    """
    对比新加载的资产负债表与 DB 中最近一次快照的差异。

    Args:
        new_balance_sheet: load_forms 返回的 balance_sheet dict

    返回:
        {
            "has_previous": bool,          # 是否有历史快照可对比
            "previous_date": str | None,   # 上次快照日期
            "changes": [                   # 变化列表
                {"product": str, "platform": str, "change": "new"|"removed"|"amount_changed",
                 "old_amount": float|None, "new_amount": float|None, "diff": float},
            ],
            "summary": str,
        }
    """
    # 获取最近一次快照日期
    conn = db_query._connect()
    try:
        row = conn.execute(
            "SELECT record_date FROM asset_records ORDER BY record_date DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {
                "has_previous": False,
                "previous_date": None,
                "changes": [],
                "summary": "数据库中没有历史资产快照，无法对比",
            }
        prev_date = row["record_date"]

        # 获取上次快照的全部记录
        prev_rows = conn.execute(
            "SELECT * FROM asset_records WHERE record_date = ?", (prev_date,)
        ).fetchall()
        prev_map = {}
        for r in prev_rows:
            key = (r["product_name"], r["platform"])
            prev_map[key] = {
                "amount": r["holding_amount"],
                "profit_amount": r["profit_amount"] or 0,
                "return_rate": r["return_rate"],
                "pool": r["notes"],
            }
    finally:
        conn.close()

    # 构建新快照的 key → amount 映射
    new_map = {}
    for pool_name, pool_data in new_balance_sheet.get("assets", {}).items():
        for item in pool_data.get("items", []):
            product_name = item.get("product", "").strip()
            if not product_name:
                continue
            platform = item.get("platform", "").strip()
            amount = float(item.get("amount", 0))
            profit = float(item.get("profit_amount", 0))
            rate = item.get("return_rate")
            key = (product_name, platform)
            new_map[key] = {
                "amount": amount,
                "profit_amount": profit,
                "return_rate": rate,
                "pool": pool_name,
            }

    changes = []
    all_keys = set(list(prev_map.keys()) + list(new_map.keys()))

    for key in all_keys:
        product, platform = key
        prev = prev_map.get(key)
        new = new_map.get(key)

        if prev and new:
            amount_diff = round(new["amount"] - prev["amount"], 2)
            profit_changed = abs(new["profit_amount"] - prev["profit_amount"]) > 0.01
            if abs(amount_diff) > 0.01 or profit_changed:
                changes.append({
                    "product": product, "platform": platform,
                    "change": "amount_changed" if abs(amount_diff) > 0.01 else "profit_changed",
                    "old_amount": prev["amount"], "new_amount": new["amount"], "diff": amount_diff,
                    "old_profit": prev["profit_amount"], "new_profit": new["profit_amount"],
                })
        elif new and not prev:
            changes.append({
                "product": product, "platform": platform,
                "change": "new",
                "old_amount": None, "new_amount": new["amount"], "diff": new["amount"],
            })
        elif prev and not new:
            changes.append({
                "product": product, "platform": platform,
                "change": "removed",
                "old_amount": prev["amount"], "new_amount": None, "diff": -prev["amount"],
            })

    summary_parts = []
    new_count = sum(1 for c in changes if c["change"] == "new")
    removed_count = sum(1 for c in changes if c["change"] == "removed")
    changed_count = sum(1 for c in changes if c["change"] == "amount_changed")
    if new_count:
        summary_parts.append(f"新增 {new_count} 项")
    if removed_count:
        summary_parts.append(f"移除 {removed_count} 项")
    if changed_count:
        summary_parts.append(f"金额变化 {changed_count} 项")
    if not summary_parts:
        summary_parts.append("无变化")

    return {
        "has_previous": True,
        "previous_date": prev_date,
        "changes": changes,
        "summary": "；".join(summary_parts),
    }


def _product_name_to_code(name: str) -> str:
    """从产品名称生成简易 code（基金名 → 六位代码或拼音 slug）"""
    import re
    # 尝试提取括号中的基金代码，如 "华夏A500ETF联接C(022431)" → "022431"
    m = re.search(r"\((\d{4,6})\)", name)
    if m:
        return m.group(1)
    # 否则取前 20 字符做 slug
    slug = re.sub(r"[^a-zA-Z0-9一-鿿]", "", name)[:20]
    return slug if slug else name[:20]


def _classify_asset_type(product_name: str, pool_name: str) -> str:
    """根据产品名和所属池推断资产类型"""
    name_lower = product_name.lower()
    if any(kw in name_lower for kw in ["etf", "指数", "股票", "qdii", "纳指", "a500", "沪深", "中证", "红利"]):
        return "fund"
    if any(kw in name_lower for kw in ["保险", "重疾", "医疗", "意外", "寿险"]):
        return "insurance"
    if any(kw in name_lower for kw in ["usdt", "btc", "eth", "加密货币"]):
        return "other"
    return "other"


def batch_collect_from_form(form_data: dict):
    """
    批量采集表单字段，一次性写入 snapshot。

    用于替代逐轮 Q&A 模式——Agent 展示表单，用户填写后，
    Agent 解析文本提取字段值，调用本函数批量落库。

    Args:
        form_data: {field_name: value_str, ...}
                   例：{"income": "2-3万", "age": "30-35", "city": "北京"}

    返回:
        {
            "collected": [field_name, ...],       # 成功写入的字段
            "skipped_existing": [field_name, ...], # 已有 confirmed 数据，跳过
            "unknown": [field_name, ...],          # 不在 FIELD_DEFS 中的字段
            "total": int,
        }
    """
    collected = []
    skipped_existing = []
    unknown = []

    # 查现有 confirmed 字段，避免覆盖
    summary = db_query.get_profile_summary()
    existing_confirmed = set()
    if summary and summary.get("fields"):
        for f in summary["fields"]:
            if f.get("version") == "confirmed":
                existing_confirmed.add(f["field_name"])

    for field_name, field_value in form_data.items():
        if field_name not in FIELD_DEFS:
            unknown.append(field_name)
            continue

        if field_name in existing_confirmed:
            skipped_existing.append(field_name)
            continue

        fd = FIELD_DEFS[field_name]
        try:
            db_query.upsert_profile_field(
                field_name=field_name,
                field_value=str(field_value),
                value_type=fd["value_type"],
                category=fd["category"],
                version="snapshot",
            )
            collected.append(field_name)
        except Exception:
            continue

    return {
        "collected": collected,
        "skipped_existing": skipped_existing,
        "unknown": unknown,
        "total": len(form_data),
    }


def process_form_file(file_path: str):
    """
    一站式处理：加载 Excel → 解析 → 批量落库。

    这是 fp-kyc 的主要入口函数。Agent 调一次即可完成全部数据提取和入库。

    Args:
        file_path: 用户填好的 Excel 文件路径

    返回:
        {
            "loaded": load_forms 的完整输出,
            "collected": batch_collect 结果,
            "cash_snapshot": {...},
            "balance_sheet": {...},
            "ready_for_planning": (bool, level, msg),
        }
    """
    from load_forms import load as _load_forms
    form_data = _load_forms(file_path)

    if "error" in form_data:
        return {"error": form_data["error"]}

    profile_fields = form_data.get("profile_fields", {})
    collect_result = batch_collect_from_form(profile_fields)

    # 保存资产负债表到 asset_records
    balance_sheet = form_data.get("balance_sheet", {})
    asset_save_result = {"saved": 0}
    asset_compare = {"has_previous": False, "changes": [], "summary": ""}
    if balance_sheet and balance_sheet.get("total_assets", 0) > 0:
        # 先对比（在保存前，拿到上次快照的差异）
        asset_compare = compare_balance_sheet(balance_sheet)
        # 再保存本次快照
        asset_save_result = save_balance_sheet(balance_sheet)

    ready, level, msg = is_ready_for_planning()

    return {
        "loaded": form_data,
        "collected": collect_result,
        "cash_snapshot": form_data.get("cash_snapshot", {}),
        "balance_sheet": balance_sheet,
        "asset_saved": asset_save_result,
        "asset_compare": asset_compare,
        "ready_for_planning": (ready, level, msg),
    }


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
