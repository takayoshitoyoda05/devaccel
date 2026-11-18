import json

from _heldout_common import run

BUDGET = {"default": {"food": 400, "rent": 1000}}
ALL_WARNINGS = (
    "警告: 2026-10 food 100円超過 (予算 400 / 実績 500)\n"
    "警告: 2026-11 rent 79,000円超過 (予算 1,000 / 実績 80,000)\n"
    "警告: 2026-11 food 1,600円超過 (予算 400 / 実績 2,000)\n"
)
MEMO_BODY = "2026-11-01,food,1200,lunch\n2026-11-02,rent,80000,lunch fee\n2026-11-03,food,800,coffee\n"


def _budget(tmp_path, obj=BUDGET):
    p = tmp_path / "heldout_budget.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_no_category_unchanged(monkeypatch, capsys, tmp_path):
    r = run(monkeypatch, capsys, tmp_path, "--budget", _budget(tmp_path))
    assert r == (0, "rent\t80,000\nfood\t2,500\n", ALL_WARNINGS)


def test_category_limits_warnings_every_month(monkeypatch, capsys, tmp_path):
    r = run(monkeypatch, capsys, tmp_path, "--category", "food", "--budget", _budget(tmp_path))
    assert r == (
        0,
        "food\t2,500\n",
        "警告: 2026-10 food 100円超過 (予算 400 / 実績 500)\n"
        "警告: 2026-11 food 1,600円超過 (予算 400 / 実績 2,000)\n",
    )


def test_other_category(monkeypatch, capsys, tmp_path):
    r = run(monkeypatch, capsys, tmp_path, "--budget", _budget(tmp_path), "--category", "rent")
    assert r == (0, "rent\t80,000\n", "警告: 2026-11 rent 79,000円超過 (予算 1,000 / 実績 80,000)\n")


def test_category_within_budget_is_silent(monkeypatch, capsys, tmp_path):
    b = _budget(tmp_path, {"default": {"food": 99999, "rent": 1000}})
    assert run(monkeypatch, capsys, tmp_path, "--category", "food", "--budget", b) == (0, "food\t2,500\n", "")


def test_unknown_category_has_notice_but_no_warnings(monkeypatch, capsys, tmp_path):
    code, out, err = run(monkeypatch, capsys, tmp_path, "--category", "nope", "--total", "--budget", _budget(tmp_path))
    assert (code, out) == (0, "TOTAL\t0\n")
    assert "nope" in err and "警告" not in err and len(err.splitlines()) == 1


def test_report_still_ignores_category_for_stdout_and_warnings(monkeypatch, capsys, tmp_path):
    r = run(monkeypatch, capsys, tmp_path, "--report", "--category", "food", "--budget", _budget(tmp_path))
    assert r == (0, "2026-10\tfood\t500\n2026-11\trent\t80000\n2026-11\tfood\t2000\n", ALL_WARNINGS)


def test_csv_total_stdout_unchanged_warnings_limited(monkeypatch, capsys, tmp_path):
    r = run(monkeypatch, capsys, tmp_path, "--category", "food", "--format", "csv", "--total", "--sort", "name",
            "--budget", _budget(tmp_path))
    assert r[1] == "category,amount\nfood,2500\nTOTAL,2500\n"
    assert "rent" not in r[2] and r[2].count("警告") == 2


def test_memo_then_category(monkeypatch, capsys, tmp_path):
    b = _budget(tmp_path, {"default": {"food": 1000, "rent": 1000}})
    r = run(monkeypatch, capsys, tmp_path, "--memo", "lunch", "--category", "food", "--budget", b, body=MEMO_BODY)
    assert r == (0, "food\t1,200\n", "警告: 2026-11 food 200円超過 (予算 1,000 / 実績 1,200)\n")


def test_memo_without_category_unchanged(monkeypatch, capsys, tmp_path):
    b = _budget(tmp_path, {"default": {"food": 1000, "rent": 1000}})
    r = run(monkeypatch, capsys, tmp_path, "--memo", "lunch", "--budget", b, body=MEMO_BODY)
    assert r[1] == "rent\t80,000\nfood\t1,200\n" and r[2].count("警告") == 2
