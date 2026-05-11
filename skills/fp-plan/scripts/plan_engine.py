"""
方案引擎：根据用户画像推荐模型并生成财务方案。

函数：
  recommend_model(profile) → 推荐的模型 + 理由
  generate_plan(profile, model) → 方案 dict
  compare_plans(plan_a, plan_b) → 并列对比

依赖：calc.py, db_query.py
"""

import sys
import os

_exec_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_exec_dir, "..", "..", "..", "scripts"))
if _scripts_dir not in sys.path and os.path.isdir(_scripts_dir):
    sys.path.insert(0, _scripts_dir)
from _path_setup import init
init()

from calc import (
    fv, pv, pmt,
    retirement_gap, retirement_corpus_needed,
    four_account_allocation, allocation_drift, simple_portfolio,
    simple_invest_portfolio,
    _r, _fmt_cny,
)

# ═══════════════════════════════════════════════════════════════
# 模型推荐
# ═══════════════════════════════════════════════════════════════

def recommend_model(profile: dict):
    """
    根据画像分析，推荐最合适的资产配置模型。

    Args:
        profile: 用户画像 dict（从 db_query.get_profile_summary 获取的 fields 列表
                 或 {field_name: field_value} 的简化映射）

    返回:
        {
            "model": "four_account" | "core_satellite" | "goal_oriented",
            "confidence": "high" | "medium" | "low",
            "reason": "一句话理由",
            "alternatives": ["备选模型"],
        }
    """
    # 统一化输入：兼容两种 profile 格式
    if isinstance(profile, list):
        fields = {f["field_name"]: f["field_value"] for f in profile}
    elif isinstance(profile, dict) and "fields" in profile:
        # 画像概要格式
        fields = {f["field_name"]: f["field_value"] for f in profile.get("fields", [])}
    else:
        fields = profile

    has_goal = "goal_financial" in fields and fields["goal_financial"]
    has_timeline = "goal_timeline" in fields and fields["goal_timeline"]
    risk = fields.get("risk_tolerance", "medium")

    # 估算净资产是否为"有积蓄"
    net_worth_str = fields.get("net_worth", "")
    income_str = fields.get("income", "")
    has_assets = _is_significant_assets(net_worth_str, income_str)

    # 决策树
    if has_goal and has_timeline:
        return {
            "model": "goal_oriented",
            "confidence": "high",
            "reason": f"你有明确的财务目标「{fields['goal_financial']}」和时间规划，目标导向模型能帮你拆分子目标和独立投资策略。",
            "alternatives": ["four_account", "core_satellite"],
        }
    elif has_goal and not has_timeline:
        if has_assets:
            return {
                "model": "core_satellite",
                "confidence": "medium",
                "reason": "你提到财务目标但没给时间线，同时已有一定积蓄。建议先用核心-卫星模型优化存量资产配置，后续再细化目标方案。",
                "alternatives": ["goal_oriented", "four_account"],
            }
        else:
            return {
                "model": "four_account",
                "confidence": "medium",
                "reason": "你的财务目标还没有明确时间，建议先通过四账户模型建立健康的收支流，再逐步细化目标。",
                "alternatives": ["goal_oriented"],
            }
    elif has_assets:
        return {
            "model": "core_satellite",
            "confidence": "high",
            "reason": "你已经有一定积蓄，核心-卫星模型能帮你科学配置存量资产，兼顾稳定和收益。",
            "alternatives": ["four_account", "goal_oriented"],
        }
    else:
        return {
            "model": "four_account",
            "confidence": "high",
            "reason": "对于刚开始理财的阶段，四账户模型是最佳起点——先建立应急金和保障，再逐步积累增值资产。",
            "alternatives": [],
        }


def _get_monthly_income(fields):
    """获取月收入，自动识别画像中的 income 是月收入还是年收入"""
    inc = _parse_range_mid(fields.get("income", ""))
    if inc <= 0:
        return 10000
    # 如果小于 10 万，视为月收入；否则视为年收入需要除以 12
    return inc if inc < 100000 else inc / 12


def _get_annual_income(fields):
    """获取年收入"""
    monthly = _get_monthly_income(fields)
    return monthly * 12


def _is_significant_assets(net_worth_str, income_str):
    """判断是否有显著积蓄：净资产 > 年收入 × 2"""
    try:
        nw = _parse_range_mid(net_worth_str)
        inc = _parse_range_mid(income_str)
        # 如果 income 可能为月收入（< 10万），则换算为年收入
        if inc < 100000:
            inc = inc * 12
        return nw > inc * 2 if inc > 0 else nw > 100000
    except (ValueError, TypeError):
        return False


