import json
from datetime import date

from kakeibo.core import Expense


def E(d, c, a, m=""):
    return Expense(date.fromisoformat(d), c, a, m)


def test_median():
    from kakeibo.stats import median_by_category
    rows = [E("2026-11-01", "food", 100), E("2026-11-02", "food", 300), E("2026-11-03", "rent", 5),
            E("2026-11-04", "food", 200), E("2026-11-05", "book", 10), E("2026-11-06", "book", 20)]
    assert median_by_category(rows) == {"book": 15.0, "food": 200.0, "rent": 5.0}
    assert list(median_by_category(rows)) == ["book", "food", "rent"]
    assert median_by_category([]) == {}


def test_export():
    from kakeibo.export import to_json
    s = to_json([E("2026-11-01", "食費", 1200, "昼"), E("2026-11-02", "rent", 80000)])
    assert s == json.dumps([{"date": "2026-11-01", "category": "食費", "amount": 1200, "memo": "昼"},
                            {"date": "2026-11-02", "category": "rent", "amount": 80000, "memo": ""}],
                           ensure_ascii=False)
    assert to_json([]) == "[]"


def test_dupes():
    from kakeibo.dupes import find_duplicates
    a, b = E("2026-11-01", "food", 100, "x"), E("2026-11-01", "food", 100, "y")
    rows = [a, b, a, a, b]
    assert find_duplicates(rows) == [(0, 2), (0, 3), (1, 4), (2, 3)]
    assert find_duplicates([]) == []


def test_yen():
    from kakeibo.fmt import yen
    assert yen(1234567) == "1,234,567円"
    assert yen(0) == "0円"
    assert yen(-1200) == "-1,200円"
    assert yen(999) == "999円"


def test_weekday():
    from kakeibo.weekday import total_by_weekday
    rows = [E("2026-11-16", "a", 100), E("2026-11-22", "b", 5), E("2026-11-23", "c", 1)]  # Mon, Sun, Mon
    assert total_by_weekday(rows) == {"Mon": 101, "Sun": 5}
    assert list(total_by_weekday(rows)) == ["Mon", "Sun"]


def test_topn():
    from kakeibo.topn import top_expenses
    a, b, c, d = E("2026-11-03", "x", 50), E("2026-11-01", "y", 50), E("2026-11-02", "z", 90), E("2026-11-01", "w", 50)
    assert top_expenses([a, b, c, d], 3) == [c, b, d]
    assert top_expenses([a], 0) == []


def test_split():
    import pytest
    from kakeibo.split import split_evenly
    assert split_evenly(1000, 3) == [334, 333, 333]
    assert sum(split_evenly(7, 4)) == 7 and split_evenly(7, 4) == [2, 2, 2, 1]
    with pytest.raises(ValueError):
        split_evenly(100, 0)


def test_streak():
    from kakeibo.streak import longest_no_spend_streak
    rows = [E("2026-11-03", "a", 1), E("2026-11-07", "b", 1)]
    assert longest_no_spend_streak(rows, date(2026, 11, 1), date(2026, 11, 10)) == 3
    assert longest_no_spend_streak([], date(2026, 11, 1), date(2026, 11, 1)) == 1
