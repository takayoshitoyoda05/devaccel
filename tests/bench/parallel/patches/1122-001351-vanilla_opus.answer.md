`click.Path` に `extensions` オプションを追加し、テストと一緒にコミットしました(`bb9ec5a`)。テストは全部通り、ruff と mypy も問題ありません。

**使い方**
```python
@click.argument("src", type=click.Path(extensions=[".csv", ".tsv"]))
```
- 大文字小文字は区別しません。`DATA.CSV` も `Data.Tsv` も通ります。
- 先頭のドットは省略できます(`"csv"` と書いても `".csv"` と同じ)。`".tar.gz"` のような二段の拡張子にも対応しています。
- 許可していない拡張子のときは、次のエラーになります(終了コード 2)。
  `Invalid value for 'SRC': Path 'in.json' does not have an allowed extension (.csv, .tsv).`

**私が決めた仕様**(違っていれば変えます)
- **存在しないファイル**もチェックします。`exists=False` のままでも、`out.txt` は弾かれます。
- **すでにあるディレクトリ**はチェックしません。
- `allow_dash=True` のときの `-`(標準入出力)はチェックしません。
- 拡張子は、入力されたパス名で判定します。`resolve_path=True` でシンボリックリンクを解決した後の名前ではありません。
- `.csv` という名前だけのファイルは、拡張子 `.csv` を持つとは見なさず、弾きます。
- 空リストや `""`、`"."` は `ValueError`、文字列以外を渡すと `TypeError` になります。`extensions=".csv"` のように文字列を1つだけ渡すと、拡張子1つとして扱います。

**変更したファイル**
- `src/click/types.py`: オプション本体と docstring。`to_info_dict()` の結果にも `extensions` を足しました。
- `tests/test_types/test_Path.py`: 新しいテスト。許可・拒否、正規化、不正な値、既存のファイルとディレクトリ、`-`、bytes と `pathlib.Path` の入力、CLI でのエラー表示、info dict を確かめています。
- `tests/test_info_dict.py`: `extensions` キーが増えたのに合わせて、期待値を直しました。
- `CHANGES.md`: 8.6.0 の項目に追記しました。

pytest の出力には毎回「31000 deselected」と出ますが、これは今回の変更より前からあるプロジェクトの設定によるもので、新しく足したテストはすべて実行されています。