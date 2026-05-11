"""
复盘引擎：对比资产快照、分析盈亏、检测偏离、生成复盘日记。

函数：
  generate_review(plan_id) → 完整复盘 dict
  save_review(review_data, format="both") → 存储复盘
  get_snapshot_pair() → 获取最近两次资产快照
  analyze_performance(prev_items, curr_items) → 逐产品盈亏
  build_rebalance_plan(drift, simple_inv) → 调仓计划
  build_narrative(comparison, performance, drift) → 文字总结

依赖：db_query.py, calc.py, profile_store.py
"""

import sys
import os
import json
import re
from datetime import datetime

_exec_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_exec_dir, "..", "..", "..", "scripts"))
if _scripts_dir not in sys.path and os.path.isdir(_scripts_dir):
    sys.path.insert(0, _scripts_dir)
from _path_setup import init
init()

import db_query
from calc import simple_invest_portfolio, allocation_drift, _r, _fmt_cny

# profile_store 路径
_kcy_dir = os.path.abspath(os.path.join(_exec_dir, "..", "..", "fp-kyc", "scripts"))
if _kcy_dir not in sys.path:
    sys.path.insert(0, _kcy_dir)
import profile_store


# ═══════════════════════════════════════════════════════════════
# 快照获取
# ═══════════════════════════════════════════════════════════════

def get_snapshot_pair():
    """
    获取最近两次不同日期的资产快照。

    返回: (previous_snapshot, current_snapshot)
          previous_snapshot 可能为 None（首次录入）
    """
    records = db_query.get_asset_records()
    if not records:
        return None, []

    # 按 record_date 分组
    date_groups = {}
    for r in records:
        d = r.get("record_date", "")
        if d not in date_groups:
            date_groups[d] = []
        date_groups[d].append(r)

    dates = sorted(date_groups.keys(), reverse=True)
    if not dates:
        return None, []

    curr_date = dates[0]
    curr_snapshot = date_groups[curr_date]

    prev_date = dates[1] if len(dates) >= 2 else None
    prev_snapshot = date_groups[prev_date] if prev_date else None

    return prev_snapshot, curr_snapshot


# ═══════════════════════════════════════════════════════════════
# 基准获取
# ═══════════════════════════════════════════════════════════════

def _fetch_benchmark(start_date=None, end_date=None):
    """
    获取同期沪深 300 涨跌幅作为基准参考。

    用 urllib 请求东方财富数据接口。失败则返回 None。
    """
    if not start_date or not end_date:
        return None

    try:
        import urllib.request

        # 东方财富沪深300指数历史数据接口
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            "secid=1.000300&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt=1&beg={start_date.replace('-', '')}&end={end_date.replace('-', '')}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        klines = data.get("data", {}).get("klines", [])
        if not klines or len(klines) < 2:
            return None

        first_close = float(klines[0].split(",")[2])
        last_close = float(klines[-1].split(",")[2])
        if first_close <= 0:
            return None

        change_pct = (last_close - first_close) / first_close
        return {
            "benchmark_name": "沪深300",
            "start_price": first_close,
            "end_price": last_close,
            "change_pct": round(change_pct, 4),
            "period": f"{start_date} → {end_date}",
        }
    except Exception:
        return None


def _benchmark_compare(item, profit_pct):
    """生成基准对比说明文字"""
    # 仅对权益类产品做基准对比
    if item.get("type") in ("fund", "stock") or item.get("code", "").startswith(("51", "15", "16")):
        # 尝试获取基准（从 item 中如果有 record_date 信息的话）
        benchmark = _fetch_benchmark()
        if benchmark:
            diff = profit_pct - benchmark["change_pct"]
            if abs(diff) < 0.01:
                return f"与沪深300基本持平"
            elif diff > 0:
                return f"跑赢沪深300（+{diff*100:.1f}%）"
            else:
                return f"跑输沪深300（{diff*100:.1f}%）"
    return ""


# ═══════════════════════════════════════════════════════════════
# 产品盈亏分析
# ═══════════════════════════════════════════════════════════════

