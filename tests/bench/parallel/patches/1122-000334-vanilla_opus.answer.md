直してコミットしました(`7c879fd`)。ただし pytest の実行が権限で拒否されたため、**テストは一度も実行できていません**。

**原因**
`src/click/types.py:695` の `_describe_range()` で、min だけ指定した場合の演算子が逆になっていました。

```python
op = ">=" if self.min_open else ">"   # 修正前
op = ">" if self.min_open else ">="   # 修正後
```

この処理は IntRange と FloatRange の共通の親クラスにあるので、FloatRange でも同じ症状が出ていました。表示だけの問題で、値のチェック自体は元から正しく 1 を受け付けていました。直前のコミット `54db462`("bench setup: click_range_bug.patch")で入った変更です。

**追加したテスト**(`tests/test_options.py`)
- `test_intrange_default_help_text` に `x>1`(min_open)と `x<32`(max_open)のケースを追加
- `test_floatrange_default_help_text` を新規追加。開区間・閉区間の6通りすべてでヘルプ表示を確認します
- `test_range_min_only_help_includes_bound` を新規追加(IntRange と FloatRange の両方)。ヘルプの表記と実際の判定(境界値 1 を通すか弾くか)が一致することを確認します

なお、既存の `test_intrange_default_help_text` にある `x>=1` のケースは、本来この不具合で落ちていたはずです。

テストを回すには、`pytest -q tests` を実行するか、pytest の実行を許可してもらえればこちらで回します。