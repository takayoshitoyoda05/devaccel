import json
from datetime import date

from _heldout_common import run

MEMO_BODY = (
    "2026-11-01,food,1200,lunch\n2026-11-02,rent,80000,\n2026-11-03,food,800,coffee\n"
    "2026-11-04,food,500,lunch with friends\n2026-11-05,book,900,lunch reading\n"
)


def test_without_count_unchanged(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--total")[:2] == (0, "rent\t80,000\nfood\t2,500\nTOTAL\t82,500\n")
    assert run(monkeypatch, capsys, tmp_path, "--format", "csv", "--total")[1] == (
        "category,amount\nrent,80000\nfood,2500\nTOTAL,82500\n"
    )
    assert run(monkeypatch, capsys, tmp_path, "--report")[1] == (
        "2026-10\tfood\t500\n2026-11\trent\t80000\n2026-11\tfood\t2000\n"
    )


def test_count_default(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--count") == (0, "rent\t80,000\t1\nfood\t2,500\t3\n", "")


def test_count_total(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--count", "--total")[1] == (
        "rent\t80,000\t1\nfood\t2,500\t3\nTOTAL\t82,500\t4\n"
    )


def test_count_csv_total_sorted_by_name(monkeypatch, capsys, tmp_path):
    out = run(monkeypatch, capsys, tmp_path, "--count", "--format", "csv", "--total", "--sort", "name")[1]
    assert out == "category,amount,count\nfood,2500,3\nrent,80000,1\nTOTAL,82500,4\n"


def test_count_report_is_per_month(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--count", "--report")[:2] == (
        0,
        "2026-10\tfood\t500\t1\n2026-11\trent\t80000\t1\n2026-11\tfood\t2000\t2\n",
    )


def test_count_category_total_counts_shown_rows_only(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--count", "--category", "food", "--total")[1] == (
        "food\t2,500\t3\nTOTAL\t2,500\t3\n"
    )


def test_count_nothing_to_show(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--count", "--category", "nope", "--total")[:2] == (0, "TOTAL\t0\t0\n")
    assert run(monkeypatch, capsys, tmp_path, "--count", "--format", "csv", body="")[:2] == (
        0,
        "category,amount,count\n",
    )


def test_count_after_memo_filter(monkeypatch, capsys, tmp_path):
    out = run(monkeypatch, capsys, tmp_path, "--count", "--memo", "lunch", "--total", body=MEMO_BODY)[1]
    assert out == "food\t1,700\t2\nbook\t900\t1\nTOTAL\t2,600\t3\n"
    out = run(monkeypatch, capsys, tmp_path, "--count", "--memo", "lunch", "--report", body=MEMO_BODY)[1]
    assert out == "2026-11\tfood\t1700\t2\n2026-11\tbook\t900\t1\n"


def test_count_does_not_change_budget_warnings(monkeypatch, capsys, tmp_path):
    b = tmp_path / "heldout_budget.json"
    b.write_text(json.dumps({"default": {"food": 400}}), encoding="utf-8")
    base = run(monkeypatch, capsys, tmp_path, "--budget", b)
    r = run(monkeypatch, capsys, tmp_path, "--budget", b, "--count")
    assert base[2].count("警告") == 2 and r[2] == base[2]
    assert r[1] == "rent\t80,000\t1\nfood\t2,500\t3\n"


def test_core_api_shape_unchanged():
    from kakeibo.core import Budget, Expense, find_overruns, monthly_totals, total_by_category

    rows = [
        Expense(date(2026, 11, 1), "food", 1200),
        Expense(date(2026, 10, 31), "food", 500),
        Expense(date(2026, 11, 2), "rent", 80000),
        Expense(date(2026, 11, 3), "food", 800, "coffee"),
    ]
    assert list(total_by_category(rows).items()) == [("rent", 80000), ("food", 2500)]
    totals = monthly_totals(rows)
    assert totals == {"2026-10": {"food": 500}, "2026-11": {"rent": 80000, "food": 2000}}
    assert find_overruns(totals, Budget({"food": 1000}, {})) == [("2026-11", "food", 1000, 1000, 2000)]