def _parse_range_mid(s):
    """解析区间/数值字符串，返回中间值。如 '10-20万' → 150000"""
    if not s:
        return 0
    # 已经是数值类型，直接返回
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s)
    has_wan = "万" in s
    s = s.replace("万", "").replace("约", "").replace("以内", "").replace("左右", "").strip()
    try:
        val = float(s)
        return val * 10000 if has_wan else val
    except ValueError:
        if "-" in s or "~" in s:
            parts = re.split(r"[-~]", s)
            try:
                lo = float(parts[0])
                hi = float(parts[1])
                mid = (lo + hi) / 2
                return mid * 10000 if has_wan else mid
            except (ValueError, IndexError):
                return 0
        return 0


import re


# ═══════════════════════════════════════════════════════════════
# 方案生成
# ═══════════════════════════════════════════════════════════════

def generate_plan(profile: dict, model: str):
    """
    根据画像和模型生成具体方案。

    Args:
        profile: 用户画像（dict，含 field_name → field_value 映射）
        model: "four_account" | "core_satellite" | "goal_oriented"

    返回:
        方案 dict，结构因模型而异，但都包含：
          model, profile_summary, allocations, tasks_preview, summary
    """
    if isinstance(profile, list):
        fields = {f["field_name"]: f["field_value"] for f in profile}
    elif isinstance(profile, dict) and "fields" in profile:
        fields = {f["field_name"]: f["field_value"] for f in profile.get("fields", [])}
    else:
        fields = profile

    if model == "four_account":
        return _gen_four_account(fields)
    elif model == "core_satellite":
        return _gen_core_satellite(fields)
    elif model == "goal_oriented":
        return _gen_goal_oriented(fields)
    else:
        return {"error": f"未知模型: {model}"}


def _format_simple_invest_weekly(simple_inv):
    """格式化极简投资周定投说明，生成简洁的 ETF 列表字符串"""
    parts = []
    for name, info in simple_inv["etfs"].items():
        if info["weekly_1x"] > 0:
            parts.append(f"{name}({info['code']}) ¥{info['weekly_1x']:.0f}/周")
    return "  ".join(parts)


def _profile_summary(fields):
    """从画像字段生成人类可读的摘要"""
    age = fields.get("age", "未知")
    city = fields.get("city", "未知")
    career = fields.get("career", "未知")
    family = fields.get("family", "未知")
    risk = fields.get("risk_tolerance", "平衡型")

    risk_map = {"low": "保守型", "medium": "平衡型", "high": "进取型"}
    risk_cn = risk_map.get(risk, risk)

    return {
        "age": age, "city": city, "career": career, "family": family,
        "risk_tolerance": risk_cn,
        "income": fields.get("income", "未提供"),
        "expense": fields.get("expense", "未提供"),
        "net_worth": fields.get("net_worth", "未提供"),
        "goal": fields.get("goal_financial", "未提供"),
        "timeline": fields.get("goal_timeline", "未提供"),
    }