def analyze_performance(prev_items, curr_items):
    """
    逐产品对比两次快照，计算盈亏。

    Args:
        prev_items: 上次快照的产品列表 (list[dict])
        curr_items: 本次快照的产品列表 (list[dict])

    返回: list[dict]
    """
    prev_map = {}
    if prev_items:
        for it in prev_items:
            key = (it.get("product_name", ""), it.get("platform", ""))
            prev_map[key] = it

    results = []
    for item in curr_items:
        key = (item.get("product_name", ""), item.get("platform", ""))
        prev = prev_map.get(key)

        if prev and prev.get("holding_amount", 0) > 0:
            prev_amt = prev["holding_amount"]
            curr_amt = item.get("holding_amount", 0)
            profit = curr_amt - prev_amt
            profit_pct = profit / prev_amt if prev_amt > 0 else 0

            prev_profit = prev.get("profit_amount", 0)
            curr_profit = item.get("profit_amount", 0)

            results.append({
                "product": item.get("product_name", ""),
                "code": item.get("product_code", ""),
                "platform": item.get("platform", ""),
                "type": item.get("type", ""),
                "prev_amount": prev_amt,
                "curr_amount": curr_amt,
                "profit": _r(profit),
                "profit_pct": round(profit_pct, 4),
                "prev_profit": prev_profit,
                "curr_profit": curr_profit,
                "benchmark_note": _benchmark_compare(item, profit_pct),
            })
        elif not prev:
            results.append({
                "product": item.get("product_name", ""),
                "code": item.get("product_code", ""),
                "platform": item.get("platform", ""),
                "type": item.get("type", ""),
                "prev_amount": 0,
                "curr_amount": item.get("holding_amount", 0),
                "profit": 0,
                "profit_pct": 0,
                "note": "新增产品，暂无对比数据",
            })

    # 标记已移除的产品
    if prev_items:
        curr_keys = {(it.get("product_name", ""), it.get("platform", "")) for it in curr_items}
        for it in prev_items:
            key = (it.get("product_name", ""), it.get("platform", ""))
            if key not in curr_keys:
                results.append({
                    "product": it.get("product_name", ""),
                    "code": it.get("product_code", ""),
                    "platform": it.get("platform", ""),
                    "type": it.get("type", ""),
                    "prev_amount": it.get("holding_amount", 0),
                    "curr_amount": 0,
                    "profit": 0,
                    "profit_pct": 0,
                    "note": "已移除",
                })

    return results


# ═══════════════════════════════════════════════════════════════
# 调仓计划
# ═══════════════════════════════════════════════════════════════

def build_rebalance_plan(drift, simple_inv):
    """
    将偏离度分析结果转化为行为型调仓步骤。

    Args:
        drift: calc.allocation_drift() 的返回
        simple_inv: calc.simple_invest_portfolio() 的返回

    返回: list[dict]
    """
    if not drift or not simple_inv:
        return []

    plans = []
    for asset, info in drift.get("drifts", {}).items():
        if abs(info["drift_ratio"]) > 0.05:
            # 在极简投资 ETF 中查找对应代码
            code = ""
            if simple_inv and "etfs" in simple_inv:
                for etf_name, etf_info in simple_inv["etfs"].items():
                    if etf_name in asset or asset in etf_name:
                        code = etf_info.get("code", "")
                        break

            action_cn = {"sell": "卖出", "buy": "买入", "hold": "持有不动"}
            plans.append({
                "asset": asset,
                "code": code,
                "action": info["action"],
                "amount": info["adjust_amount"],
                "reason": (
                    f"{'超配' if info['drift_ratio'] > 0 else '低配'} "
                    f"{abs(info['drift_ratio'])*100:.1f}%，"
                    f"建议{action_cn.get(info['action'], '调整')} "
                    f"¥{abs(info['adjust_amount']):,.0f}"
                ),
            })

    return plans


# ═══════════════════════════════════════════════════════════════
# 文字总结
# ═══════════════════════════════════════════════════════════════

