"""
风险嗅探配置：关键词生成 + 新闻源映射 + 配置落库。

函数：
  generate_keywords(plan) → 根据方案生成关键词列表
  map_sources(plan, template_path) → 关键词 → 新闻源映射
  save_configs(plan_id, configs) → 写入 risk_sniff_config 表

依赖：db_query.py, templates/news_sources.yaml（可选）
"""

import json
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


# ────────────────────────────────────────────────────────────
# 默认新闻源（news_sources.yaml 不存在时的兜底）
# ────────────────────────────────────────────────────────────

DEFAULT_SOURCES = {
    "宏观经济": [
        {"name": "财联社", "url": "https://www.cls.cn/telegraph", "type": "web"},
        {"name": "华尔街见闻", "url": "https://wallstreetcn.com/news/global", "type": "web"},
    ],
    "A股/指数": [
        {"name": "东方财富", "url": "https://finance.eastmoney.com/a/czqyw.html", "type": "web"},
        {"name": "新浪财经", "url": "https://finance.sina.com.cn/stock/", "type": "web"},
    ],
    "基金/债券": [
        {"name": "天天基金", "url": "https://fund.eastmoney.com/news/czqyw.html", "type": "web"},
        {"name": "雪球", "url": "https://xueqiu.com/today", "type": "web"},
    ],
    "房地产": [
        {"name": "新浪财经-房产", "url": "https://finance.sina.com.cn/realstock/company/sh000001/nc.shtml", "type": "web"},
        {"name": "华尔街见闻-地产", "url": "https://wallstreetcn.com/topics/realestate", "type": "web"},
    ],
    "保险": [
        {"name": "财经网-保险", "url": "https://finance.caijing.com.cn/insurance/", "type": "web"},
    ],
}


