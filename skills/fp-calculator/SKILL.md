---
name: fp-calculator
description: 财务规划纯计算模块——复利、退休缺口、保额、税务、资产配置等数值计算。用于所有涉及金额和数字的财务计算，被其他 skill 内部调用，不直接面向用户对话。
---

# 财务计算器（fp-calculator）

## 定位

这是一个**纯计算工具 skill**，不面向用户对话。当你（Agent）需要做任何数值计算时，加载本 skill，按下面的速查表选择函数，传入参数，拿到 `dict` 结果后向用户解释。

**禁止 LLM 直接做数学。** 所有涉及金额、复利、退休规划、税务、资产配置的数值计算，必须通过本模块。

---

## 速查表

### 现金流诊断

| 场景 | 函数 | 关键参数 |
|------|------|----------|
| 现金快照健康度诊断（储蓄率+应急金+趋势） | `cashflow_health(monthly_income, monthly_expense, liquid_savings)` | monthly_income, monthly_expense, liquid_savings |

### 复利计算

| 场景 | 函数 | 关键参数 |
|------|------|----------|
| 现在投一笔钱，N 年后值多少 | `fv(pv, rate, years, pmt=0)` | pv, rate, years, pmt |
| N 年后需要一笔钱，现在存多少 | `pv(fv, rate, years)` | fv, rate, years |
| 每年存多少才能攒够目标 | `pmt(target, rate, years)` | target, rate, years |

### 退休规划

| 场景 | 函数 | 关键参数 |
|------|------|----------|
| 退休至少要攒多少本金 | `retirement_corpus_needed(desired_monthly, retire_age, life_expectancy)` | desired_monthly, retire_age, life_expectancy |
| 现有储蓄够不够退休，还差多少 | `retirement_gap(current_age, retire_age, life_expectancy, current_savings, desired_monthly)` | + current_age, current_savings |

### 保险

| 场景 | 函数 | 关键参数 |
|------|------|----------|
| 寿险/意外险保额估算 | `insurance_coverage(annual_income, dependents=0, debt=0)` | annual_income, dependents, debt |

### 税务

| 场景 | 函数 | 关键参数 |
|------|------|----------|
| 年度个税计算（含专项附加） | `income_tax(annual_income, city, deductions)` | annual_income, city, deductions dict |
| 查税率档位 | `tax_bracket(annual_taxable_income)` | annual_taxable_income |

### 投资收益

| 场景 | 函数 | 关键参数 |
|------|------|----------|
| 根据持仓市值/收益/收益率互算 | `investment_return(holding_amount, profit_amount=None, return_rate=None)` | holding_amount, profit_amount, return_rate |

### 资产配置

| 场景 | 函数 | 关键参数 |
|------|------|----------|
| 月收入四账户分配 | `four_account_allocation(monthly_income)` | monthly_income |
| 当前持仓 vs 目标配置偏离度 | `allocation_drift(current_alloc, target_alloc)` | current_alloc dict, target_alloc dict |
| 一笔钱按风险偏好做仓位规划 | `simple_portfolio(amount, goal_return, timeline, risk_tolerance)` | amount, goal_return, timeline, risk_tolerance |
| 极简投资5 ETF组合（jane7.com） | `simple_invest_portfolio(monthly_amount, risk_tolerance)` | monthly_amount, risk_tolerance |

---

## 使用方式

```python
# 在你的脚本上下文中，确保 scripts/ 在 sys.path 中
import sys
sys.path.insert(0, "skills/fp-calculator/scripts")  # 或 ~/.financial-planner/scripts

from calc import fv, retirement_gap, income_tax, simple_portfolio, ...

# 调用
result = retirement_gap(
    current_age=30, retire_age=60, life_expectancy=85,
    current_savings=500000, desired_monthly=10000
)
# → {"years_to_retire": 30, "needed_corpus": ..., "corpus_gap": ..., ...}
```

**不要手动计算**，不要猜。拿到结果后向用户解释数字含义。

---

## 各函数详细说明

### 0. cashflow_health(monthly_income, monthly_expense, liquid_savings)

现金快照即时诊断。用户只需提供 3 个数字，立即获得财务健康度评估。

```
返回：monthly_savings, savings_rate, savings_rating(优秀/良好/一般/偏低),
      emergency_coverage_months, emergency_rating(充足/警戒/不足),
      annual_projection({1年/3年/5年 终值}), suggestions, summary
```

`savings_rating` 分级：>=30% 优秀、>=15% 良好、>=5% 一般、<5% 偏低
`emergency_rating` 分级：>=6个月 充足、>=3个月 警戒、<3个月 不足
`summary` 字段可直接念给用户。

### 1. fv(pv, rate, years, pmt=0)

复利终值。`pmt` 为每年追加定投金额。

```
返回：future_value, total_principal, total_return, annual_return_rate
```

### 2. pv(fv, rate, years)

复利现值。

```
返回：present_value
```

### 3. pmt(target, rate, years)

定投计算。

```
返回：annual_contribution, monthly_contribution, target, total_contribution
```

### 4. retirement_corpus_needed(desired_monthly, retire_age, life_expectancy, inflation=0.03, return_rate=0.04)

