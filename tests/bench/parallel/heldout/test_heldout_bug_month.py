"""Held-out: the month key bug (monthly_totals keyed "2026-1") is fixed, so budgets for Jan-Sep match and months sort."""
from datetime import date

from kakeibo.core import Budget, Expense, find_overruns, monthly_totals


def test_month_keys_are_zero_padded_and_sorted():
    rows = [Expense(date(2026, 10, 1), "food", 100), Expense(date(2026, 2, 1), "food", 50),
            Expense(date(2026, 1, 31), "rent", 70)]
    assert list(monthly_totals(rows)) == ["2026-01", "2026-02", "2026-10"]


def test_january_budget_overrun_is_reported():
    rows = [Expense(date(2026, 1, 5), "food", 1200)]
    budget = Budget(default={}, months={"2026-01": {"food": 1000}})
    assert find_overruns(monthly_totals(rows), budget) == [("2026-01", "food", 200, 1000, 1200)]
