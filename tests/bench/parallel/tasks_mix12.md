次の 12 件は互いに独立している(編集するファイルが重ならない)。どれも `src/kakeibo/core.py` の `Expense`(day: date, category: str, amount: int, memo: str)や `load_csv` を使う新しいモジュールを追加し、テストを足す。既存のファイル(core.py・__init__.py・README.md など)は変更しない。標準ライブラリだけを使う。

1. `src/kakeibo/stats.py` に `median_by_category(rows: list[Expense]) -> dict[str, float]`: カテゴリごとの金額の中央値(偶数個なら中央 2 つの平均)。キーはカテゴリ名の昇順。空なら `{}`。テストは `tests/test_stats.py`。
2. `src/kakeibo/export.py` に `to_json(rows: list[Expense]) -> str`: `[{"date": "YYYY-MM-DD", "category": ..., "amount": ..., "memo": ...}, ...]` の JSON 文字列(入力の順、`ensure_ascii=False`、インデントなし、キーの順は date, category, amount, memo)。テストは `tests/test_export.py`。
3. `src/kakeibo/dupes.py` に `find_duplicates(rows: list[Expense]) -> list[tuple[int, int]]`: day・category・amount・memo がすべて同じ明細の組 `(i, j)`(i < j、入力のインデックス)を i の昇順、同じ i なら j の昇順で返す。テストは `tests/test_dupes.py`。
4. `src/kakeibo/fmt.py` に `yen(n: int) -> str`: 3 桁区切りと「円」(例 `1234567` → `1,234,567円`、`0` → `0円`、負数は `-1,200円`)。テストは `tests/test_fmt.py`。

5. `src/kakeibo/weekday.py` に `total_by_weekday(rows: list[Expense]) -> dict[str, int]`: 曜日(`"Mon"`〜`"Sun"`、英語 3 文字)ごとの合計。明細のない曜日は含めない。キーは月曜始まりの順。テストは `tests/test_weekday.py`。
6. `src/kakeibo/topn.py` に `top_expenses(rows: list[Expense], n: int) -> list[Expense]`: 金額の大きい順に n 件(同額は日付の早い順、それも同じなら入力の順)。n が 0 以下なら `[]`。テストは `tests/test_topn.py`。
7. `src/kakeibo/split.py` に `split_evenly(amount: int, people: int) -> list[int]`: 円の整数を people 人で割り、端数は先頭の人から 1 円ずつ足す(合計は amount に一致)。people が 1 未満なら `ValueError`。テストは `tests/test_split.py`。
8. `src/kakeibo/streak.py` に `longest_no_spend_streak(rows: list[Expense], start: date, end: date) -> int`: start〜end(両端含む)の期間で、明細が 1 件もない日の最長連続日数。テストは `tests/test_streak.py`。
9. 定期支出の検出: `src/kakeibo/recurring.py`。テストは `tests/test_recurring.py`。
   - `add_month(d: date) -> date`: 翌月の同じ日を返す。翌月にその日がなければ翌月の末日(例 2026-01-31 → 2026-02-28、2024-01-31 → 2024-02-29、2026-12-15 → 2027-01-15)。
   - `@dataclass(frozen=True) class Recurring` — フィールドはこの順: `category: str`, `amount: int`, `days: tuple[date, ...]`, `next_expected: date`。
   - `find_recurring(rows: list[Expense], min_count: int = 3, tolerance: int = 3) -> list[Recurring]`:
     - `min_count < 2` または `tolerance < 0` なら `ValueError`。
     - 明細を (category, amount) の組でグループ分けする(memo は無視)。各グループで日付の重複を除き、昇順に並べる(d0 < d1 < ...)。
     - 隣り合う 2 つの日付 d_i, d_{i+1} は `abs((d_{i+1} - add_month(d_i)).days) <= tolerance` のとき「つながっている」とする。
     - 並びを、隣どうしがつながっている極大の連続区間に分ける(つながっていない所で切る)。長さが `min_count` 以上の区間 1 つにつき `Recurring(category, amount, days=区間の日付(昇順), next_expected=add_month(区間の最後の日付))` を 1 件作る。
     - 結果は category の昇順、同じなら amount の昇順、同じなら `days[0]` の昇順。該当なしや空入力は `[]`。

10. 他行 CSV の取り込み: `src/kakeibo/bankimport.py`。テストは `tests/test_bankimport.py`。
   - `parse_amount(s: str) -> int`: 前後の空白を除いたあと、「任意の `-`」「任意の `¥` または `￥` 1 文字」「ASCII 数字で始まり ASCII 数字とカンマ `,` だけからなる 1 文字以上の列」「任意の `円`」がこの順に並んだ文字列だけを受け付け、カンマを除いて整数にする(カンマの位置は検査しない)。例: `" ￥1,234,567 "` → `1234567`、`"-¥300"` → `-300`、`"980円"` → `980`、`"0"` → `0`。それ以外(`""`、`"円"`、`"12.5"`、`"1 200"`、`"--5"`、`"¥-5"`、全角数字 `"１２３"` など)は `ValueError`。
   - `parse_date(s: str) -> date`: 前後の空白を除いたあと、`YYYY/M/D` または `YYYY-M-D`(年は 4 桁、月と日は 1〜2 桁でゼロ埋めは任意、数字は ASCII のみ)を受け付ける。区切りの混在(`2026/1-5`)、年が 4 桁でないもの(`26/1/5`)、存在しない日付(`2026/02/30`)、その他の形式は `ValueError`。
   - `DEFAULT_MAPPING = {"date": "利用日", "category": "分類", "amount": "利用金額", "memo": "利用店名"}`(Expense のフィールド名 → CSV の列名)。
   - `import_rows(text: str, mapping: dict[str, str] | None = None, category_map: dict[str, str] | None = None) -> tuple[list[Expense], list[tuple[int, str]]]`:
     - `text` は 1 行目がヘッダーの CSV 文字列(`csv` モジュールで読む。引用符で囲まれたカンマ入りの値に対応する)。`mapping` が `None` なら `DEFAULT_MAPPING`。
     - `mapping` にキー `date`・`category`・`amount` のどれかが無ければ `ValueError`(`memo` は省略可で、省略時の memo は `""`)。`mapping` が指す列名がヘッダーに無ければ `ValueError`。CSV の余分な列は無視する。
     - 戻り値は `(取り込めた明細(入力の順), エラーの一覧)`。エラーは `(行番号, フィールド名)` で、行番号は text 上の物理行番号(ヘッダーが 1)。空行は読み飛ばすが行番号には数える。
     - 各データ行で date → amount → category の順に検査する。date は `parse_date`、amount は `parse_amount` が `ValueError` を出したらそれぞれ `"date"`、`"amount"` のエラー。category は前後の空白を除いて空文字列なら `"category"` のエラー。1 行に複数の誤りがあればこの順ですべて記録する。列が足りない行の欠けた値は空文字列として扱う。エラーが 1 つでもある行は明細に含めない。
     - category は前後の空白を除いたあと、`category_map` にキーがあればその値に置き換える。memo は前後の空白を除く。

