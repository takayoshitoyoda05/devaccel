予算まわりを `src/kakeibo/budget.py` に分けて、コミットしました(`0a57b2a`)。テストは 57 件すべて通り、ruff と pyright もエラーはありません。

- **新しい `budget.py`:** `Budget`・`BudgetError`・`load_budget`・`find_overruns` と、その下請けの `_MONTH_RE`・`_amounts` を中身そのままで移しました。`core.py` には依存していないので、循環 import はありません。
- **`core.py`:** 予算部分を削除し、`budget.py` から公開されている 4 つの名前を読み込み直しています。これで今の `from kakeibo.core import Budget, ...` もそのまま動きます。使わなくなった `json` と `re` の import は消しました。
- **テスト:** `kakeibo.core` と `kakeibo.budget` の 4 つの名前が同じオブジェクトを指していることを確認するテストを 1 件足しました。それ以外のテストは変えていません。

`core.py` から引き続き読み込めるのは公開されている 4 つだけで、`_amounts` と `_MONTH_RE` はもう `kakeibo.core` からは import できません。リポジトリ内でこの 2 つを `core` から使っている箇所はないので、今のところ影響はありません。