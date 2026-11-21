予算まわりを `src/kakeibo/budget.py` に移し、コミットしました(`9a3d343`)。テストは 57 件すべて通り、ruff・pyright もエラーなしです。

- **移したもの:** `Budget`・`BudgetError`・`load_budget`・`find_overruns` と、下請けの `_amounts` と `_MONTH_RE` です。中身は書き換えず、そのまま移動しました。`core.py` では使わなくなった `json` と `re` の import を消しています。
- **今の import との互換:** `core.py` から公開している 4 つの名前を読み込み直しているので、`from kakeibo.core import ...` はそのまま動きます。`__init__.py` と既存のテストは変更していません。
- **テスト:** `kakeibo.core` と `kakeibo.budget` の 4 つの名前が同じものを指していることを確かめるテストを `tests/test_budget.py` に 1 つ足しました。

アンダースコアで始まる `_amounts` と `_MONTH_RE` は `core` からは読み込めなくなりました。今のコードでは使っている箇所はありません。

ruff の設定で `X as X` 形式の再エクスポートが警告になるため、普通の import に `# noqa: F401` を付けて対応しています。