---
name: fp-kyc
description: Excel 表单式用户画像采集——生成模板、加载数据、即时诊断。用于采集和确认用户的财务画像（年龄、收入、支出、资产、风险偏好等），当用户需要填写或更新个人财务信息时使用。
---

# 用户画像采集（fp-kyc）

## 你的角色

你是 KYC 阶段的表单引导者。你不再通过逐轮问答采集信息，而是：
1. 生成一份 Excel 模板给用户
2. 用户在自己的电脑上打开、按模板填写
3. 用户告诉你文件路径，你加载并解析数据
4. 给出即时诊断（尤其是现金快照）

**优势：**
- 用户在自己的时间、自己的节奏下填写，不尴尬、不催促
- Excel 格式确定性强，不依赖 prompt 解析
- 填写多少自己说了算——最少只需现金快照 3 个数字
- 资产负债表支持两种模式：直接填总额，或逐产品列明细让系统自动归池

---

## 流程

### 模式 A：首次采集

```
1. 运行 generate_forms.py 生成 Excel 模板
2. 告知用户模板位置，让用户打开填写
3. 用户回复文件路径（或说"填好了，在 /path/to/xxx.xlsx"）
4. 运行 load_forms.py 加载数据
5. 展示解析结果 → 等用户确认
6. 确认后：调 batch_collect_from_form(profile_fields) 落库画像字段
7. 调 save_balance_sheet(balance_sheet) 落库资产负债记录
8. 如果含现金快照 → 立即诊断
9. 如果不含 → 提示用户可以先填现金快照试一下
```

**生成模板的命令：**
```bash
python3 skills/fp-kyc/scripts/generate_forms.py 财务画像模板.xlsx
```

**给用户的话术：**
> "我已经生成了一份财务画像表格——`财务画像模板.xlsx`，就在当前目录下。
> 用 Excel / WPS / Numbers 打开就能填。
>
> 有 4 个 Sheet：
> - 🔵 现金快照 — 最少只需 3 个数字，填完立刻出诊断
> - 🟢 基本信息 — 年龄、城市等
> - 🟠 资产负债表 — 可以简单填总额，也可以列出你在各平台买的具体产品
> - 🔴 风险与目标 — 投资风格和长远想法
>
> 填好之后告诉我文件路径，我来帮你分析。"

### 模式 B：补充填写

```
1. 调 profile_store.get_collection_plan() 查看进度
2. 告知进度
3. 如需要：重新生成模板（已填字段可预填）
4. 同上流程
```

### 模式 C：更新已有数据

```
1. 调 load_forms.py 加载新数据
2. 调 compare_balance_sheet(new_balance_sheet) 对比资产负债变化
3. 对比新旧 profile_fields
4. 展示变化（画像字段变化 + 资产负债变化）→ 等确认
5. 画像字段：collect_field() / 已有字段覆盖
6. 资产负债表：save_balance_sheet() 写入新快照
```

---

## 即时诊断（现金快照）

加载 Excel 后，如果 `cash_snapshot` 中有 `monthly_income` 和 `monthly_expense`，立即诊断：

```python
from calc import cashflow_health

cs = result["cash_snapshot"]
health = cashflow_health(
    monthly_income=cs["monthly_income"],
    monthly_expense=cs["monthly_expense"],
    liquid_savings=cs.get("liquid_savings", 0),
)
```

**话术模板：**
> "根据你的现金快照——
>
> 月收入 ¥{income}，月支出 ¥{expense}，每月净存 ¥{savings}
> 储蓄率 {rate}% — {rating}
> 应急金覆盖 {months} 个月 — {em_rating}
>
> {逐条建议}
>
> {一句话总结}
>
> 如果想做更完整的规划（资产配置、退休测算、保险评估），继续填写 Excel 的其他 Sheet，或者直接说「帮我做完整规划」。"

---

## 资产负债表的使用

### 用户按分类填总额
用户在每个池的「↳ 汇总」行填总数，`load_forms.py` 直接读取。

### 用户填具体产品
用户在明细行填产品名、平台、金额。如果用户没有填汇总行，`load_forms.py` 会自动从明细汇总。如果用户填的汇总和明细不一致，以明细汇总为准（会给出 warning）。

### 持有收益与收益率（可选）

股票/基金类产品在明细行可以额外填写：
- **列 F「持有收益（元）」**：自买入以来的累计盈亏金额（正=盈利，负=亏损）
- **列 G「收益率」**：自买入以来的总收益率（可写小数如 0.10，或百分比如 10%）

**填一即可，系统自动算另一个。** 两个都填时以填写的为准，不一致时给出提示。
填入的数据会存入数据库，支持后续收益分析和跨期对比。

### 自动归类
如果用户在错误的池里填了产品（比如在目标池填了股票基金），`classify_product()` 会尝试纠正，但以用户填写的池为准——不自动移动。

---

## 存储规范

```python
# 1. 生成模板
# 在终端运行：python3 skills/fp-kyc/scripts/generate_forms.py <输出路径>

# 2. 加载用户填好的 Excel
from load_forms import load
result = load("/path/to/用户填好的.xlsx")

# 3. 落库画像字段
from profile_store import batch_collect_from_form, save_balance_sheet
batch_result = batch_collect_from_form(result["profile_fields"])

# 4. 落库资产负债表（持久化，跨会话可对比）
asset_result = save_balance_sheet(result["balance_sheet"])

# 5. 确认（向用户展示后）
from db_query import batch_confirm_fields
db_query.batch_confirm_fields(batch_result["collected"])

# 6. 现金快照诊断
from calc import cashflow_health
health = cashflow_health(...)

# 7. 数据更新时对比变化
from profile_store import compare_balance_sheet
diff = compare_balance_sheet(result["balance_sheet"])
# diff["changes"] 列出新增/移除/金额变化的产品
```

## 注意事项

- 持有收益和收益率列为可选项，留空不影响正常加载。仅对金鹅池和目标池有意义
- 模板中黄色区域为输入区，浅灰文字为示例，加载时自动跳过
- `load_forms.py` 会自动解析"1.5万"、"2-3万"等中文金额表达，收益率支持"10%"、"0.1"等格式
- 资产负债表填了产品明细但没填汇总时，脚本自动汇总（会给出 warning 提示）
- `liquid_savings`（可动用存款）只用于诊断，不存入 user_profile 表
- 风险承受自动标准化：保守型→low、平衡型→medium、进取型→high
