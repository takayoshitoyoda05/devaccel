import pytest
from _heldout_common import run

TIES = "2026-11-01,food,1000,\n2026-11-02,book,1000,\n2026-11-03,rent,5000,\n2026-11-04,cafe,300,\n"


def test_default_unchanged(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path)[:2] == (0, "rent\t80,000\nfood\t2,500\n")


def test_top1(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--top", "1")[:2] == (0, "rent\t80,000\n")


def test_top_ties_by_name(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--top", "2", body=TIES)[1] == "rent\t5,000\nbook\t1,000\n"


def test_top_total_counts_shown_only(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--top", "2", "--total", body=TIES)[1].endswith("TOTAL\t6,000\n")


def test_top_more_than_categories(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--top", "10")[1] == "rent\t80,000\nfood\t2,500\n"


def test_top_with_category(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--top", "1", "--category", "food")[1] == "food\t2,500\n"


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_top_bad(monkeypatch, capsys, tmp_path, bad):
    code, out, err = run(monkeypatch, capsys, tmp_path, f"--top={bad}")
    assert code == 2 and err.strip()