def _gen_four_account(fields):
    """生成四账户方案"""
    monthly = _get_monthly_income(fields)
    monthly_expense = _parse_range_mid(fields.get("expense", ""))
    if monthly_expense <= 0:
        monthly_expense = 0
    # 按可支配收入（收入减支出）分配，确保方案可行
    disposable = max(monthly - monthly_expense, 0)
    if disposable < 1000:
        disposable = monthly * 0.3  # 兜底：至少按收入的 30%

    alloc = four_account_allocation(disposable)

    # 极简投资：为金鹅池（高收益账户）生成具体 ETF 配置
    risk = fields.get("risk_tolerance", "medium")
    growth_monthly = alloc["accounts"]["growth"]["monthly"]
    simple_inv = simple_invest_portfolio(growth_monthly, risk)

    ps = _profile_summary(fields)

    plan = {
        "model": "four_account",
        "model_name": "四账户模型",
        "profile_summary": ps,
        "assumptions": {
            "monthly_income": monthly,
            "monthly_expense": monthly_expense,
            "disposable_income": disposable,
            "explanation": f"月收入 {_fmt_cny(monthly)}，扣除支出 {_fmt_cny(monthly_expense)}，可支配 {_fmt_cny(disposable)} 用于四账户分配",
        },
        "allocations": {
            **alloc["accounts"],
            "growth": {
                **alloc["accounts"]["growth"],
                "note": f"高收益（极简投资）：{simple_inv['summary']}",
                "simple_invest": simple_inv,
            },
        },
        "overview": f"月可支配 {_fmt_cny(disposable)}（收入 {_fmt_cny(monthly)} - 支出 {_fmt_cny(monthly_expense)}）按四账户分配："
                   f"应急 {_fmt_cny(alloc['accounts']['emergency']['monthly'])}/月 + "
                   f"保障 {_fmt_cny(alloc['accounts']['insurance']['monthly'])}/月 + "
                   f"保本增值 {_fmt_cny(alloc['accounts']['stable']['monthly'])}/月 + "
                   f"高收益（极简投资） {_fmt_cny(alloc['accounts']['growth']['monthly'])}/月",
        "simple_invest_rationale": simple_inv["rationale"],
        "suggestions": _four_account_suggestions(fields, alloc, monthly_expense, simple_inv),
        "tasks_preview": [
            {"priority": "紧急", "desc": f"开立应急账户，存入 ¥{_r(monthly_expense*6):,.0f}（6 个月生活费）"},
            {"priority": "高", "desc": "配置基础保障：重疾险 + 医疗险 + 意外险"},
            {"priority": "中", "desc": f"每周定投极简投资组合（5 ETF），任选一天操作：{_format_simple_invest_weekly(simple_inv)}"},
            {"priority": "中", "desc": f"每月向保本账户存入 ¥{alloc['accounts']['stable']['monthly']:,.0f}，配置债券基金"},
            {"priority": "低", "desc": "每年做一次极简投资组合再平衡，恢复各 ETF 到目标权重"},
        ],
    }

    return plan


def _four_account_suggestions(fields, alloc, monthly_expense=0, simple_inv=None):
    """四账户补充建议"""
    suggestions = []

    if simple_inv:
        suggestions.append(
            "金鹅池（高收益账户）默认采用「极简投资」方法（源自 jane7.com）："
            f"{simple_inv['summary']}。这个方法简单透明、不择时、适合投资新手——"
            "你不需要判断涨跌，只需要坚持定投 + 每年再平衡。如果你有偏好的投资策略，可以随时调整。"
        )

    # 应急账户建议（按月支出计算）
    em_target = monthly_expense * 6 if monthly_expense > 0 else 60000
    suggestions.append(
        f"应急账户建议存够 {_fmt_cny(em_target)}（6 个月支出），"
        "放货币基金或活期理财，随用随取"
    )

    risk = fields.get("risk_tolerance", "medium")
    if risk == "low":
        suggestions.append("你是保守型，高收益账户可适当降低至 25%，保本增值提至 50%")
    elif risk == "high":
        suggestions.append("你是进取型，可考虑将高收益账户提至 40%-45%，接受更大波动换取更高回报")

    if "has_insurance" in fields and fields["has_insurance"].lower() in ("否", "没有", "无", "false", "0"):
        suggestions.append("你目前没有保险，建议优先配置：重疾险（年收入 3-5 倍保额）+ 百万医疗险")

    return suggestions


