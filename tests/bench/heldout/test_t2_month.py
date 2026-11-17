import pytest
from _heldout_common import run


def test_default_unchanged(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path)[:2] == (0, "rent\t80,000\nfood\t2,500\n")


def test_month(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--month", "2026-11")[:2] == (0, "rent\t80,000\nfood\t2,000\n")


def test_other_month(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--month", "2026-10")[1] == "food\t500\n"


def test_month_report(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--month", "2026-10", "--report")[1] == "2026-10\tfood\t500\n"


def test_empty_month(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--month", "2025-01")[:2] == (0, "")


def test_empty_month_total(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--month", "2025-01", "--total")[:2] == (0, "TOTAL\t0\n")


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "2026-1", "202611", "26-11", "2026-11-01"])
def test_bad_month(monkeypatch, capsys, tmp_path, bad):
    code, out, err = run(monkeypatch, capsys, tmp_path, "--month", bad)
    assert code == 2 and err.strip() and out == ""
