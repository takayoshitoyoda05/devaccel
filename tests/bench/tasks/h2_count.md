kakeibo に `--count` オプションを追加して。カテゴリごとの明細の件数(CSV の行数)を金額の右に1列足す。

- 既定出力: 各行を `カテゴリ<TAB>金額<TAB>件数` にする(金額は今と同じ桁区切りあり、件数は桁区切りなしの整数)。
- `--total` 併用: 合計行を `TOTAL<TAB>合計金額<TAB>合計件数` にする。件数も金額と同じく「表示した行だけ」の合計。表示する行が無ければ `TOTAL<TAB>0<TAB>0`。
- `--format csv` 併用: ヘッダを `category,amount,count` にし、各行と `TOTAL` 行の末尾に件数を足す。表示する行が無ければヘッダ行だけ。
- `--report` 併用: 各行を `月<TAB>カテゴリ<TAB>円<TAB>件数` にする(件数はその月・そのカテゴリの行数。並びは今のまま)。
- `--category`・`--memo`・`--sort` と併用できる。件数は `--memo` / `--category` で絞り込んだ後の行を数える。並び順は `--count` の有無で変わらない。
- `--budget` の警告(stderr)は `--count` の有無で変わらない。
- `--count` を付けないときの出力は、どのオプションの組み合わせでも今と1バイトも変えない。
- `kakeibo.core` の既存の公開関数・クラス(`Expense`・`load_csv`・`total_by_category`・`monthly_totals`・`load_budget`・`find_overruns`)は他からも import されている。引数と戻り値の形は変えない(関数の追加は可)。
- テストも追加して。README も更新して。
- コミット・push・PR は不要。作業ツリーに変更を残して終わってよい。