def _gen_core_satellite(fields):
    """生成核心-卫星方案"""
    net_worth_str = fields.get("net_worth", "")
    total = _parse_range_mid(net_worth_str)
    if total <= 0:
        total = 200000  # 默认兜底

    risk = fields.get("risk_tolerance", "medium")

    # 核心卫星比例根据风险偏好调整
    configs = {
        "low":    {"core": 0.80, "satellite": 0.20, "core_desc": "国债ETF + 高等级信用债 + 沪深300（大盘）", "sat_desc": "红利指数"},
        "medium": {"core": 0.70, "satellite": 0.30, "core_desc": "沪深300 + 中证500 + 国债ETF", "sat_desc": "消费主题 + 科技 + 黄金"},
        "high":   {"core": 0.60, "satellite": 0.40, "core_desc": "沪深300 + 中证500 + 可转债", "sat_desc": "科技 + 医药 + 海外QDII + 黄金"},
    }

    cfg = configs.get(risk, configs["medium"])

    core_amount = total * cfg["core"]
    sat_amount = total * cfg["satellite"]

    # 极简投资参考：为core仓权益部分提供具体ETF代码
    risk = fields.get("risk_tolerance", "medium")
    core_equity_ratio = cfg.get("core_equity", 0.60)  # core中权益占比
    core_equity_monthly = (core_amount * core_equity_ratio) / 12  # 折算月投入用于展示ETF方案
    simple_inv = simple_invest_portfolio(max(core_equity_monthly, 1000), risk)

    # 模拟当前持仓（空）vs 目标配置的偏离度
    current = {
        "核心仓": {"ratio": 0, "amount": 0},
        "卫星仓": {"ratio": 0, "amount": 0},
    }
    target = {"核心仓": cfg["core"], "卫星仓": cfg["satellite"]}
    drift = allocation_drift(current, target)

    ps = _profile_summary(fields)

    plan = {
        "model": "core_satellite",
        "model_name": "核心-卫星模型",
        "profile_summary": ps,
        "assumptions": {
            "total_assets": total,
            "explanation": "基于你提供的净资产估算的可投资资产，首次配置建议分批建仓",
        },
        "allocations": {
            "core": {
                "ratio": cfg["core"],
                "amount": _r(core_amount),
                "description": cfg["core_desc"],
                "assets": cfg["core_desc"].split(" + "),
                "simple_invest_note": f"权益部分建议参考极简投资等权思路：沪深300+中证500+标普500+纳斯达克100各{simple_inv['etfs']['沪深300']['ratio']*100:.0f}%，债券{simple_inv['bond_ratio']*100:.0f}%",
                "simple_invest_etfs": simple_inv["etfs"],
            },
            "satellite": {
                "ratio": cfg["satellite"],
                "amount": _r(sat_amount),
                "description": cfg["sat_desc"],
                "assets": cfg["sat_desc"].split(" + "),
            },
        },
        "drift_threshold": 0.05,
        "rebalance_frequency": "每季度",
        "suggestions": _core_satellite_suggestions(fields, cfg),
        "tasks_preview": [
            {"priority": "高", "desc": f"分批建仓核心仓 ¥{core_amount:,.0f}：{cfg['core_desc']}"},
            {"priority": "中", "desc": f"分批建仓卫星仓 ¥{sat_amount:,.0f}：{cfg['sat_desc']}"},
            {"priority": "中", "desc": "确认调仓频率和偏离阈值（建议每季度，阈值 5%）"},
            {"priority": "低", "desc": "每季度运行偏离度检查，触发阈值时执行再平衡"},
        ],
    }

    return plan


def _core_satellite_suggestions(fields, cfg):
    suggestions = []
    suggestions.append(f"核心仓（{cfg['core']*100:.0f}%）追求稳定，卫星仓（{cfg['satellite']*100:.0f}%）追求超额收益")
    suggestions.append(
        "核心仓的权益部分可以参考「极简投资」方法（源自 jane7.com）："
        "沪深300+中证500+标普500+纳斯达克100等权重配置，不做市场择时。详见方案配置中的 ETF 代码参考。"
    )

    goal = fields.get("goal_financial", "")
    timeline = fields.get("goal_timeline", "")
    if goal and timeline:
        suggestions.append(f"你的目标「{goal}」({timeline})，可随着目标临近逐步降低卫星仓比例")

    return suggestions