def build_narrative(comparison, performance, drift):
    """
    生成复盘文字总结——客观数据 + 基准对比 + 鼓励收尾。
    """
    parts = []

    nw = comparison.get("net_worth", {})
    if nw.get("change", 0) != 0:
        direction = "增长" if nw["change"] > 0 else "减少"
        parts.append(
            f"本期净资产{direction} ¥{abs(nw['change']):,.0f}"
            f"（{abs(nw.get('change_pct', 0))*100:.1f}%）。"
        )
    else:
        parts.append("本期净资产无变化。")

    # 表现最好 / 最弱
    gainers = [p for p in performance if p.get("profit", 0) > 0]
    losers = [p for p in performance if p.get("profit", 0) < 0]

    if gainers:
        best = max(gainers, key=lambda x: x["profit_pct"])
        parts.append(
            f"表现最佳：{best['product']}，"
            f"持仓市值从 ¥{best['prev_amount']:,.0f} → ¥{best['curr_amount']:,.0f}"
            f"（+{best['profit_pct']*100:.1f}%）。"
        )
        if best.get("benchmark_note"):
            parts.append(f"  → 对比基准：{best['benchmark_note']}。")

    if losers:
        worst = min(losers, key=lambda x: x["profit_pct"])
        parts.append(
            f"表现最弱：{worst['product']}，"
            f"持仓市值从 ¥{worst['prev_amount']:,.0f} → ¥{worst['curr_amount']:,.0f}"
            f"（{worst['profit_pct']*100:.1f}%）。"
        )
        if worst.get("benchmark_note"):
            parts.append(f"  → 对比基准：{worst['benchmark_note']}。")

    # 新增/移除
    new_items = [p for p in performance if p.get("note") == "新增产品，暂无对比数据"]
    removed_items = [p for p in performance if p.get("note") == "已移除"]
    if new_items:
        names = "、".join(p["product"] for p in new_items)
        parts.append(f"新纳入：{names}。")
    if removed_items:
        names = "、".join(p["product"] for p in removed_items)
        parts.append(f"已移除：{names}。")

    # 调仓
    if drift and drift.get("max_drift", 0) > 0.05:
        parts.append(
            f"当前仓位偏离度 {drift['max_drift']*100:.1f}%，"
            f"超过 5% 阈值，建议执行再平衡。"
        )
    elif drift:
        parts.append("仓位配置在健康范围内，无需调整。继续坚持定投即可。")
    else:
        parts.append("暂无仓位偏离数据。按极简投资方法，每半年到一年检查一次即可。")

    parts.append("继续保持每周定投的节奏，每一笔操作都在为未来积累。")

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# 复盘日记 Markdown
# ═══════════════════════════════════════════════════════════════

