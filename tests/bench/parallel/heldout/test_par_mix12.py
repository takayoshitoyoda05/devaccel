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


# ---- medium set ----
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


def test_bankimport():
    from kakeibo.bankimport import DEFAULT_MAPPING, import_rows, parse_amount, parse_date
    assert parse_amount(" ￥1,234,567 ") == 1234567
    assert parse_amount("-¥300") == -300
    assert parse_amount("980円") == 980
    for bad in ["", "円", "12.5", "1 200", "--5", "¥-5", "１２３"]:
        with pytest.raises(ValueError):
            parse_amount(bad)
    assert parse_date(" 2026/1/5 ") == D("2026-01-05")
    assert parse_date("2026-11-04") == D("2026-11-04")
    for bad in ["2026/1-5", "26/1/5", "2026/02/30", "20260105", ""]:
        with pytest.raises(ValueError):
            parse_date(bad)
    assert DEFAULT_MAPPING == {"date": "利用日", "category": "分類", "amount": "利用金額", "memo": "利用店名"}
    text = ("利用日,利用店名,利用金額,分類,備考\n"
            '2026/11/3,スーパー ,"1,200", 食費,x\n'
            "\n"
            "2026-11-04,書店,¥980円,本,\n"
            "2026/13/1,x,abc, ,\n"
            "2026/11/05,返金,-500,食費,\n"
            "2026/11/06,店\n")
    rows, errors = import_rows(text, category_map={"食費": "food"})
    assert rows == [E("2026-11-03", "food", 1200, "スーパー"), E("2026-11-04", "本", 980, "書店"),
                    E("2026-11-05", "food", -500, "返金")]
    assert errors == [(5, "date"), (5, "amount"), (5, "category"), (7, "amount"), (7, "category")]
    m = {"date": "d", "category": "c", "amount": "a"}
    assert import_rows("d,c,a\n2026/1/2,x,10\n", m) == ([E("2026-01-02", "x", 10, "")], [])
    with pytest.raises(ValueError):
        import_rows("d,c\n2026/1/2,x\n", m)
    with pytest.raises(ValueError):
        import_rows("d,c,a\n2026/1/2,x,10\n", {"date": "d", "category": "c"})


def test_query():
    from kakeibo.query import QueryError, filter_rows, matches, tokenize
    assert tokenize('a AND (b OR NOT "c d") cat:x and') == [
        ("TERM", "a"), ("AND", "AND"), ("LPAREN", "("), ("TERM", "b"), ("OR", "OR"), ("NOT", "NOT"),
        ("TERM", "c d"), ("RPAREN", ")"), ("CAT", "x"), ("TERM", "and")]
    a = E("2026-11-01", "food", 500, "Coffee at cafe")
    b = E("2026-11-02", "food", 1200, "lunch (set)")
    c = E("2026-11-03", "book", 1500, "coffee table book")
    d = E("2026-11-04", "rent", 80000)
    rows = [a, b, c, d]
    assert filter_rows("coffee", rows) == [a, c]
    assert filter_rows("food AND NOT coffee", rows) == [b]
    assert filter_rows("cat:BOOK OR lunch", rows) == [b, c]
    assert filter_rows("coffee book", rows) == [c]
    assert filter_rows("NOT (food OR cat:book)", rows) == [d]
    assert filter_rows('"lunch (set)"', rows) == [b]
    assert filter_rows("rent OR food AND coffee", rows) == [a, d]
    assert filter_rows("cat:boo", rows) == []
    assert matches("NOT NOT cafe", a) is True
    assert matches('"AND"', a) is False
    assert issubclass(QueryError, ValueError)
    for bad in ["", "  ", "(food", "food )", "food AND", "OR food", "NOT", "()", 'food "abc', '""', "cat:"]:
        with pytest.raises(QueryError):
            filter_rows(bad, [])


def test_monthdiff():
    from kakeibo.monthdiff import DiffRow, available_months, latest_diff, month_diff, render_diff, top_movers
    rows = [E("2026-09-30", "food", 100),
            E("2026-10-01", "food", 1000), E("2026-10-20", "food", 500), E("2026-10-01", "rent", 80000),
            E("2026-10-05", "book", 2000), E("2026-10-06", "misc", 300),
            E("2026-11-02", "food", 1800), E("2026-11-01", "rent", 80000), E("2026-11-03", "game", 6000),
            E("2026-11-04", "misc", 100), E("2026-11-05", "misc", -100)]
    diffs = month_diff(rows, "2026-10", "2026-11")
    assert diffs == [DiffRow("game", 0, 6000, 6000, None, "new"),
                     DiffRow("book", 2000, 0, -2000, -100.0, "gone"),
                     DiffRow("food", 1500, 1800, 300, 20.0, "up"),
                     DiffRow("misc", 300, 0, -300, -100.0, "down"),
                     DiffRow("rent", 80000, 80000, 0, 0.0, "same")]
    assert top_movers(diffs, 2) == diffs[:2]
    assert top_movers(diffs, 10) == diffs[:4]
    assert top_movers(diffs, 0) == []
    assert render_diff(diffs) == ("category\tprev\tcurr\tdelta\tpct\n"
                                  "game\t0\t6000\t+6000\t-\n"
                                  "book\t2000\t0\t-2000\t-100.0%\n"
                                  "food\t1500\t1800\t+300\t+20.0%\n"
                                  "misc\t300\t0\t-300\t-100.0%\n"
                                  "rent\t80000\t80000\t+0\t+0.0%")
    assert available_months(rows) == ["2026-09", "2026-10", "2026-11"]
    assert latest_diff(rows) == diffs
    assert month_diff(rows, "2026-08", "2026-09") == [DiffRow("food", 0, 100, 100, None, "new")]
    with pytest.raises(ValueError):
        latest_diff(rows[:1])
    for bad in ["2026-1", "2026-13", "2026/10"]:
        with pytest.raises(ValueError):
            month_diff(rows, bad, "2026-11")
    with pytest.raises(ValueError):
        top_movers(diffs, -1)