def _gen_goal_oriented(fields):
    """生成目标导向方案"""
    monthly_income = _get_monthly_income(fields)

    goal = fields.get("goal_financial", "财务自由")
    timeline_str = fields.get("goal_timeline", "10年")
    risk = fields.get("risk_tolerance", "medium")

    # 解析时间线
    timeline_match = re.search(r"(\d+)", str(timeline_str))
    years = int(timeline_match.group(1)) if timeline_match else 10

    # 根据目标类型判断策略
    simple_inv = None
    goal_monthly_growth = 0
    goal_lower = goal.lower()
    if any(kw in goal_lower for kw in ["买房", "首付", "购房"]):
        goal_type = "买房"
        # 低风险，短期债券为主
        strategy = "低风险策略：主要配置短期债券基金 + 货币基金，追求本金安全"
        alloc_desc = {"bond": 0.80, "cash": 0.20}
        monthly_alloc = monthly_income * 0.35  # 建议 35% 月收入
    elif any(kw in goal_lower for kw in ["退休", "养老"]):
        goal_type = "退休"
        strategy = f"目标日期策略：权益比例从当前 {(65 if risk == 'high' else 50)}% 逐年下降至 {(30 if risk == 'high' else 20)}%"
        alloc_desc = {"stock": 0.50, "bond": 0.40, "cash": 0.10}
        monthly_alloc = monthly_income * 0.25
    elif any(kw in goal_lower for kw in ["被动收入", "财务自由", "fire"]):
        goal_type = "被动收入"
        strategy = "高息策略：配置红利指数 + 高息债 + REITs，追求稳定现金流"
        alloc_desc = {"dividend_stock": 0.40, "bond": 0.35, "reits": 0.15, "cash": 0.10}
        monthly_alloc = monthly_income * 0.30
    else:
        goal_type = "通用目标"
        strategy = "平衡策略：债券+股票 50/50，兼顾增长和风险控制"
        alloc_desc = {"stock": 0.50, "bond": 0.50}
        monthly_alloc = monthly_income * 0.30

    # 极简投资增强：长期目标（退休/被动收入/通用）添加具体ETF方案
    # 买房是短期低风险目标，不适合80%权益的极简投资
    simple_inv = None
    if goal_type != "买房":
        growth_portion = 0.70  # 目标账户中70%用于长期增长
        goal_monthly_growth = monthly_alloc * growth_portion
        simple_inv = simple_invest_portfolio(max(goal_monthly_growth, 1000), risk)

    # 计算目标金额（简单估算）
    if goal_type == "买房":
        # 假设目标金额 = 月存入 × 12 × 年数 × 1.03（3% 年化）
        target_amount = monthly_alloc * 12 * years * (1.03 ** years)
    else:
        target_amount = monthly_alloc * 12 * years * (1.05 ** years)

    # 用简单仓位规划验证可行性
    simple = simple_portfolio(
        amount=0,  # 从零开始存
        goal_return=0.05,
        timeline=years,
        risk_tolerance=risk,
    )

    ps = _profile_summary(fields)

    plan = {
        "model": "goal_oriented",
        "model_name": "目标导向模型",
        "profile_summary": ps,
        "goal": {
            "description": goal,
            "type": goal_type,
            "timeline_years": years,
            "strategy": strategy,
        },
        "sub_accounts": [
            {
                "name": f"「{goal_type}」子账户",
                "monthly_contribution": _r(monthly_alloc),
                "annual_contribution": _r(monthly_alloc * 12),
                "allocation": alloc_desc,
                "estimated_target": _r(target_amount),
                "note": strategy,
                **({"simple_invest_growth_pool": {
                    "monthly_amount": _r(goal_monthly_growth),
                    "etfs": simple_inv["etfs"],
                    "summary": simple_inv["summary"],
                    "rationale": simple_inv["rationale"],
                }} if simple_inv else {}),
            },
            {
                "name": "「日常」子账户",
                "monthly_contribution": _r(monthly_income * 0.50),
                "annual_contribution": _r(monthly_income * 0.50 * 12),
                "allocation": {"emergency": 0.20, "insurance": 0.15, "stable": 0.40, "growth": 0.25},
                "note": "剩余收入按四账户管理日常资金",
            },
        ],
        "feasibility": simple.get("feasibility", "stretch"),
        "suggestions": _goal_suggestions(goal_type, years, monthly_alloc, risk),
    }

    # 简化分配描述
    alloc_desc_str = ", ".join(f"{k}:{v*100:.0f}%" for k, v in alloc_desc.items())
    plan["tasks_preview"] = [
        {"priority": "高", "desc": f"开设「{goal_type}」专属子账户，开始每周定投极简投资5 ETF组合"},
        {"priority": "中", "desc": f"配置 {alloc_desc_str}" + (f"（增长部分：{simple_inv['summary']}）" if simple_inv else "")},
        {"priority": "低", "desc": f"随目标临近（还剩 {max(years-2, 1)} 年时）逐步降低权益比例"},
    ]
    return plan


def _goal_suggestions(goal_type, years, monthly_alloc, risk):
    suggestions = []
    suggestions.append(f"建议每周定投 ¥{monthly_alloc/4.33:,.0f} 到目标子账户，坚持 {years} 年")
    if risk == "low" and goal_type != "买房":
        suggestions.append("你是保守型，建议目标子账户以债券为主，降低波动")
    if goal_type != "买房":
        suggestions.append(
            "长期增长部分默认采用「极简投资」方法（源自 jane7.com）："
            "5只ETF等权重配置，每年再平衡。这个方法适合5年以上的长期目标，简单且经过时间验证。"
        )
    suggestions.append(f"建议每年底复盘一次目标进度，根据实际情况调整月存金额")
    return suggestions


# ═══════════════════════════════════════════════════════════════
# 方案对比
# ═══════════════════════════════════════════════════════════════