def _write_review_markdown(review_data, output_dir=None):
    """
    将复盘数据渲染为 Markdown 文件。

    返回: 文件路径
    """
    if output_dir is None:
        output_dir = os.path.expanduser("~/.financial-planner/reviews")
    os.makedirs(output_dir, exist_ok=True)

    review_date = review_data.get("review_date", datetime.now().strftime("%Y-%m-%d"))
    filename = f"{review_date}.md"
    filepath = os.path.join(output_dir, filename)

    lines = []
    lines.append(f"# 复盘日记 — {review_date}")
    lines.append("")

    # 总体概览
    comparison = review_data.get("comparison", {})
    lines.append("## 总体概览")
    lines.append("")

    ta = comparison.get("total_assets", {})
    tl = comparison.get("total_liabilities", {})
    nw = comparison.get("net_worth", {})

    lines.append("| 指标 | 上次 | 本次 | 变化 |")
    lines.append("|------|------|------|------|")
    lines.append(
        f"| 总资产 | ¥{ta.get('previous', 0):,.0f} | ¥{ta.get('current', 0):,.0f} | "
        f"{'+' if ta.get('change', 0) >= 0 else ''}¥{ta.get('change', 0):,.0f} |"
    )
    lines.append(
        f"| 总负债 | ¥{tl.get('previous', 0):,.0f} | ¥{tl.get('current', 0):,.0f} | "
        f"{'+' if tl.get('change', 0) >= 0 else ''}¥{tl.get('change', 0):,.0f} |"
    )
    lines.append(
        f"| 净资产 | ¥{nw.get('previous', 0):,.0f} | ¥{nw.get('current', 0):,.0f} | "
        f"{'+' if nw.get('change', 0) >= 0 else ''}¥{nw.get('change', 0):,.0f}"
        f"（{'+' if nw.get('change_pct', 0) >= 0 else ''}{nw.get('change_pct', 0)*100:.1f}%）|"
    )
    lines.append("")

    # 产品盈亏
    performance = review_data.get("product_performance", [])
    if performance:
        lines.append("## 产品盈亏")
        lines.append("")
        lines.append("| 产品 | 代码 | 上次 | 本次 | 盈亏 | 收益率 | 说明 |")
        lines.append("|------|------|------|------|------|--------|------|")
        for p in performance:
            note = p.get("benchmark_note") or p.get("note") or ""
            lines.append(
                f"| {p['product']} | {p['code']} | ¥{p['prev_amount']:,.0f} | "
                f"¥{p['curr_amount']:,.0f} | "
                f"{'+' if p['profit'] >= 0 else ''}¥{p['profit']:,.0f} | "
                f"{p['profit_pct']*100:+.1f}% | {note} |"
            )
        lines.append("")

    # 仓位偏离
    drift = review_data.get("drift_analysis")
    rebalance = review_data.get("rebalance_plan", [])
    if drift or rebalance:
        lines.append("## 仓位偏离")
        lines.append("")
        if drift.get("max_drift", 0) > 0.05:
            lines.append(f"最大偏离度 {drift['max_drift']*100:.1f}%，超过 5% 阈值。")
        else:
            lines.append(f"最大偏离度 {drift.get('max_drift', 0)*100:.1f}%，在健康范围内。")
        lines.append("")

        if rebalance:
            lines.append("| 资产 | 代码 | 操作 | 金额 | 原因 |")
            lines.append("|------|------|------|------|------|")
            for plan in rebalance:
                action_cn = {"sell": "卖出", "buy": "买入", "hold": "持有"}
                lines.append(
                    f"| {plan['asset']} | {plan['code']} | "
                    f"{action_cn.get(plan['action'], plan['action'])} | "
                    f"¥{abs(plan['amount']):,.0f} | {plan['reason']} |"
                )
            lines.append("")

    # 亮点 & 关注
    highlights = review_data.get("highlights", [])
    concerns = review_data.get("concerns", [])
    if highlights or concerns:
        lines.append("## 亮点 & 关注")
        lines.append("")
        for h in highlights:
            lines.append(f"- ✅ {h}")
        for c in concerns:
            lines.append(f"- ⚠️ {c}")
        lines.append("")

    # 文字总结
    narrative = review_data.get("narrative", "")
    if narrative:
        lines.append("## 文字总结")
        lines.append("")
        lines.append(narrative)
        lines.append("")

    # 下一步
    next_steps = review_data.get("next_steps", [])
    if next_steps:
        lines.append("## 下一步")
        lines.append("")
        for step in next_steps:
            lines.append(f"- [ ] {step}")
        lines.append("")

    content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def generate_review(plan_id=None):
    """
    执行一次完整复盘，返回结构化复盘日记。

    Args:
        plan_id: 方案 ID。None 时取活跃方案。

    返回:
        {
            "review_date": "2026-05-12",
            "plan_id": 1,
            "plan_model": "four_account",
            "previous_snapshot_date": "2026-04-01" | None,
            "current_snapshot_date": "2026-05-10",
            "comparison": {
                "total_assets": {"previous": ..., "current": ..., "change": ...},
                "total_liabilities": {...},
                "net_worth": {...},
            },
            "product_performance": [...],
            "drift_analysis": {...} | None,
            "rebalance_plan": [...],
            "narrative": "文字总结",
            "highlights": [...],
            "concerns": [...],
            "next_steps": [...],
        }
    """
    plan = db_query.get_active_plan()
    if not plan:
        return {"error": "无活跃方案，无法复盘"}

    if plan_id is None:
        plan_id = plan["id"]

    # 1. 获取快照
    prev_snapshot, curr_snapshot = get_snapshot_pair()
    if not curr_snapshot:
        return {
            "error": "暂无资产记录，请先更新 Excel 文件录入资产数据",
            "plan_id": plan_id,
            "plan_model": plan.get("model", ""),
        }

    prev_date = prev_snapshot[0]["record_date"] if prev_snapshot else None
    curr_date = curr_snapshot[0]["record_date"]

    # 2. 总体对比
    prev_total_assets = sum(r.get("holding_amount", 0) for r in prev_snapshot) if prev_snapshot else 0
    curr_total_assets = sum(r.get("holding_amount", 0) for r in curr_snapshot)
    prev_total_liabilities = sum(
        r.get("holding_amount", 0) for r in (prev_snapshot or []) if r.get("type") == "other"
    )
    curr_total_liabilities = sum(
        r.get("holding_amount", 0) for r in curr_snapshot if r.get("type") == "other"
    )
    prev_nw = prev_total_assets - prev_total_liabilities
    curr_nw = curr_total_assets - curr_total_liabilities
    nw_change = curr_nw - prev_nw
    nw_pct = nw_change / prev_nw if prev_nw > 0 else 0

    comparison = {
        "total_assets": {
            "previous": prev_total_assets,
            "current": curr_total_assets,
            "change": curr_total_assets - prev_total_assets,
        },
        "total_liabilities": {
            "previous": prev_total_liabilities,
            "current": curr_total_liabilities,
            "change": curr_total_liabilities - prev_total_liabilities,
        },
        "net_worth": {
            "previous": _r(prev_nw),
            "current": _r(curr_nw),
            "change": _r(nw_change),
            "change_pct": round(nw_pct, 4),
        },
    }

    # 3. 产品盈亏分析
    performance = analyze_performance(
        prev_snapshot or [],
        curr_snapshot,
    )

    # 4. 偏离度分析（如果方案包含极简投资配置）
    drift = None
    rebalance_plan = []
    simple_inv = None

    # 尝试从方案的 target_allocations 中获取极简投资配置
    target_alloc = plan.get("target_allocations", {})
    growth_cfg = target_alloc.get("growth", {})
    if growth_cfg and "simple_invest" in growth_cfg:
        simple_inv = growth_cfg["simple_invest"]
    else:
        # 从 growth monthly 自行构建
        growth_monthly = growth_cfg.get("monthly", 0)
        if growth_monthly > 0:
            risk = target_alloc.get("risk_tolerance", "medium")
            simple_inv = simple_invest_portfolio(growth_monthly, risk)

    if simple_inv and curr_snapshot:
        # 构建当前仓位（按 ETF 名称聚合）
        current_alloc = {}
        for item in curr_snapshot:
            name = item.get("product_name", "")
            if name and item.get("type") in ("fund", "stock"):
                current_alloc[name] = {
                    "ratio": 0,  # 后面计算
                    "amount": item.get("holding_amount", 0),
                }

        if current_alloc:
            total_amount = sum(v["amount"] for v in current_alloc.values())
            if total_amount > 0:
                for name in current_alloc:
                    current_alloc[name]["ratio"] = current_alloc[name]["amount"] / total_amount

                # 构建目标配置
                target_alloc_map = {}
                for etf_name, etf_info in simple_inv["etfs"].items():
                    target_alloc_map[etf_name] = etf_info["ratio"]

                drift = allocation_drift(current_alloc, target_alloc_map)
                rebalance_plan = build_rebalance_plan(drift, simple_inv)

    # 5. 生成分析与建议
    highlights = []
    concerns = []
    next_steps = []

    gainers = [p for p in performance if p.get("profit", 0) > 0]
    if gainers:
        best = max(gainers, key=lambda x: x["profit_pct"])
        highlights.append(f"{best['product']}收益 +{best['profit_pct']*100:.1f}%，表现亮眼")

    if nw_change > 0:
        highlights.append(f"净资产增加 ¥{nw_change:,.0f}，财富在稳步增长")

    if prev_snapshot:
        highlights.append(f"坚持记录第 {len(performance)} 个产品，对自己的资产心中有数")

    losers = [p for p in performance if p.get("profit", 0) < 0]
    for p in losers[:2]:
        concerns.append(f"{p['product']}亏损 {p['profit_pct']*100:.1f}%，持续关注其表现")

    if drift and drift.get("max_drift", 0) > 0.05:
        concerns.append(f"仓位偏离 {drift['max_drift']*100:.1f}%，超过 5% 阈值")
        next_steps.append("执行再平衡调仓（详见仓位偏离表格）")

    if rebalance_plan:
        for plan_item in rebalance_plan[:3]:
            action_cn = {"sell": "卖出", "buy": "买入", "hold": "持有"}
            next_steps.append(
                f"{action_cn.get(plan_item['action'], '调整')} "
                f"{plan_item['asset']}（{plan_item['code']}）¥{abs(plan_item['amount']):,.0f}"
            )

    if not rebalance_plan:
        next_steps.append("继续每周定投极简投资组合，保持节奏")

    # 6. 叙事
    narrative = build_narrative(comparison, performance, drift)

    review_data = {
        "review_date": datetime.now().strftime("%Y-%m-%d"),
        "plan_id": plan_id,
        "plan_model": plan.get("model", ""),
        "previous_snapshot_date": prev_date,
        "current_snapshot_date": curr_date,
        "comparison": comparison,
        "product_performance": performance,
        "drift_analysis": drift,
        "rebalance_plan": rebalance_plan,
        "narrative": narrative,
        "highlights": highlights,
        "concerns": concerns,
        "next_steps": next_steps,
    }

    return review_data