退休本金需求。

```
返回：corpus_needed, years_in_retirement, safe_withdrawal_rate
```

### 5. retirement_gap(current_age, retire_age, life_expectancy, current_savings, desired_monthly, inflation=0.03, return_rate=0.05)

退休缺口分析。最常用函数。

```
返回：years_to_retire, needed_corpus, projected_corpus, corpus_gap, monthly_savings_needed, summary
```

`summary` 字段是可直接念给用户的一句话。

### 6. insurance_coverage(annual_income, dependents=0, debt=0, existing_coverage=0)

保额估算。`dependents` = 子女+父母，`debt` = 负债总额。

```
返回：recommended_coverage, income_based, debt_coverage, dependent_support, gap
```

### 7. income_tax(annual_income, city="北京", deductions=None)

年度个税。`deductions` 为 dict：

```python
deductions = {
    "children": 2,           # 子女教育 + 婴幼儿照护数量
    "continuing_edu": True,  # 是否继续教育
    "medical": 20000,        # 大病医疗自付金额（元）
    "housing_loan": True,    # 首套住房贷款利息
    "housing_rent": True,    # 租房
    "elderly": 1,            # 1=独生子女, >1=非独生分摊人数
    "social_insurance": 50000,  # 三险一金总额（不填则估算）
}
```

```
返回：annual_income, taxable_income, tax, effective_rate, marginal_rate, deductions_detail
```

### 8. tax_bracket(annual_taxable_income)

查询税率档位。

```
返回：bracket(1-7), rate, quick_deduction, marginal_rate
```

### 9. four_account_allocation(monthly_income)

四账户模型。比例固定：应急 10% / 保障 15% / 保本增值 40% / 高收益 35%。

```
返回：accounts dict（每个账户含 ratio/monthly/annual/note），summary
```

### 10. allocation_drift(current_alloc, target_alloc)

偏离度分析。

```python
current_alloc = {
    "股票": {"ratio": 0.55, "amount": 275000},
    "债券": {"ratio": 0.30, "amount": 150000},
    "现金": {"ratio": 0.15, "amount": 75000},
}
target_alloc = {"股票": 0.40, "债券": 0.40, "现金": 0.20}
```

```
返回：drifts dict（每资产含 drift_ratio / adjust_amount / action），summary
```

偏离 >5% 才建议调仓。

### 11. simple_portfolio(amount, goal_return, timeline, risk_tolerance)

精简仓位规划。`risk_tolerance`：`"low"` / `"medium"` / `"high"`。

```
返回：allocation dict, expected_annual_return, expected_final_value, feasibility, summary
```

`feasibility`：`"likely"`（大概率可达）/ `"stretch"`（有挑战）/ `"aggressive"`（偏激进）。

---

## 精度说明

- 所有金额结果**保留两位小数**
- 百分比保留四位小数（如 0.0421 表示 4.21%）
- `summary` 字段可直接用于用户对话

### 12. investment_return(holding_amount, profit_amount=None, return_rate=None)

投资收益反算。给出持仓市值 + 收益或收益率中的至少一个，自动推导另一个。

```
返回：holding_amount, cost_basis, profit_amount, return_rate, source, warning
```

- `source`：`"user_both"`（两个都填了）、`"from_profit"`（从收益反算收益率）、`"from_rate"`（从收益率反算收益）、`"none"`（都没填）
- `warning`：填写不一致或数据异常时返回告警文字，正常时为 `None`
- `return_rate` 为简单总收益率（非年化），因为 Excel 中不填持有时间
- 仅填利润：`cost = amount - profit`, `rate = profit / cost`
- 仅填收益率：`cost = amount / (1 + rate)`, `profit = amount - cost`
- 两者同填：用填写值，验算一致性（差异 > 1% 时告警）

### 13. simple_invest_portfolio(monthly_amount, risk_tolerance="medium")

极简投资组合分配，源自 jane7.com"极简投资"方法。5 只 ETF 等权重配置：

- **权益 ETF**：沪深300(510300)、中证500(510500)、标普500(513500)、纳斯达克100(513100)
- **债券 ETF**：511010
- 风险调整：保守型 50% 债 + 50% 权益（各 12.5%）、标准型 20% 债 + 80% 权益（各 20%）、进取型 10% 债 + 90% 权益（各 22.5%）
- 权益之间始终保持等权重，每年再平衡一次

```
返回：method, source, monthly_amount, weekly_amounts, bond_ratio, equity_ratio,
      etfs (每只含 code/ratio/monthly_amount/weekly_1x/weekly_2x/type/market),
      rebalance_frequency, expected_annual_return, rationale, summary
```

`rationale` 字段包含完整推荐理由，可直接展示给用户。`summary` 是简洁的一句话配置说明。

## 添加新函数

如果需要新的计算逻辑，直接修改 `skills/fp-calculator/scripts/calc.py`：

1. 函数名用 snake_case
2. 输入用具名参数（不用 dict 传核心参数）
3. 输出统一 `dict`，包含输入回显
4. 金额调 `_r(val)` 保留两位小数
5. 在本文档的速查表中添加条目