def compare_plans(plan_a: dict, plan_b: dict):
    """
    两个方案并列对比。

    返回:
        {
            "plans": [plan_a_summary, plan_b_summary],
            "differences": [{"field": ..., "a": ..., "b": ..., "note": ...}],
            "recommendation": "一句话推荐",
        }
    """
    a_summary = _brief(plan_a)
    b_summary = _brief(plan_b)

    diffs = []

    # 模型对比
    if plan_a.get("model") != plan_b.get("model"):
        diffs.append({
            "field": "配置模型",
            "a": plan_a.get("model_name", plan_a.get("model")),
            "b": plan_b.get("model_name", plan_b.get("model")),
            "note": "不同模型适用于不同阶段，可切换",
        })

    # 风险等级对比
    risk_a = plan_a.get("profile_summary", {}).get("risk_tolerance", "")
    risk_b = plan_b.get("profile_summary", {}).get("risk_tolerance", "")
    if risk_a != risk_b:
        diffs.append({
            "field": "风险等级假设",
            "a": risk_a,
            "b": risk_b,
            "note": "风险偏好不同导致配置差异",
        })

    # 分配对比（仅四账户模型）
    if plan_a.get("model") == "four_account" and plan_b.get("model") == "four_account":
        alloc_a = plan_a.get("allocations", {})
        alloc_b = plan_b.get("allocations", {})
        for key in alloc_a:
            if key in alloc_b:
                ratio_a = alloc_a[key].get("ratio", 0)
                ratio_b = alloc_b[key].get("ratio", 0)
                if abs(ratio_a - ratio_b) > 0.01:
                    diffs.append({
                        "field": f"{alloc_a[key].get('note', key)}比例",
                        "a": f"{ratio_a*100:.0f}%",
                        "b": f"{ratio_b*100:.0f}%",
                        "note": "",
                    })

    # 推荐
    if plan_a.get("model") == "four_account" and plan_b.get("model") == "goal_oriented":
        recommendation = "如果有明确目标，推荐方案 B（目标导向）；日常现金流管理用方案 A（四账户）"
    elif plan_a.get("model") == "goal_oriented" and plan_b.get("model") == "core_satellite":
        recommendation = "目标导向聚焦特定目标，核心-卫星优化整体存量，可以叠加使用"
    else:
        recommendation = "两个方案各有侧重，可以根据你的实际情况选择或组合"

    return {
        "plans": [a_summary, b_summary],
        "differences": diffs,
        "recommendation": recommendation,
    }


def _brief(plan):
    """生成方案摘要（用于对比）"""
    return {
        "model": plan.get("model_name", plan.get("model")),
        "key_feature": plan.get("goal", {}).get("strategy", "")
                      or plan.get("allocations", {}).get("emergency", {}).get("note", "")
                      or plan.get("allocations", {}).get("core", {}).get("description", ""),
    }


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 模拟画像
    profile_new = {
        "age": "30-35", "city": "北京", "career": "程序员", "family": "单身",
        "income": "20-30万", "expense": "10-15万", "net_worth": "20万以内",
        "risk_tolerance": "medium",
    }
    profile_goal = {
        "age": "30-35", "city": "深圳", "career": "产品经理", "family": "已婚无娃",
        "income": "30-50万", "expense": "15-20万", "net_worth": "50-100万",
        "risk_tolerance": "medium",
        "goal_financial": "5年内在深圳买房", "goal_timeline": "5年",
    }
    profile_assets = {
        "age": "35-40", "city": "上海", "career": "金融", "family": "已婚有娃",
        "income": "50-100万", "expense": "30-50万", "net_worth": "200-500万",
        "risk_tolerance": "high",
    }

    print("=== 模型推荐 ===")
    print("新手 →", recommend_model(profile_new))
    print("有目标 →", recommend_model(profile_goal))
    print("有积蓄 →", recommend_model(profile_assets))

    print("\n=== 四账户方案（新手）===")
    plan_new = generate_plan(profile_new, "four_account")
    import json
    print(json.dumps(plan_new, ensure_ascii=False, indent=2, default=str)[:1000])

    print("\n=== 目标导向方案 ===")
    plan_goal = generate_plan(profile_goal, "goal_oriented")
    print(json.dumps(plan_goal, ensure_ascii=False, indent=2, default=str)[:1200])

    print("\n=== 核心卫星方案 ===")
    plan_assets = generate_plan(profile_assets, "core_satellite")
    print(json.dumps(plan_assets, ensure_ascii=False, indent=2, default=str)[:1200])

    print("\n=== 方案对比 ===")
    print(compare_plans(plan_new, plan_goal))
