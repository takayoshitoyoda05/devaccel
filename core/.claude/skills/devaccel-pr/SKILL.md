---
name: devaccel-pr
description: 作業を PR にするときに使う。実動作確認の記録を書き、1 コマンドでコミット・push・証拠つき PR を作ってレビュー要否のラベルを付ける。
---

# devaccel-pr

人は差分ではなく証拠を見る。PR 本文はスクリプトが機械的に組み立てる(検査は base の check.sh を HEAD のスナップショットで実行。自己申告しない)。

1. 作業ブランチにいることを確認する(main 等なら `git switch -c <名前>`)。
2. `.devaccel/ship.md` に Write する: **1 行目 = PR の題名**、2 行目以降 = 実動作確認(実行したコマンド / 出力の要点 / 期待と合ったか。確かめられなかったことは、そう書く)。`.claude/` の下には書かない。
3. 単独のコマンドで実行: `python3 .claude/hooks/devaccel_ship.py --file .devaccel/ship.md --paths <新しく作ったファイル...>`
   - 追跡済みの変更は自動で入る。新規ファイルは `--paths` に並べる(`-A` 相当はしない)。
   - コミット・push(作業ブランチを origin へ)・PR 作成までを 1 回で行う。迷ったら先に `--dry-run`。
4. 出力の URL とラベルを報告する。`needs-human` なら理由を伝える(ラベルを外すために変更を加えない)。

衝突・統合後の失敗で `needs-human` に落とされたら: `git merge origin/<base>` → 解消 → 3 を再実行(既存 PR が更新される)。