def _load_sources(template_path=None):
    """加载新闻源配置（YAML 优先，不存在用默认）"""
    if template_path and os.path.exists(template_path):
        try:
            import yaml
            with open(template_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            pass
    # 也尝试用户目录的 news_sources.yaml
    user_yaml = os.path.expanduser("~/.financial-planner/templates/news_sources.yaml")
    if os.path.exists(user_yaml):
        try:
            import yaml
            with open(user_yaml, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            pass
    return DEFAULT_SOURCES


# ═══════════════════════════════════════════════════════════════
# 关键词生成
# ═══════════════════════════════════════════════════════════════

def generate_keywords(plan: dict) -> list:
    """
    根据方案自动生成嗅探关键词列表。

    Args:
        plan: 方案 dict（含 model 和 allocations）

    返回:
        [{"keyword": "关键字", "category": "A股/指数", "priority": "high"},
         {"keyword": "关键字", "category": "基金/债券", "priority": "medium"}, ...]
    """
    model = plan.get("model", "")
    keywords = []

    # 通用宏观经济关键词（所有方案都加）
    common = [
        ("降息", "宏观经济", "high"),
        ("降准", "宏观经济", "high"),
        ("通胀", "宏观经济", "medium"),
        ("CPI", "宏观经济", "medium"),
        ("LPR", "宏观经济", "medium"),
        ("央行", "宏观经济", "high"),
    ]
    for kw, cat, pri in common:
        keywords.append({"keyword": kw, "category": cat, "priority": pri})

    if model == "four_account":
        _add_kw(keywords, "指数基金", "基金/债券", "high")
        _add_kw(keywords, "债券基金", "基金/债券", "high")
        _add_kw(keywords, "A股", "A股/指数", "high")
        _add_kw(keywords, "沪深300", "A股/指数", "high")
        _add_kw(keywords, "货币基金", "基金/债券", "medium")
        # 保障相关
        _add_kw(keywords, "重疾险", "保险", "medium")
        _add_kw(keywords, "医疗险", "保险", "medium")

    elif model == "core_satellite":
        alloc = plan.get("allocations", {})
        sat_desc = alloc.get("satellite", {}).get("description", "")
        core_desc = alloc.get("core", {}).get("description", "")

        # 从核心仓提取关键词
        for asset in ["沪深300", "中证500", "国债", "可转债", "大盘"]:
            if asset in core_desc:
                _add_kw(keywords, asset, "A股/指数", "high")
        if "国债" in core_desc:
            _add_kw(keywords, "国债收益率", "基金/债券", "high")

        # 从卫星仓提取关键词
        for asset in ["消费", "科技", "医药", "黄金", "海外", "QDII"]:
            if asset in sat_desc:
                _add_kw(keywords, asset, "A股/指数", "medium")
        if "黄金" in sat_desc:
            _add_kw(keywords, "黄金价格", "宏观经济", "medium")
        if "海外" in sat_desc or "QDII" in sat_desc:
            _add_kw(keywords, "美联储", "宏观经济", "medium")
            _add_kw(keywords, "人民币汇率", "宏观经济", "medium")

    elif model == "goal_oriented":
        goal = plan.get("goal", {})
        goal_type = goal.get("type", "")

        if goal_type == "买房":
            _add_kw(keywords, "房贷利率", "房地产", "high")
            _add_kw(keywords, "楼市政策", "房地产", "high")
            _add_kw(keywords, "房价", "房地产", "high")
            _add_kw(keywords, "首付", "房地产", "medium")
        elif goal_type == "退休":
            _add_kw(keywords, "养老金", "宏观经济", "high")
            _add_kw(keywords, "退休政策", "宏观经济", "medium")
            _add_kw(keywords, "养老目标基金", "基金/债券", "medium")
        elif goal_type == "被动收入":
            _add_kw(keywords, "红利指数", "A股/指数", "high")
            _add_kw(keywords, "高息债", "基金/债券", "medium")
            _add_kw(keywords, "REITs", "基金/债券", "medium")
            _add_kw(keywords, "股息", "A股/指数", "medium")

    # 去重（同 keyword 同 category 的合并）
    seen = set()
    dedup = []
    for kw in keywords:
        key = (kw["keyword"], kw["category"])
        if key not in seen:
            seen.add(key)
            dedup.append(kw)
    return dedup


def _add_kw(lst, keyword, category, priority):
    lst.append({"keyword": keyword, "category": category, "priority": priority})


# ═══════════════════════════════════════════════════════════════
# 新闻源映射
# ═══════════════════════════════════════════════════════════════

def map_sources(plan: dict, template_path: str = None) -> list:
    """
    根据方案和新闻源模板，生成 (关键词 → 新闻源) 的映射。

    Args:
        plan: 方案 dict
        template_path: news_sources.yaml 路径（可选）

    返回:
        [{
            "keyword": "A股",
            "category": "A股/指数",
            "priority": "high",
            "sources": [{"name": "...", "url": "...", "type": "web"}, ...]
        }, ...]
    """
    keywords = generate_keywords(plan)
    all_sources = _load_sources(template_path)

    configs = []
    for kw in keywords:
        cat = kw["category"]
        sources = all_sources.get(cat, [])
        # 如果无对应类别，尝试"宏观经济"作为兜底
        if not sources:
            sources = all_sources.get("宏观经济", [])

        configs.append({
            "keyword": kw["keyword"],
            "category": cat,
            "priority": kw["priority"],
            "sources": sources,
        })
    return configs


# ═══════════════════════════════════════════════════════════════
# 配置落库
# ═══════════════════════════════════════════════════════════════

def save_configs(plan_id: int, configs: list) -> list:
    """
    将嗅探配置写入 risk_sniff_config 表。

    先删除该 plan 的旧配置，再批量写入新配置。

    Args:
        plan_id: 方案 ID
        configs: map_sources() 返回的配置列表

    返回: list[int] 创建的配置 ID 列表
    """
    # 先停用旧配置
    conn = db_query._connect()
    try:
        conn.execute(
            "UPDATE risk_sniff_config SET active=0, updated_at=? WHERE plan_id=?",
            (db_query._now(), plan_id),
        )
        conn.commit()
    finally:
        conn.close()

    ids = []
    for cfg in configs:
        # db_query.upsert_sniff_config 的接口
        # 需要 source_urls 为 JSON 格式
        source_urls = [s["url"] for s in cfg["sources"]]
        source_names = [s["name"] for s in cfg["sources"]]

        # 直接写（upsert_sniff_config 使用 keyword + plan_id 去重）
        db_query.upsert_sniff_config(
            plan_id=plan_id,
            keyword=cfg["keyword"],
            source_urls=source_urls,
            frequency=_priority_to_frequency(cfg["priority"]),
            priority=cfg["priority"],
        )
        ids.append(plan_id)  # 简化：不跟踪具体 ID

    return ids


def _priority_to_frequency(priority: str) -> str:
    """优先级 → 建议扫描频率"""
    mapping = {"high": "daily", "medium": "weekly", "low": "monthly"}
    return mapping.get(priority, "weekly")


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    plan = {
        "model": "core_satellite",
        "allocations": {
            "core": {"description": "沪深300 + 中证500 + 国债ETF"},
            "satellite": {"description": "科技 + 医药 + 海外QDII + 黄金"},
        },
    }

    print("=== 关键词 ===")
    keywords = generate_keywords(plan)
    for kw in keywords:
        print(f"  [{kw['priority']}] {kw['keyword']} ({kw['category']})")

    print(f"\n共 {len(keywords)} 个关键词")

    print("\n=== 新闻源映射 ===")
    configs = map_sources(plan)
    for cfg in configs[:5]:
        sources_str = ", ".join(s["name"] for s in cfg["sources"][:3])
        print(f"  {cfg['keyword']} → {sources_str}")
