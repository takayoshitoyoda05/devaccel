次の 8 件は互いに独立している(編集するファイルが重ならない)。どれも `src/kakeibo/core.py` の `Expense`(day: date, category: str, amount: int, memo: str)を使う純粋な関数を新しいモジュールに追加し、テストを足す。既存のファイル(core.py・__init__.py・README.md など)は変更しない。

1. `src/kakeibo/stats.py` に `median_by_category(rows: list[Expense]) -> dict[str, float]`: カテゴリごとの金額の中央値(偶数個なら中央 2 つの平均)。キーはカテゴリ名の昇順。空なら `{}`。テストは `tests/test_stats.py`。
2. `src/kakeibo/export.py` に `to_json(rows: list[Expense]) -> str`: `[{"date": "YYYY-MM-DD", "category": ..., "amount": ..., "memo": ...}, ...]` の JSON 文字列(入力の順、`ensure_ascii=False`、インデントなし、キーの順は date, category, amount, memo)。テストは `tests/test_export.py`。
3. `src/kakeibo/dupes.py` に `find_duplicates(rows: list[Expense]) -> list[tuple[int, int]]`: day・category・amount・memo がすべて同じ明細の組 `(i, j)`(i < j、入力のインデックス)を i の昇順、同じ i なら j の昇順で返す。テストは `tests/test_dupes.py`。
4. `src/kakeibo/fmt.py` に `yen(n: int) -> str`: 3 桁区切りと「円」(例 `1234567` → `1,234,567円`、`0` → `0円`、負数は `-1,200円`)。テストは `tests/test_fmt.py`。

5. `src/kakeibo/weekday.py` に `total_by_weekday(rows: list[Expense]) -> dict[str, int]`: 曜日(`"Mon"`〜`"Sun"`、英語 3 文字)ごとの合計。明細のない曜日は含めない。キーは月曜始まりの順。テストは `tests/test_weekday.py`。
6. `src/kakeibo/topn.py` に `top_expenses(rows: list[Expense], n: int) -> list[Expense]`: 金額の大きい順に n 件(同額は日付の早い順、それも同じなら入力の順)。n が 0 以下なら `[]`。テストは `tests/test_topn.py`。
7. `src/kakeibo/split.py` に `split_evenly(amount: int, people: int) -> list[int]`: 円の整数を people 人で割り、端数は先頭の人から 1 円ずつ足す(合計は amount に一致)。people が 1 未満なら `ValueError`。テストは `tests/test_split.py`。
8. `src/kakeibo/streak.py` に `longest_no_spend_streak(rows: list[Expense], start: date, end: date) -> int`: start〜end(両端含む)の期間で、明細が 1 件もない日の最長連続日数。テストは `tests/test_streak.py`。