def save_review(review_data, format="both"):
    """
    存储复盘日记到数据库和/或 Markdown 文件。

    Args:
        review_data: generate_review() 返回的数据
        format: "db" / "md" / "both"

    返回: {"review_id": int | None, "markdown_path": str | None}
    """
    review_id = None
    md_path = None

    if format in ("db", "both"):
        try:
            review_id = db_query.create_review(
                plan_id=review_data["plan_id"],
                review_date=review_data["review_date"],
                snapshot_prev=review_data.get("previous_snapshot_date"),
                snapshot_curr=review_data["current_snapshot_date"],
                net_worth_change=review_data["comparison"]["net_worth"]["change"],
                net_worth_change_pct=review_data["comparison"]["net_worth"].get("change_pct", 0),
                drift_max=review_data.get("drift_analysis", {}).get("max_drift"),
                rebalance_needed=1 if review_data.get("rebalance_plan") else 0,
                highlights=json.dumps(review_data.get("highlights", []), ensure_ascii=False),
                concerns=json.dumps(review_data.get("concerns", []), ensure_ascii=False),
                detail_json=json.dumps(review_data, ensure_ascii=False, default=str),
                narrative=review_data.get("narrative", ""),
            )
        except Exception:
            pass  # 数据库写入失败不阻塞 Markdown 输出

    if format in ("md", "both"):
        try:
            md_path = _write_review_markdown(review_data)
        except Exception:
            pass

    return {"review_id": review_id, "markdown_path": md_path}


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== 快照对 ===")
    prev, curr = get_snapshot_pair()
    print(f"Previous snapshot: {len(prev) if prev else 0} records")
    print(f"Current snapshot: {len(curr) if curr else 0} records")

    print("\n=== 模拟产品盈亏分析 ===")
    prev_items = [
        {"product_name": "沪深300", "product_code": "510300", "platform": "支付宝",
         "type": "fund", "holding_amount": 20000, "profit_amount": 1000},
        {"product_name": "中证500", "product_code": "510500", "platform": "支付宝",
         "type": "fund", "holding_amount": 15000, "profit_amount": 500},
    ]
    curr_items = [
        {"product_name": "沪深300", "product_code": "510300", "platform": "支付宝",
         "type": "fund", "holding_amount": 22000, "profit_amount": 2000},
        {"product_name": "中证500", "product_code": "510500", "platform": "支付宝",
         "type": "fund", "holding_amount": 14000, "profit_amount": -500},
        {"product_name": "纳斯达克100", "product_code": "513100", "platform": "支付宝",
         "type": "fund", "holding_amount": 10000, "profit_amount": 800},
    ]
    perf = analyze_performance(prev_items, curr_items)
    for p in perf:
        print(f"  {p['product']}: ¥{p['prev_amount']:,.0f} → ¥{p['curr_amount']:,.0f}"
              f" ({p['profit_pct']*100:+.1f}%) {p.get('benchmark_note', '')}")

    print("\n=== 模拟复盘日记生成 ===")
    mock_review = {
        "review_date": datetime.now().strftime("%Y-%m-%d"),
        "plan_id": 1,
        "plan_model": "four_account",
        "previous_snapshot_date": "2026-04-01",
        "current_snapshot_date": "2026-05-10",
        "comparison": {
            "total_assets": {"previous": 100000, "current": 105000, "change": 5000},
            "total_liabilities": {"previous": 0, "current": 0, "change": 0},
            "net_worth": {"previous": 100000, "current": 105000, "change": 5000, "change_pct": 0.05},
        },
        "product_performance": perf,
        "drift_analysis": None,
        "rebalance_plan": [],
        "narrative": "本期净资产增长 ¥5,000（5.0%）。表现最佳：沪深300（+10.0%）。仓位在健康范围内，继续坚持定投。",
        "highlights": ["净资产增加 ¥5,000", "沪深300 收益 +10%"],
        "concerns": ["中证500 亏损 -3.3%"],
        "next_steps": ["继续每周定投极简投资组合，保持节奏"],
    }

    md_path = _write_review_markdown(mock_review)
    print(f"Markdown written to: {md_path}")