11. 検索クエリ: `src/kakeibo/query.py`。テストは `tests/test_query.py`。
   - `class QueryError(ValueError)`。
   - `tokenize(q: str) -> list[tuple[str, str]]`: `(種類, 値)` の並びを返す。
     - 空白は区切りで、トークンにならない。
     - `(` → `("LPAREN", "(")`、`)` → `("RPAREN", ")")`。
     - `"` から次の `"` までは引用。中身(空白や括弧を含んでよい。エスケープは無い)を値とする `("TERM", 中身)`。閉じていない、または中身が空なら `QueryError`。
     - それ以外は、空白・`(`・`)`・`"` 以外の文字が続く限りを 1 語とする。語がちょうど `AND` / `OR` / `NOT`(大文字のみ)なら `("AND", "AND")` / `("OR", "OR")` / `("NOT", "NOT")`。語が `cat:` で始まるなら `("CAT", cat: より後ろ)` で、後ろが空なら `QueryError`。その他は `("TERM", 語)`(小文字の `and` などは TERM)。
   - 文法(優先順位は低い順に OR < AND < NOT):
     - `or_expr := and_expr ("OR" and_expr)*`
     - `and_expr := not_expr (["AND"] not_expr)*` — `AND` は省略でき、項を並べると AND になる。
     - `not_expr := "NOT" not_expr | primary`
     - `primary := TERM | CAT | "(" or_expr ")"`
     - トークンが 1 つも無い、括弧が合わない、演算子の後ろに項が無い、`()` など、文法に合わないものはすべて `QueryError`。
   - 評価: `TERM` は値が memo または category の部分文字列なら真。`CAT` は値が category と完全一致なら真。どちらも両辺を `str.casefold()` して比べる(大文字小文字を区別しない)。
   - `matches(q: str, e: Expense) -> bool`: クエリを 1 件の明細に対して評価する。
   - `filter_rows(q: str, rows: list[Expense]) -> list[Expense]`: 真になる明細を入力の順で返す。クエリが不正なら rows が空でも `QueryError`。

12. 前月比レポート: `src/kakeibo/monthdiff.py`。テストは `tests/test_monthdiff.py`。
   - `@dataclass(frozen=True) class DiffRow` — フィールドはこの順: `category: str`, `prev: int`, `curr: int`, `delta: int`, `pct: float | None`, `status: str`。
   - `month_diff(rows: list[Expense], prev_month: str, curr_month: str) -> list[DiffRow]`:
     - 月は `"YYYY-MM"`(月は 01〜12 の 2 桁)。形式が違えば `ValueError`。
     - 2 つの月のどちらかに明細があるカテゴリごとに 1 行。`prev` / `curr` はその月のカテゴリ合計(明細が無ければ 0)、`delta = curr - prev`、`pct = round(delta / prev * 100, 1)`(`prev == 0` なら `None`)。
     - `status`: prev_month にそのカテゴリの明細が 1 件も無ければ `"new"`、curr_month に 1 件も無ければ `"gone"`、それ以外は delta が正なら `"up"`、負なら `"down"`、0 なら `"same"`(判定は明細の有無で行い、合計が 0 かどうかではない)。
     - 並びは `abs(delta)` の降順、同じなら category の昇順。
   - `top_movers(diffs: list[DiffRow], n: int = 3) -> list[DiffRow]`: `status == "same"` を除いた先頭 n 件(順序は保つ)。`n < 0` なら `ValueError`。
   - `render_diff(diffs: list[DiffRow]) -> str`: タブ区切りの表。1 行目は `category\tprev\tcurr\tdelta\tpct`、以降 1 件 1 行で `category`、`prev`、`curr`、符号つきの delta(`+300`、`-2000`、`+0`)、符号つき小数 1 桁の pct に `%`(`+20.0%`、`-100.0%`、`+0.0%`。`None` なら `-`)。行は `\n` でつなぎ、末尾に改行は付けない。
   - `available_months(rows: list[Expense]) -> list[str]`: 明細がある月 `"YYYY-MM"` の昇順(重複なし)。
   - `latest_diff(rows: list[Expense]) -> list[DiffRow]`: `available_months` の最後の 2 つを (prev, curr) とした `month_diff`。月が 2 つ未満なら `ValueError`。
