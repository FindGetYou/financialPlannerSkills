"""
新闻扫描器：从新闻源抓取标题 → 匹配关键词 → 输出待分析条目。

函数：
  fetch_headlines(sources, limit=10) → 抓取新闻标题
  match_keywords(headlines, keywords) → 关键词匹配
  as_analysis_prompt(matches, plan, profile) → 组装给 AI 分析用的 prompt

依赖：sniff_setup.py (关键词生成), db_query.py (读配置)

注意：中国境内新闻源 RSS 不稳定，本脚本尽力而为。
      抓取失败时返回空列表，由 Agent 的 SKILL.md 指导使用 web_search 补充。
"""

import json
import re
import sys
import os
from datetime import datetime

_script_dir = os.path.dirname(os.path.abspath(__file__))
_user_scripts = os.path.expanduser("~/.financial-planner/scripts")
_project_scripts = os.path.join(_script_dir, "..", "..", "..", "scripts")
for _p in [_project_scripts, _user_scripts]:
    _p = os.path.abspath(_p)
    if _p not in sys.path and os.path.isdir(_p):
        sys.path.insert(0, _p)

import db_query

# 尝试导入 curl 替代方案
try:
    import urllib.request
    import urllib.error
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════
# 新闻抓取
# ═══════════════════════════════════════════════════════════════

def fetch_headlines(sources: list, limit: int = 10) -> list:
    """
    从新闻源抓取标题。

    Args:
        sources: [{"name": "...", "url": "...", "type": "web"}, ...]
        limit: 每个源最多取几个标题

    返回:
        [{"title": "新闻标题", "source": "来源名", "url": "文章链接", "fetched_at": "ISO时间"},
         ...]
    """
    headlines = []

    for src in sources:
        source_name = src.get("name", "未知来源")
        source_url = src.get("url", "")
        source_type = src.get("type", "web")

        try:
            if source_type == "rss":
                items = _fetch_rss(source_url, limit)
            else:
                items = _fetch_web(source_url, source_name, limit)

            for item in items:
                item["source"] = source_name
                item["fetched_at"] = datetime.now().isoformat()
            headlines.extend(items)

        except Exception:
            # 单个源失败不影响其他源
            continue

    return headlines


def _fetch_rss(url: str, limit: int) -> list:
    """尝试从 RSS/Atom 抓取标题"""
    items = []
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # 简易 RSS 解析：找 <title> 标签
        titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.+?)(?:\]\]>)?</title>", content)
        links = re.findall(r"<link>(.+?)</link>", content)

        for i, title in enumerate(titles[1:limit+1]):  # 跳过 channel title
            item = {"title": title.strip(), "url": links[i+1] if i+1 < len(links) else url}
            items.append(item)
    except Exception:
        pass
    return items


def _fetch_web(url: str, source_name: str, limit: int) -> list:
    """
    尝试从网页抓取标题（简易 HTML 解析）。

    优先匹配常见的财经新闻标题模式，识别 <a> 标签或 h1-h4 中的文本。
    中文财经网站常使用 JSONP 或动态渲染，此方法可能获取不到最新内容。
    此时返回空列表，由 Agent 使用 web_search 补充。
    """
    items = []
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # 策略 1：提取 <a> 标签中含有较长文本的链接（可能是新闻标题）
        # 优先匹配 href 中有 /article/、/news/、/detail/ 模式的
        link_pattern = re.compile(
            r'<a[^>]*href=["\']([^"\']*(?:article|news|detail|story|flash)[^"\']*)["\'][^>]*>'
            r'\s*(.+?)\s*</a>',
            re.DOTALL | re.IGNORECASE,
        )
        matches = link_pattern.findall(content)

        for href, text in matches:
            text = re.sub(r"<[^>]+>", "", text).strip()
            if len(text) > 8 and len(text) < 120:
                full_url = href if href.startswith("http") else _join_url(url, href)
                items.append({"title": text, "url": full_url})
                if len(items) >= limit:
                    break

        # 策略 2：如果策略 1 没找到，尝试 <title> 类标签
        if not items:
            title_pattern = re.compile(r'<(?:h[1-4]|div[^>]*class=["\'][^"\']*title[^"\']*["\'])[^>]*>\s*(.+?)\s*</(?:h[1-4]|div)>', re.DOTALL | re.IGNORECASE)
            matches = title_pattern.findall(content)
            for text in matches:
                text = re.sub(r"<[^>]+>", "", text).strip()
                if 8 < len(text) < 120:
                    items.append({"title": text, "url": url})
                    if len(items) >= limit:
                        break

    except Exception:
        pass

    return items


