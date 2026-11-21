`click.Choice` に候補にない値を渡すと、近い候補があればエラーの末尾に「Did you mean ...?」が付くようにしました。テストを追加し、`ecb8838` でコミット済みです。

**出力例**
```
Error: Invalid value for '--method': 'bax' is not one of 'foo', 'bar', 'baz'. (Did you mean one of: 'bar', 'baz'?)
```
近い候補がない場合（例: `meh`）は、メッセージはこれまでと同じです。

**変更内容**
- `src/click/types.py`: `Choice.get_invalid_choice_message` を変更しました。
  - 近い候補は `difflib.get_close_matches` で探しています。未知のオプションやコマンドのエラー（`NoSuchOption` / `NoSuchCommand`）と同じ方法です。
  - 提案文の整形も同じ関数 `_format_possibilities` を使っているので、文言が揃っています。
  - 比較は入力値と候補を正規化してから行います。そのため `case_sensitive=False` や `token_normalize_func` を使っている場合も、Enum の選択肢でも正しく提案されます。
- `tests/test_types/test_Choice.py`: テストを追加しました。候補が1つ／複数の場合、選択肢が1つだけの場合、大文字小文字の扱い、Enum、CLI 経由のエラー表示、提案が出ない場合を確認しています。
- `CHANGES.md`: 8.6.0 の項目に追記しました。

**確認結果**
- テストは全件通過しました（2636 passed）。stress テストは設定で既定で除外されるため、実行していません。
- ruff と mypy は問題なしです。