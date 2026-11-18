次の作業は、`src/kakeibo/core.py` の `Expense`(day: date, category: str, amount: int, memo: str)を使う純粋な関数群を新しいモジュールに追加し、テストを足す。標準ライブラリだけを使う。既存のファイルは変更しない。

定期支出の検出: `src/kakeibo/recurring.py`。テストは `tests/test_recurring.py`。
   - `add_month(d: date) -> date`: 翌月の同じ日を返す。翌月にその日がなければ翌月の末日(例 2026-01-31 → 2026-02-28、2024-01-31 → 2024-02-29、2026-12-15 → 2027-01-15)。
   - `@dataclass(frozen=True) class Recurring` — フィールドはこの順: `category: str`, `amount: int`, `days: tuple[date, ...]`, `next_expected: date`。
   - `find_recurring(rows: list[Expense], min_count: int = 3, tolerance: int = 3) -> list[Recurring]`:
     - `min_count < 2` または `tolerance < 0` なら `ValueError`。
     - 明細を (category, amount) の組でグループ分けする(memo は無視)。各グループで日付の重複を除き、昇順に並べる(d0 < d1 < ...)。
     - 隣り合う 2 つの日付 d_i, d_{i+1} は `abs((d_{i+1} - add_month(d_i)).days) <= tolerance` のとき「つながっている」とする。
     - 並びを、隣どうしがつながっている極大の連続区間に分ける(つながっていない所で切る)。長さが `min_count` 以上の区間 1 つにつき `Recurring(category, amount, days=区間の日付(昇順), next_expected=add_month(区間の最後の日付))` を 1 件作る。
     - 結果は category の昇順、同じなら amount の昇順、同じなら `days[0]` の昇順。該当なしや空入力は `[]`。
