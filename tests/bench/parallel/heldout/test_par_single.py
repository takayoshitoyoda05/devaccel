from datetime import date

import pytest

from kakeibo.core import Expense


def E(d, c, a, m=""):
    return Expense(date.fromisoformat(d), c, a, m)


def D(s):
    return date.fromisoformat(s)


def test_recurring():
    from kakeibo.recurring import Recurring, add_month, find_recurring
    assert add_month(D("2026-01-31")) == D("2026-02-28")
    assert add_month(D("2024-01-31")) == D("2024-02-29")
    assert add_month(D("2026-12-15")) == D("2027-01-15")
    rows = [E("2026-03-30", "rent", 80000), E("2026-01-31", "rent", 80000, "a"), E("2026-02-28", "rent", 80000),
            E("2026-04-30", "rent", 80000), E("2026-04-30", "rent", 80000, "dup"),
            E("2026-07-01", "rent", 80000), E("2026-08-01", "rent", 80000),
            E("2026-01-05", "sub", 990), E("2026-02-07", "sub", 990), E("2026-03-06", "sub", 990),
            E("2026-02-10", "sub", 1200),
            E("2026-01-01", "food", 500), E("2026-01-15", "food", 500), E("2026-02-01", "food", 500)]
    rent = Recurring("rent", 80000, (D("2026-01-31"), D("2026-02-28"), D("2026-03-30"), D("2026-04-30")),
                     D("2026-05-30"))
    sub = Recurring("sub", 990, (D("2026-01-05"), D("2026-02-07"), D("2026-03-06")), D("2026-04-06"))
    assert find_recurring(rows) == [rent, sub]
    rent2 = Recurring("rent", 80000, (D("2026-07-01"), D("2026-08-01")), D("2026-09-01"))
    assert find_recurring(rows, min_count=2) == [rent, rent2, sub]
    assert find_recurring(rows, tolerance=1) == []
    assert find_recurring([]) == []
    with pytest.raises(ValueError):
        find_recurring(rows, min_count=1)
    with pytest.raises(ValueError):
        find_recurring(rows, tolerance=-1)


