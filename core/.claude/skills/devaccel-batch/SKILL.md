---
name: devaccel-batch
description: 独立した S/M 作業の束を /batch で並列に実装し、各単位を証拠つき PR にする(人は land で統合を確かめてマージ)。
disable-model-invocation: true
---

# devaccel-batch

引数: やることの一覧(1 行 1 件)。

## 使う条件
- 独立した S/M が **多数**(目安 5 件以上、かつ各件が数分以上かかる規模)。実測では小さな作業 4 件で逐次 93 秒・$0.24、並列 129 秒・$0.80 と、並列のほうが遅く高かった(単位は親のキャッシュを共有せず、PR・検査の固定費がかかる)。迷ったら 1 セッションで順に。L は並列化しない(design スキルで 1 本ずつ)。
- 編集ファイルが重なる作業は同じ単位にまとめる。重なりは land で衝突になる。

## 手順
1. `git fetch origin`(古い base から始めると land で落ちる)。
2. 各単位の **コンテキストパック** を作る: 編集するファイル / 読むべき参照 / 受け入れ条件 / 実行するテスト / 範囲外。README・docs は振る舞いを変えた単位自身が更新する。
3. `/batch` を呼ぶ。各単位への指示に次を必ず埋め込む:
   - 「Bash は単純なコマンドを 1 つずつ(`$(...)`・`$変数`・ループ・ヒアドキュメント・`cd` は使わない。単位では確認できず拒否される)。ファイルは Write/Edit で作る」
   - 「最後に devaccel-pr スキルで PR にする」
4. 終わったら PR の URL とラベルを一覧にし、ユーザーに次を伝える:
   - 統合の確認とマージは人が端末で `python3 .claude/hooks/devaccel_land.py --merge`(evidence-ok を最新 base 上で 1 本ずつ再検証)。
   - `needs-human` は理由を読む。衝突で落ちた単位は、その worktree で `git merge origin/<base>` → 解消 → push → devaccel-pr 再実行。