def _join_url(base: str, href: str) -> str:
    """拼接相对 URL"""
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        # 取 base 的域名部分
        domain = re.match(r"(https?://[^/]+)", base)
        if domain:
            return domain.group(1) + href
    return base.rstrip("/") + "/" + href.lstrip("/")


# ═══════════════════════════════════════════════════════════════
# 关键词匹配
# ═══════════════════════════════════════════════════════════════

def match_keywords(headlines: list, keywords: list) -> list:
    """
    将标题与关键词列表匹配。

    Args:
        headlines: fetch_headlines() 返回的标题列表
        keywords: 关键词字符串列表（如 ["A股", "沪深300", "降息"]）

    返回:
        [{
            "title": "原标题",
            "source": "来源",
            "url": "链接",
            "matched_keywords": ["匹配到的关键词"],
            "fetched_at": "...",
         }, ...]
    """
    matches = []
    for h in headlines:
        title = h.get("title", "")
        matched = [kw for kw in keywords if kw.lower() in title.lower()]
        if matched:
            matches.append({
                "title": title,
                "source": h.get("source", ""),
                "url": h.get("url", ""),
                "matched_keywords": matched,
                "fetched_at": h.get("fetched_at", ""),
            })
    return matches


# ═══════════════════════════════════════════════════════════════
# 分析 prompt 组装
# ═══════════════════════════════════════════════════════════════

def as_analysis_prompt(matches: list, plan: dict, profile: dict = None) -> str:
    """
    将匹配结果组装成给 AI 分析的 prompt。

    Args:
        matches: match_keywords() 返回的匹配条目
        plan: 用户方案 dict
        profile: 用户画像 dict（可选，用于上下文）

    返回: str 可直接发送给 LLM 的 prompt
    """
    model_name = plan.get("model_name", plan.get("model", "未知模型"))

    profile_str = ""
    if profile:
        ps = plan.get("profile_summary", {})
        if ps:
            profile_str = (
                f"用户概况：{ps.get('age', '?')}岁，{ps.get('city', '?')}，"
                f"{ps.get('career', '?')}，风险偏好{ps.get('risk_tolerance', '平衡型')}\n"
            )

    if not matches:
        return "本次扫描未发现匹配的新闻，无需分析。"

    match_list = []
    for i, m in enumerate(matches, 1):
        kws = "、".join(m["matched_keywords"])
        match_list.append(
            f"{i}. [{m['source']}] {m['title']}\n"
            f"   匹配关键词：{kws}\n"
            f"   链接：{m['url']}"
        )

    prompt = f"""你是一位财务风险分析师。你的用户采用了「{model_name}」进行资产配置。

{profile_str}
以下是本次扫描到可能与用户资产相关的新闻（共 {len(matches)} 条）：

{chr(10).join(match_list)}

请逐一分析每条新闻：
1. **是否跟用户的方案相关？** 不相关直接跳过
2. **影响程度如何？** 按以下标准分级：
   - 🟡 提示：关注即可，不影响方案
   - 🟠 关注：可能影响方案，需要留意后续发展
   - 🔴 预警：需要立即关注，可能需调整方案
3. **建议操作**：如果达到 🟠 或 🔴 级别，给用户一个简短的行动建议

最后给出总体判断：本次扫描是否需要通知用户。如果所有新闻都只是 🟡 级别或无关，建议不打扰用户。

请用中文回复。格式简洁，每条新闻不超过 3 行分析。"""

    return prompt


