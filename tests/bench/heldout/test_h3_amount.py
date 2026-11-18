import pytest
from _heldout_common import run

GOOD = (
    '2026-11-01,food,"1,200",\n'
    '2026-11-02,rent,"¥80,000",\n'
    "2026-11-03,food, 800円 ,\n"
    '2026-11-04,car,"￥1,234,567円",\n'
    "2026-11-05,refund,-¥500,\n"
    "2026-11-06,food,007,\n"
    '2026-12-01,refund,"-1,000円",\n'
)


def _line(value):
    return f'2026-11-01,food,100,\n2026-11-02,food,"{value}",\n'


def test_plain_integers_unchanged(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--total") == (0, "rent\t80,000\nfood\t2,500\nTOTAL\t82,500\n", "")


def test_accepted_notations(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--total", body=GOOD) == (
        0,
        "car\t1,234,567\nrent\t80,000\nfood\t2,007\nrefund\t-1,500\nTOTAL\t1,315,074\n",
        "",
    )


def test_accepted_notations_csv_output_is_plain_integers(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--format", "csv", "--sort", "name", body=GOOD)[:2] == (
        0,
        "category,amount\ncar,1234567\nfood,2007\nrefund,-1500\nrent,80000\n",
    )


def test_accepted_notations_report(monkeypatch, capsys, tmp_path):
    assert run(monkeypatch, capsys, tmp_path, "--report", body=GOOD)[1] == (
        "2026-11\tcar\t1234567\n2026-11\trent\t80000\n2026-11\tfood\t2007\n2026-11\trefund\t-500\n"
        "2026-12\trefund\t-1000\n"
    )


@pytest.mark.parametrize("value", ["-¥500", "￥500", "500円", "  1,000  ", "-0", "¥1,000円", "999", "12,345"])
def test_each_valid_form(monkeypatch, capsys, tmp_path, value):
    code, out, err = run(monkeypatch, capsys, tmp_path, "--format", "csv", body=_line(value))
    assert code == 0 and err == "" and out.startswith("category,amount\nfood,")


@pytest.mark.parametrize("value", ["+500", "1_000", "１２００", "1２3"])
def test_rejects_what_int_used_to_accept(monkeypatch, capsys, tmp_path, value):
    code, out, err = run(monkeypatch, capsys, tmp_path, body=_line(value))
    assert code == 1 and out == "" and err.startswith("3: ")


@pytest.mark.parametrize("value", ["12,00", "1,2000", ",100", "1,200,", "1,,200", "1234,567", "1,200,00"])
def test_rejects_bad_grouping(monkeypatch, capsys, tmp_path, value):
    code, out, err = run(monkeypatch, capsys, tmp_path, body=_line(value))
    assert code == 1 and out == "" and err.startswith("3: ")


@pytest.mark.parametrize(
    "value", ["¥-500", "¥¥500", "¥￥500", "500円円", "円500", "500¥", "--500", "¥ 500", "- 500", "1 200", "1.0"]
)
def test_rejects_bad_order_or_extra_symbols(monkeypatch, capsys, tmp_path, value):
    code, out, err = run(monkeypatch, capsys, tmp_path, body=_line(value))
    assert code == 1 and out == "" and err.startswith("3: ")


@pytest.mark.parametrize("value", ["", "¥", "円", "-", "¥円", "   "])
def test_rejects_no_digits(monkeypatch, capsys, tmp_path, value):
    code, out, err = run(monkeypatch, capsys, tmp_path, body=_line(value))
    assert code == 1 and out == "" and err.startswith("3: ")


def test_error_message_format_and_all_bad_lines_reported(monkeypatch, capsys, tmp_path):
    body = '2026-11-01,food,1_000,\n2026-11-02,food,"1,200",\n2026-11-03,food,"12,00",\n'
    assert run(monkeypatch, capsys, tmp_path, body=body) == (
        1,
        "",
        "2: 金額が整数ではありません: '1_000'\n4: 金額が整数ではありません: '12,00'\n",
    )
