HEADER = "date,category,amount,memo\n"
BODY = "2026-10-31,food,500,\n2026-11-01,food,1200,\n2026-11-02,rent,80000,\n2026-11-03,food,800,\n"


def run(monkeypatch, capsys, tmp_path, *argv, body=BODY):
    from kakeibo import main

    p = tmp_path / "in.csv"
    p.write_text(HEADER + body, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["kakeibo", str(p), *map(str, argv)])
    code = 0
    try:
        main()
    except SystemExit as e:
        code = e.code or 0
    out = capsys.readouterr()
    return code, out.out, out.err
