---
name: devaccel-batch
description: 独立した作業の大きな束を、作業単位(devaccel-unit、haiku)で並列に実装し、親が機械的に統合して証拠つき PR を 1 本にする。
disable-model-invocation: true
---

# devaccel-batch

引数: やることの一覧(1 行 1 件)。

## 使う条件(実測: docs/design.md D14)
- **既定は逐次**(1 セッションで順に実装し devaccel-pr で 1 本)。小さな作業 4 件では逐次 93 秒・$0.24 に対し、単位ごとに PR を作る並列は 129 秒・$0.80 だった。
- 並列にするのは: 逐次だと 5 分を超えそうで、4 件以上あり、編集ファイルが重ならないときだけ。L は並列化しない(design スキル)。

## 手順
1. `git fetch origin` → 作業ブランチを切る(`git switch -c batch/<名前> origin/<base>`)。
2. **親は薄く**: 親はコードを読まない(読むのは単位)。依頼文を単位ごとに分け、各単位への指示は **その件の文面そのまま(+ 共通の前提があれば 1 行)だけ**。規則・手順・リポジトリの説明は書かない(`devaccel-unit` の定義にある)。指示文が長いと、書き出す時間のぶん単位の起動が順にずれる(実測: 1 件 2,000 字で約 5 秒ずつ)。README・docs を変えるなら担当を 1 単位に決める。親の手数とコンテキストがコストの大半を占める(実測: 単位 4 つで $0.04、親 $0.33)。
3. Agent ツールで `devaccel-unit` を **単位の数だけ同じメッセージで** 起動する(並列に走る)。各単位の返事の `branch:` を控える。返事の要約以外は読み込まない。
4. `.devaccel/ship.md` に Write(1 行目 = 題名、以降 = 各単位の確認メモの要約)し、単独のコマンドで:
   `python3 .claude/hooks/devaccel_ship.py --file .devaccel/ship.md --units <branch1> <branch2> ...`
   - 単位のブランチを `--no-ff` で統合(衝突した単位は外して報告)→ base の check.sh を 1 回 → push → PR 1 本。
5. 統合後の差分を受け入れ条件と照合し、URL・ラベル・外した単位をユーザーに報告する。マージは人(`devaccel_land.py --merge` か GitHub)。
