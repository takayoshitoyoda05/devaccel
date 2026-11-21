`click.Path` に `extensions` オプションを追加して、コミットまで済ませました（`a423d22`）。テストは全件通っていて、mypy と ruff もエラーなしです。

```python
@click.argument("src", type=click.Path(dir_okay=False, extensions=[".csv", ".tsv"]))
```

**動作**
- 大文字小文字は区別しません。`DATA.CSV` や `data.Tsv` も通ります。
- 先頭のドットはあってもなくても同じ扱いです（`"csv"` と `".csv"` は同じ）。
- `.tar.gz` のような二重の拡張子も指定できます。
- ファイルがまだ存在しないパスもチェックします。出力ファイルの指定にも使えます。
- 次の場合はチェックしません。
  - パスが既存のディレクトリのとき
  - `allow_dash=True` で `-` が渡されたとき
- 拡張子に合わないとエラーになります。例: `File 'input.json' does not have one of the extensions '.csv', '.tsv'.`
- `extensions=[]` や空文字の拡張子を渡すと `ValueError` になります。

**自分で決めた点**
- `resolve_path=True` のときは、シンボリックリンクを解決する前の、ユーザーが入力した名前で判定します。リンク先の名前で判定したい場合は変更できます。
- `.csv` という名前だけのファイルは不許可にしました。

**変更したファイル**
- `src/click/types.py`: 本体の実装と docstring。`to_info_dict()` に `extensions` キーを追加
- `tests/test_types/test_Path.py`: 新しいテストを追加
- `tests/test_info_dict.py`: `extensions` キーの期待値を追加
- `CHANGES.md`: 8.6.0 の変更履歴に1行追加

テストを実行すると「31000 deselected」と出ます。これは今回の変更とは関係なく、もともとのテスト設定で多くのテストが除外されているためです。