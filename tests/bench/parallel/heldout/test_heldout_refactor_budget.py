"""Held-out: the budget code moved to kakeibo.budget, old imports from kakeibo.core still work, same behaviour."""
from datetime import date

import kakeibo.budget as b
import kakeibo.core as c


def test_new_module_has_the_budget_api():
    for name in ("Budget", "BudgetError", "load_budget", "find_overruns"):
        assert hasattr(b, name), name


def test_old_imports_still_work_and_are_the_same_objects():
    assert c.Budget is b.Budget and c.load_budget is b.load_budget
    assert c.find_overruns is b.find_overruns and c.BudgetError is b.BudgetError


def test_behaviour_unchanged():
    rows = [c.Expense(date(2026, 3, 1), "food", 1500)]
    budget = b.Budget(default={"food": 1000}, months={})
    assert b.find_overruns(c.monthly_totals(rows), budget) == [("2026-03", "food", 500, 1000, 1500)]
