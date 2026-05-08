"""
财务规划纯计算模块

所有函数统一规范：
  - 输入：具名参数（不使用 dict 传参）
  - 输出：dict，包含输入回显、计算结果、推导过程
  - 精度：金额保留两位小数
  - 禁止 LLM 直接做复杂数学，全部走此模块

用法示例：
  from calc import fv, retirement_gap, four_account_allocation, income_tax
  result = fv(pv=200000, rate=0.04, years=10)
  print(result["future_value"])  # 296048.57
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


# ────────────────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────────────────

def _r(val):
    """金额保留两位小数"""
    return float(Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _fmt_cny(val):
    """格式化为人民币字符串（千分位）"""
    return f"¥{_r(val):,.2f}"


# ═══════════════════════════════════════════════════════════════
# 1. 复利计算
# ═══════════════════════════════════════════════════════════════

def fv(pv: float, rate: float, years: int, pmt: float = 0):
    """
    终值计算：现在投入一笔钱，每年追加定投，N 年后值多少。

    Args:
        pv: 现值（当前本金，元）
        rate: 年化收益率（如 0.04 表示 4%）
        years: 投资年限
        pmt: 每年追加投入（元），默认 0

    返回:
        {
            "future_value": 终值,
            "total_principal": 总投入本金,
            "total_return": 总收益,
            "annual_return_rate": 年化收益率,
        }

    公式：FV = PV*(1+r)^n + PMT*((1+r)^n - 1)/r
    """
    pv_growth = pv * (1 + rate) ** years
    if rate == 0:
        pmt_growth = pmt * years
    else:
        pmt_growth = pmt * ((1 + rate) ** years - 1) / rate

    future_value = pv_growth + pmt_growth
    total_principal = pv + pmt * years
    total_return = future_value - total_principal

    return {
        "future_value": _r(future_value),
        "total_principal": _r(total_principal),
        "total_return": _r(total_return),
        "annual_return_rate": rate,
    }


def pv(fv: float, rate: float, years: int):
    """
    现值计算：N 年后需要的钱，现在要一次存多少。

    Args:
        fv: 终值（N 年后需要的金额，元）
        rate: 年化收益率
        years: 年限

    返回:
        {
            "present_value": 现值,
            "future_value": 目标金额（回显）,
            "years": 年限,
        }

    公式：PV = FV / (1+r)^n
    """
    present_value = fv / ((1 + rate) ** years)

    return {
        "present_value": _r(present_value),
        "future_value": fv,
        "years": years,
    }


def pmt(target: float, rate: float, years: int):
    """
    定期定投计算：每年存多少才能在 N 年后攒到目标金额。

    Args:
        target: 目标金额（元）
        rate: 年化收益率
        years: 年限

    返回:
        {
            "annual_contribution": 每年需投入,
            "monthly_contribution": 每月需投入（约数）,
            "target": 目标金额（回显）,
            "total_contribution": 总投入,
        }

    公式：PMT = FV * r / ((1+r)^n - 1)
    """
    if rate == 0:
        annual = target / years
    else:
        annual = target * rate / ((1 + rate) ** years - 1)

    return {
        "annual_contribution": _r(annual),
        "monthly_contribution": _r(annual / 12),
        "target": target,
        "total_contribution": _r(annual * years),
    }


# ═══════════════════════════════════════════════════════════════
# 2. 退休规划
# ═══════════════════════════════════════════════════════════════

def retirement_corpus_needed(
    desired_monthly: float,
    retire_age: int,
    life_expectancy: int,
    inflation: float = 0.03,
    return_rate: float = 0.04,
):
    """
    计算退休时至少需要多少本金。

    假设退休后每年提取所需生活费（扣除通胀），本金按 return_rate 持续增值。

    Args:
        desired_monthly: 退休后每月期望生活费（今天币值，元）
        retire_age: 退休年龄
        life_expectancy: 预期寿命
        inflation: 年均通胀率，默认 3%
        return_rate: 退休后投资年化收益率，默认 4%

    返回:
        {
            "corpus_needed": 退休时所需总本金,
            "years_in_retirement": 退休年限,
            "desired_monthly_today": 当前期望月支出（回显）,
            "first_year_monthly": 退休首年月支出（通胀调整后）,
            "safe_withdrawal_rate": 建议提取率,
        }
    """
    years = life_expectancy - retire_age
    if years <= 0:
        return {
            "corpus_needed": 0,
            "years_in_retirement": 0,
            "desired_monthly_today": desired_monthly,
            "first_year_monthly": 0,
            "safe_withdrawal_rate": return_rate,
            "error": "退休年龄大于等于预期寿命，无需规划退休金",
        }

    # 退休首年月支出（通胀调整）
    years_to_retire = retire_age - 0  # 简化：假设调用时隐含当前年龄
    # 注意：此函数独立使用，不依赖 current_age。调用方应传入已折算过的 desired_monthly
    # 这里保留 simplicity：直接使用 desired_monthly 作为退休首月支出
    # 如需通胀调整，由 retirement_gap 处理

    annual_expense = desired_monthly * 12

    # 退休金总需求：假设每年提取，本金按 return_rate 增值
    # 简化计算：使用永续年金公式（保守）或等额提取公式
    # PV = PMT * (1 - (1+g)^n * (1+r)^(-n)) / (r - g)
    # 其中 g = inflation, r = return_rate
    r_real = (1 + return_rate) / (1 + inflation) - 1  # 实际收益率

    if r_real == 0:
        corpus = annual_expense * years
    else:
        # 每年提取额随通胀增长
        corpus = annual_expense * (1 - (1 + inflation) ** years * (1 + return_rate) ** (-years)) / r_real

    # 安全提取率建议（4% 规则为基准，根据退休年限调整）
    if years >= 30:
        swr = 0.04
    elif years >= 20:
        swr = 0.045
    else:
        swr = 0.05

    return {
        "corpus_needed": _r(corpus),
        "years_in_retirement": years,
        "desired_monthly_today": desired_monthly,
        "first_year_monthly": desired_monthly,  # 简化：未做通胀前推
        "first_year_annual": _r(annual_expense),
        "safe_withdrawal_rate": swr,
    }


def retirement_gap(
    current_age: int,
    retire_age: int,
    life_expectancy: int,
    current_savings: float,
    desired_monthly: float,
    inflation: float = 0.03,
    return_rate: float = 0.05,
):
    """
    退休缺口分析：现有储蓄够不够退休？还差多少？每月需要补存多少？

    Args:
        current_age: 当前年龄
        retire_age: 目标退休年龄
        life_expectancy: 预期寿命
        current_savings: 现有可用于退休的储蓄（元）
        desired_monthly: 退休后每月期望生活支出（今天币值，元）
        inflation: 年均通胀率，默认 3%
        return_rate: 退休前投资年化收益率，默认 5%

    返回:
        {
            "years_to_retire": 距离退休年数,
            "needed_corpus": 退休时所需本金,
            "projected_corpus": 现有储蓄按 return_rate 增长后的终值,
            "corpus_gap": 缺口（正值=不足，负值=有余）,
            "monthly_savings_needed": 填补缺口每月需追加储蓄,
            "summary": 一句话总结,
        }
    """
    years_to_retire = retire_age - current_age
    if years_to_retire <= 0:
        years_to_retire = 0

    # 退休首年期望月支出（通胀调整）
    first_year_monthly = desired_monthly * (1 + inflation) ** years_to_retire

    # 退休时所需本金
    corpus_result = retirement_corpus_needed(
        desired_monthly=first_year_monthly,
        retire_age=retire_age,
        life_expectancy=life_expectancy,
        inflation=inflation,
        return_rate=0.04,  # 退休后保守收益率
    )
    needed_corpus = corpus_result["corpus_needed"]

    # 现有储蓄的终值
    projected_corpus = current_savings * (1 + return_rate) ** years_to_retire

    gap = needed_corpus - projected_corpus

    # 填补缺口每月需储蓄（退休前定投）
    if gap > 0 and years_to_retire > 0:
        monthly_needed = pmt(target=gap, rate=return_rate, years=years_to_retire)["monthly_contribution"]
    elif gap > 0 and years_to_retire == 0:
        monthly_needed = gap  # 已到退休年龄，缺口需一次性补足
    else:
        monthly_needed = 0

    summary = (
        f"距离退休还有 {years_to_retire} 年，"
        f"退休时需 {_fmt_cny(needed_corpus)}，"
        f"现有储蓄预计增长至 {_fmt_cny(projected_corpus)}，"
        f"{f'缺口 {_fmt_cny(gap)}，每月需补存 {_fmt_cny(monthly_needed)}' if gap > 0 else '储蓄充足。'}"
    )

    return {
        "years_to_retire": years_to_retire,
        "needed_corpus": _r(needed_corpus),
        "projected_corpus": _r(projected_corpus),
        "corpus_gap": _r(gap),
        "monthly_savings_needed": _r(monthly_needed),
        "summary": summary,
    }


# ═══════════════════════════════════════════════════════════════
# 3. 保险保额估算
# ═══════════════════════════════════════════════════════════════

def insurance_coverage(
    annual_income: float,
    dependents: int = 0,
    debt: float = 0,
    existing_coverage: float = 0,
):
    """
    寿险/意外险保额估算（收入倍数法 + 负债覆盖 + 抚养年限）。

    Args:
        annual_income: 年收入（元）
        dependents: 抚养人数（子女+需赡养父母）
        debt: 负债总额（房贷、车贷等，元）
        existing_coverage: 已有保额（元），默认 0

    返回:
        {
            "recommended_coverage": 建议保额,
            "income_multiplier": 收入倍数（5-10年）,
            "debt_coverage": 负债覆盖部分,
            "dependent_support": 抚养费部分,
            "existing_coverage": 已有保额（回显）,
            "gap": 缺口（正值=不足）,
        }
    """
    # 收入倍数法：5-10 年年收入
    income_based = annual_income * 5  # 保守取 5 倍

    # 抚养费：按每人 10 万元/年 × 5 年估算
    dependent_support = dependents * 100000 * 5

    # 总建议保额
    recommended = income_based + debt + dependent_support

    gap = max(0, recommended - existing_coverage)

    return {
        "recommended_coverage": _r(recommended),
        "income_based": _r(income_based),
        "debt_coverage": _r(debt),
        "dependent_support": _r(dependent_support),
        "existing_coverage": existing_coverage,
        "gap": _r(gap),
        "income_multiplier": 5,
    }


# ═══════════════════════════════════════════════════════════════
# 4. 税务计算
# ═══════════════════════════════════════════════════════════════

# 综合所得年度累进税率表（《个人所得税法》附表一）
_TAX_BRACKETS = [
    (0,       36000,   0.03, 0),
    (36000,   144000,  0.10, 2520),
    (144000,  300000,  0.20, 16920),
    (300000,  420000,  0.25, 31920),
    (420000,  660000,  0.30, 52920),
    (660000,  960000,  0.35, 85920),
    (960000,  float("inf"), 0.45, 181920),
]

# 住房租金扣除标准（元/月）
_RENT_DEDUCTION = {
    "北京": 1500, "上海": 1500, "广州": 1500, "深圳": 1500,
    "天津": 1500, "重庆": 1500,
    # 各省会及计划单列市默认 1500
    # 人口 > 100 万城市默认 1100
    # 其他 800
    "default_large": 1100,
    "default_small": 800,
}

# 直辖市和计划单列市列表
_TIER1_CITIES = {
    "北京", "上海", "广州", "深圳", "天津", "重庆",
    "杭州", "南京", "武汉", "成都", "西安", "郑州",
    "大连", "青岛", "宁波", "厦门", "沈阳", "长沙",
    "济南", "哈尔滨", "长春", "合肥", "南昌", "昆明",
    "贵阳", "南宁", "呼和浩特", "太原", "石家庄", "乌鲁木齐",
    "兰州", "银川", "西宁", "海口", "拉萨", "福州",
}


def tax_bracket(annual_taxable_income: float):
    """
    查询税率档位。

    Args:
        annual_taxable_income: 年度应纳税所得额（已扣除各项）

    返回:
        {
            "bracket": 档位序号（1-7）,
            "rate": 适用税率,
            "quick_deduction": 速算扣除数,
            "marginal_rate": 边际税率,
        }
    """
    for i, (lo, hi, rate, qd) in enumerate(_TAX_BRACKETS):
        if lo <= annual_taxable_income < hi:
            return {
                "bracket": i + 1,
                "rate": rate,
                "quick_deduction": qd,
                "marginal_rate": rate,
            }
    # fallback（超过最高档）
    return {
        "bracket": 7,
        "rate": 0.45,
        "quick_deduction": 181920,
        "marginal_rate": 0.45,
    }


def income_tax(
    annual_income: float,
    city: str = "北京",
    deductions: Optional[dict] = None,
):
    """
    年度个人所得税计算（综合所得，含专项附加扣除）。

    Args:
        annual_income: 年度总收入（工资薪金 + 劳务等综合所得，元）
        city: 所在城市（用于住房租金扣除标准判断）
        deductions: 专项附加扣除配置，dict 可选字段：
            children: int         子女教育 + 婴幼儿照护数量
            continuing_edu: bool  是否继续教育（学历/职业资格）
            medical: float        大病医疗自付金额（元）
            housing_loan: bool    是否有首套住房贷款利息
            housing_rent: bool    是否租房
            elderly: int          赡养老人数量（独生子女填 1，非独生填分摊数量）
            social_insurance: float 三险一金全年总额（可选，默认按基数估算）

    返回:
        {
            "annual_income": 年收入（回显）,
            "taxable_income": 应纳税所得额,
            "tax": 应纳税额,
            "effective_rate": 有效税率,
            "marginal_rate": 边际税率,
            "deductions_detail": 各项扣除明细,
        }
    """
    if deductions is None:
        deductions = {}

    # ── 各项扣除计算 ──
    detail = {}

    # 基本减除：60,000 元/年
    basic_deduction = 60000
    detail["基本减除"] = basic_deduction

    # 三险一金
    social_insurance = deductions.get("social_insurance", 0)
    if social_insurance == 0:
        # 估算：按收入 22.5%（养老8%+医疗2%+失业0.5%+公积金12%），上限按社平工资3倍
        social_insurance = min(annual_income * 0.225, 300000 * 0.225)
    detail["三险一金(估)"] = _r(social_insurance)

    # 子女教育 + 婴幼儿照护：2,000元/月/人
    children_count = deductions.get("children", 0)
    children_deduction = children_count * 2000 * 12
    if children_deduction > 0:
        detail["子女教育/婴幼儿照护"] = _r(children_deduction)

    # 继续教育
    continuing_edu = 0
    if deductions.get("continuing_edu"):
        continuing_edu = 4800  # 400/月 × 12，简化版
        detail["继续教育"] = _r(continuing_edu)

    # 大病医疗（限额 80,000 元/年）
    medical = min(deductions.get("medical", 0), 80000)
    if medical > 0:
        detail["大病医疗"] = _r(medical)

    # 住房贷款利息：1,000元/月
    housing_loan = 0
    if deductions.get("housing_loan"):
        housing_loan = 1000 * 12
        detail["住房贷款利息"] = _r(housing_loan)

    # 住房租金：按城市分档
    housing_rent = 0
    if deductions.get("housing_rent"):
        if city in _TIER1_CITIES:
            housing_rent = 1500 * 12
        else:
            housing_rent = 1100 * 12  # 默认大城市档
        detail["住房租金"] = _r(housing_rent)

    # 赡养老人：3,000元/月（独生子女），非独生 ≤ 1,500/人
    elderly = deductions.get("elderly", 0)
    # elderly 填的是分摊人数，简化：如果填了 1，按独生子女 3000；如果 >1，按每人 1500
    if elderly == 1:
        elderly_deduction = 3000 * 12
    elif elderly > 1:
        elderly_deduction = min(elderly, 2) * 1500 * 12  # 每人最多 1500
    else:
        elderly_deduction = 0
    if elderly_deduction > 0:
        detail["赡养老人"] = _r(elderly_deduction)

    # ── 应纳税所得额 ──
    total_deductions = (
        basic_deduction + social_insurance
        + children_deduction + continuing_edu + medical
        + housing_loan + housing_rent + elderly_deduction
    )
    taxable_income = max(0, annual_income - total_deductions)

    # ── 计算税额 ──
    bracket_info = tax_bracket(taxable_income)
    tax = taxable_income * bracket_info["rate"] - bracket_info["quick_deduction"]
    tax = max(0, tax)

    effective_rate = tax / annual_income if annual_income > 0 else 0

    return {
        "annual_income": _r(annual_income),
        "taxable_income": _r(taxable_income),
        "tax": _r(tax),
        "effective_rate": round(effective_rate, 4),
        "marginal_rate": bracket_info["rate"],
        "deductions_detail": detail,
    }


# ═══════════════════════════════════════════════════════════════
# 5. 资产配置
# ═══════════════════════════════════════════════════════════════

def four_account_allocation(monthly_income: float):
    """
    四账户模型：将月收入分配到四个账户。

    「标准普尔家庭资产配置象限」变体：
      1. 应急账户：3-6 个月生活支出，放活期/货币基金
      2. 保障账户：保险费用，年收入的 10%-20%
      3. 保本增值账户：债券/存款/养老金，长期增值，稳定
      4. 高收益账户：股票/基金，追求更高收益

    Args:
        monthly_income: 税后月收入（元）

    返回:
        {
            "monthly_income": 月收入（回显）,
            "accounts": {
                "emergency":    {"ratio": 0.10, "monthly": ..., "annual": ..., "note": "应急金"},
                "insurance":    {"ratio": 0.15, "monthly": ..., "annual": ..., "note": "保障"},
                "stable":       {"ratio": 0.40, "monthly": ..., "annual": ..., "note": "保本增值"},
                "growth":       {"ratio": 0.35, "monthly": ..., "annual": ..., "note": "高收益"},
            },
            "summary": 一句话说明,
        }
    """
    accts = {
        "emergency":  {"ratio": 0.10, "note": "应急金：货币基金/活期存款，目标积累3-6个月生活费"},
        "insurance":  {"ratio": 0.15, "note": "保障：重疾险/医疗险/寿险/意外险"},
        "stable":     {"ratio": 0.40, "note": "保本增值：债券/大额存单/养老金"},
        "growth":     {"ratio": 0.35, "note": "高收益：指数基金/股票"},
    }

    for key in accts:
        accts[key]["monthly"] = _r(monthly_income * accts[key]["ratio"])
        accts[key]["annual"] = _r(accts[key]["monthly"] * 12)

    return {
        "monthly_income": monthly_income,
        "accounts": accts,
        "summary": f"月收入 {_fmt_cny(monthly_income)} 按四账户分配："
                   f"应急 {_fmt_cny(accts['emergency']['monthly'])}/月 + "
                   f"保障 {_fmt_cny(accts['insurance']['monthly'])}/月 + "
                   f"保本增值 {_fmt_cny(accts['stable']['monthly'])}/月 + "
                   f"高收益 {_fmt_cny(accts['growth']['monthly'])}/月",
    }


def allocation_drift(current_alloc: dict, target_alloc: dict):
    """
    资产配置偏离度分析：当前持仓 vs 目标配置，给出调仓方向和金额。

    Args:
        current_alloc: 当前各资产占比和市值，如 {"股票": {"ratio": 0.45, "amount": 225000}, ...}
        target_alloc:  目标各资产占比，如 {"股票": 0.40, "债券": 0.40, "现金": 0.20}

    返回:
        {
            "total_amount": 总市值,
            "drifts": {
                "asset_name": {
                    "current_ratio": ...,
                    "target_ratio": ...,
                    "current_amount": ...,
                    "target_amount": ...,
                    "drift_ratio": 偏离度（正=超配，负=低配）,
                    "adjust_amount": 调整金额（正=需卖出，负=需买入）,
                    "action": "sell"/"buy"/"hold",
                },
                ...
            },
            "max_drift": 最大偏离度,
            "summary": 调仓建议一句话,
        }
    """
    total_amount = sum(item.get("amount", 0) for item in current_alloc.values()) if current_alloc else 0

    if total_amount == 0:
        return {
            "total_amount": 0,
            "drifts": {},
            "max_drift": 0,
            "summary": "当前无持仓，无需调整",
        }

    drifts = {}
    max_drift = 0
    actions = []

    for asset_name, target_ratio in target_alloc.items():
        current = current_alloc.get(asset_name, {"ratio": 0, "amount": 0})
        current_ratio = current.get("ratio", 0)
        current_amount = current.get("amount", 0)
        target_amount = total_amount * target_ratio

        drift_ratio = round(current_ratio - target_ratio, 4)
        adjust_amount = current_amount - target_amount  # 正=超配需卖出，负=低配需买入

        if abs(drift_ratio) > 0.05:  # 偏离超过 5% 才建议调整
            if adjust_amount > 0:
                action = "sell"
                actions.append(f"{asset_name}超配，建议卖出 {_fmt_cny(adjust_amount)}")
            else:
                action = "buy"
                actions.append(f"{asset_name}低配，建议买入 {_fmt_cny(abs(adjust_amount))}")
        else:
            action = "hold"

        drifts[asset_name] = {
            "current_ratio": current_ratio,
            "target_ratio": target_ratio,
            "current_amount": current_amount,
            "target_amount": _r(target_amount),
            "drift_ratio": drift_ratio,
            "adjust_amount": _r(adjust_amount),
            "action": action,
        }

        max_drift = max(max_drift, abs(drift_ratio))

    summary = "；".join(actions) if actions else "当前配置与目标基本一致，无需调整"

    return {
        "total_amount": _r(total_amount),
        "drifts": drifts,
        "max_drift": round(max_drift, 4),
        "summary": summary,
    }


def simple_portfolio(
    amount: float,
    goal_return: float,
    timeline: int,
    risk_tolerance: str = "medium",
):
    """
    精简仓位规划：用户给出一笔资金、目标收益和投资期限，直接输出仓位分配建议。

    基于经验规则（不构成投资建议）：
      - low:    80%债券 + 20%股票（保守型）
      - medium: 50%债券 + 50%股票（平衡型）
      - high:   20%债券 + 80%股票（进取型）

    Args:
        amount: 投入本金（元）
        goal_return: 期望年化收益率（如 0.06 表示 6%）
        timeline: 投资期限（年）
        risk_tolerance: low / medium / high

    返回:
        {
            "amount": 本金（回显）,
            "goal_return": 目标年化收益率（回显）,
            "timeline": 投资期限（回显）,
            "risk_tolerance": 风险等级（回显）,
            "allocation": {
                "bond":  {"ratio": ..., "amount": ..., "expected_return": ...},
                "stock":  {"ratio": ..., "amount": ..., "expected_return": ...},
            },
            "expected_annual_return": 预期组合年化收益率,
            "expected_final_value": 预期最终金额,
            "feasibility": "likely" / "stretch" / "aggressive",
            "summary": 一句话说明,
        }
    """
    # 资产配置比例映射
    allocations = {
        "low":    {"stock": 0.20, "bond": 0.80},
        "medium": {"stock": 0.50, "bond": 0.50},
        "high":   {"stock": 0.80, "bond": 0.20},
    }
    alloc = allocations.get(risk_tolerance, allocations["medium"])

    # 假设长期年化收益（经验值，非预测）
    stock_return = 0.08   # 股票预期 8%
    bond_return = 0.035   # 债券预期 3.5%

    expected_return = alloc["stock"] * stock_return + alloc["bond"] * bond_return
    expected_final = amount * (1 + expected_return) ** timeline

    # 可行性判断
    if goal_return <= expected_return * 0.8:
        feasibility = "likely"
    elif goal_return <= expected_return:
        feasibility = "stretch"
    else:
        feasibility = "aggressive"

    bond_alloc = {
        "ratio": alloc["bond"],
        "amount": _r(amount * alloc["bond"]),
        "expected_return": bond_return,
    }
    stock_alloc = {
        "ratio": alloc["stock"],
        "amount": _r(amount * alloc["stock"]),
        "expected_return": stock_return,
    }

    summary = (
        f"{risk_tolerance_map(risk_tolerance)}，"
        f"建议 {alloc['bond']*100:.0f}% 债券 + {alloc['stock']*100:.0f}% 股票，"
        f"预期组合年化 {expected_return*100:.1f}%，"
        f"{timeline} 年后预计 {_fmt_cny(expected_final)}。"
        f"实现目标年化 {goal_return*100:.1f}% {'可能性较高' if feasibility == 'likely' else '有一定挑战' if feasibility == 'stretch' else '偏激进'}。"
    )

    return {
        "amount": amount,
        "goal_return": goal_return,
        "timeline": timeline,
        "risk_tolerance": risk_tolerance,
        "allocation": {"bond": bond_alloc, "stock": stock_alloc},
        "expected_annual_return": round(expected_return, 4),
        "expected_final_value": _r(expected_final),
        "feasibility": feasibility,
        "summary": summary,
    }


def risk_tolerance_map(level: str) -> str:
    mapping = {"low": "保守型", "medium": "平衡型", "high": "进取型"}
    return mapping.get(level, "平衡型")


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== 复利：终值 ===")
    print(fv(pv=200000, rate=0.04, years=10))

    print("\n=== 复利：现值 ===")
    print(pv(fv=500000, rate=0.04, years=15))

    print("\n=== 复利：定投 ===")
    print(pmt(target=1000000, rate=0.05, years=20))

    print("\n=== 退休缺口 ===")
    print(retirement_gap(30, 60, 85, 500000, 10000))

    print("\n=== 保险保额 ===")
    print(insurance_coverage(annual_income=200000, dependents=2, debt=800000))

    print("\n=== 个税计算 ===")
    print(income_tax(annual_income=300000, city="北京", deductions={"children": 1, "housing_rent": True}))

    print("\n=== 税率档位 ===")
    print(tax_bracket(150000))

    print("\n=== 四账户配置 ===")
    print(four_account_allocation(monthly_income=20000))

    print("\n=== 偏离度分析 ===")
    print(allocation_drift(
        current_alloc={
            "股票": {"ratio": 0.55, "amount": 275000},
            "债券": {"ratio": 0.30, "amount": 150000},
            "现金": {"ratio": 0.15, "amount": 75000},
        },
        target_alloc={"股票": 0.40, "债券": 0.40, "现金": 0.20},
    ))

    print("\n=== 精简仓位规划 ===")
    print(simple_portfolio(amount=500000, goal_return=0.06, timeline=10, risk_tolerance="medium"))