# ═══════════════════════════════════════════════════════════════
# 扫描主流程
# ═══════════════════════════════════════════════════════════════

def scan(plan_id: int = None, profile: dict = None, template_path: str = None) -> dict:
    """
    执行一次完整扫描：读配置 → 抓取 → 匹配 → 组装 prompt。

    Args:
        plan_id: 方案 ID。如果 None，扫描所有活跃方案的配置
        profile: 用户画像
        template_path: news_sources.yaml 路径

    返回:
        {
            "matches": [...],
            "analysis_prompt": "给 AI 的 prompt",
            "plan": plan dict,
            "keywords_checked": [...],
            "sources_checked": [...],
        }
    """
    from sniff_setup import map_sources as _map_sources

    if plan_id is not None:
        sniff_configs = db_query.get_sniff_configs(plan_id=plan_id, active_only=True)
        active_plan = db_query.get_active_plan()
    else:
        # 扫描所有活跃方案
        active_plan = db_query.get_active_plan()
        if active_plan:
            sniff_configs = db_query.get_sniff_configs(plan_id=active_plan["id"], active_only=True)
        else:
            return {"matches": [], "analysis_prompt": "无活跃方案，无法扫描", "plan": None}

    if not sniff_configs:
        # 无配置 → 自动生成
        if active_plan:
            configs = _map_sources(active_plan, template_path)
            sniff_configs = [
                {
                    "keyword": c["keyword"],
                    "source_urls": [s["url"] for s in c["sources"]],
                    "frequency": "weekly",
                    "priority": c["priority"],
                }
                for c in configs
            ]
        else:
            return {"matches": [], "analysis_prompt": "无活跃方案且无嗅探配置", "plan": None}

    # 收集所有 source_urls（去重）
    all_sources = []
    all_keywords = []
    seen_urls = set()
    for cfg in sniff_configs:
        all_keywords.append(cfg["keyword"])
        for url in (cfg.get("source_urls") or []):
            if url not in seen_urls:
                seen_urls.add(url)
                all_sources.append({"url": url, "name": cfg.get("keyword", "")})

    # 抓取 + 匹配
    headlines = fetch_headlines(all_sources)
    matches = match_keywords(headlines, all_keywords)

    # 组装 prompt
    prompt = as_analysis_prompt(matches, active_plan or {}, profile)

    return {
        "matches": matches,
        "analysis_prompt": prompt,
        "plan": active_plan,
        "keywords_checked": list(set(all_keywords)),
        "sources_checked": list(seen_urls),
    }


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== 测试抓取（5 大源）===")
    sources = [
        {"name": "财联社", "url": "https://www.cls.cn/telegraph", "type": "web"},
        {"name": "东方财富", "url": "https://finance.eastmoney.com/a/czqyw.html", "type": "web"},
    ]
    headlines = fetch_headlines(sources, limit=5)
    print(f"共抓取 {len(headlines)} 条")
    for h in headlines[:5]:
        print(f"  [{h['source']}] {h['title'][:60]}...")

    print(f"\n=== 关键词匹配测试 ===")
    test_headlines = [
        {"title": "央行宣布降息25个基点 LPR跟随下调", "source": "财联社", "url": "https://..."},
        {"title": "A股三大指数集体走强 沪深300涨超2%", "source": "东方财富", "url": "https://..."},
        {"title": "今日天气晴好 适宜出行", "source": "某新闻网", "url": "https://..."},
    ]
    matched = match_keywords(test_headlines, ["降息", "A股", "沪深300", "LPR"])
    print(f"匹配 {len(matched)} 条:")
    for m in matched:
        print(f"  {m['title']} ← {m['matched_keywords']}")

    print(f"\n=== Prompt 示例 ===")
    plan = {"model": "four_account", "model_name": "四账户模型"}
    prompt = as_analysis_prompt(matched, plan)
    print(prompt[:500])
