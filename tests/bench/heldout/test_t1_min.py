import pytest
from _heldout_common import run


def test_default_unchanged(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path)[:2] == (0, "rent\t80,000\nfood\t2,500\n")


def test_min_filters_rows(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--min", "1000")[:2] == (0, "rent\t80,000\nfood\t1,200\n")


def test_min_boundary_is_inclusive(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--min", "800")[1] == "rent\t80,000\nfood\t2,000\n"


def test_min_total(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--min", "1000", "--total")[1].endswith("TOTAL\t81,200\n")


def test_min_report_drops_month(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--min", "1000", "--report")[1] == "2026-11\trent\t80000\n2026-11\tfood\t1200\n"


def test_min_zero_is_noop(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--min", "0")[1] == "rent\t80,000\nfood\t2,500\n"


@pytest.mark.parametrize("bad", ["-1"])
def test_min_negative(monkeypatch, capsys, tmp_path, bad):
    code, out, err = run(monkeypatch, capsys, tmp_path, f"--min={bad}")
    assert code == 2 and err.strip()
