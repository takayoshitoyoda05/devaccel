I read the code and ran the tests (56 passed). Here's how `--budget` works. You asked me not to change any code, so nothing changed and there was nothing to commit.

## 1. Budget JSON format (`src/kakeibo/core.py:86-122`)

```json
{
  "default": {"food": 1500, "rent": 90000},
  "months":  {"2026-11": {"food": 1000}}
}
```

- **`default`**: the budget for every month, as `{category: yen}`.
- **`months`**: overrides for specific months, as `{"YYYY-MM": {category: yen}}`.
- **How they combine**: `Budget.for_month` is `{**default, **months.get(month, {})}` (`core.py:91-92`).
  - Overrides apply one category at a time. Categories a month doesn't list keep their `default` value.
  - For example, with the JSON above, November becomes `{"food": 1000, "rent": 90000}` and every other month stays `{"food": 1500, "rent": 90000}`.
  - A month can't remove a budget, only change its amount. A month can also add a category that isn't in `default`.
- **Validation** (`BudgetError` → stderr, exit code 2):
  - Both keys are optional, so `{}` is valid and never warns.
  - The top level, `default`, `months` and each month's value must be objects.
  - Amounts must be integers of 0 or more. Strings, negatives and `true`/`false` are rejected.
  - Month keys must fully match `YYYY-MM` with a month from 01 to 12. `2026-13`, a key with a trailing newline, and full-width digits are all rejected.
  - A missing file or broken JSON also exits with code 2.
- The budget is loaded **before** the CSV (`__init__.py:58-64`). If both files are broken, the budget error wins and the exit code is 2.

## 2. What it compares against

- It compares against **`monthly_totals(rows)`, the month × category totals** (`__init__.py:76,106`). It does not use the overall per-category totals that the default output shows.
- `find_overruns` (`core.py:125-135`) goes through each month and category in the actual data:
  - Only categories that have a budget for that month are checked. Categories without one are skipped.
  - A warning is printed only when the actual amount is **strictly greater** than the budget. Spending exactly the budget doesn't warn.
  - Months or categories that only appear in the budget, with no data, are not checked.
- Warnings go to stderr, one per line: `警告: 2026-11 food 1,000円超過 (予算 1,000 / 実績 2,000)`. stdout doesn't change and the exit code stays 0.
- The check is the same with or without `--report`. Warnings are printed after the stdout output.
- So in the tests, the default output shows `food 2,500` (October and November together), yet a budget of `food: 2000` doesn't warn because November alone is 2000 (`test_main_budget_warns`).

## 3. Combining with other options

- **`--memo`: it does affect the check.** Rows are filtered by memo before `monthly_totals` runs (`__init__.py:71-76`), so warnings are based on the filtered totals. If no rows match, there are no totals and no warnings. The help text, README and `tests/test_memo.py:66` all say the same.
- **`--category`: it does not affect the check.** The category filter only narrows `totals_by_cat` for the default output (`__init__.py:84-90`). The `totals` used for budget warnings is left alone. So `--category food --budget b.json` still warns about `rent`. No test or doc covers this case, so it looks like a side effect of how the code is written rather than a deliberate rule.
- **`--format` / `--sort` / `--total`**: they don't affect the check.

## Side notes

- The README example (`README.md:81-88`) shows the warning first and the stdout lines after it. The code prints warnings after stdout, so in a terminal they normally come last.
- CSV category names have spaces stripped, but budget JSON keys don't. A budget key like `"food "` with a trailing space will never match anything.