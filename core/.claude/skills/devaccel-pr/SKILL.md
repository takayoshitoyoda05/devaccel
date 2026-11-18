---
name: devaccel-pr
description: 作業を PR にするときに使う(/batch の各単位の最後も)。実動作確認の記録を残し、検証の証拠を本文にした PR を作ってレビュー要否のラベルを付ける。
---

# devaccel-pr

人は差分ではなく証拠を見る。PR 本文はスクリプトが機械的に組み立てる(自分で書かない)。

コマンドは 1 回の Bash で 1 つずつ。`$(...)`・`$変数`・ヒアドキュメント・`cd` を使わない(確認なしで動かせず、/batch の単位では拒否される)。ファイルは Write ツールで書く。

1. **実動作確認**: verify-app の手順で動かし、「実行したコマンド / 出力の要点 / 期待と合ったか」を数行で `.devaccel/pr-notes.md` に Write する(git 管理外。`.claude/` の下は書き込みに確認が要るので使わない)。確認できなかったことは、できなかったと書く。
2. **コミット**: `git add <変更したパス>`(`-A` は使わない)。メッセージは `.devaccel/commit-msg.txt` に Write し、`git commit -F .devaccel/commit-msg.txt`。末尾に検証の記録を 1 行(未実施は `none`):
   `Verified-by: check-full=<pass|fail> verify-app=<yes|none> spec-review=<yes|none>`
3. **push**: `git push origin HEAD` を**単独のコマンドで**(`&&` でつなげない、`cd` を付けない。`-u` は不要)。作業ブランチ上でのみ可能。
4. **PR 作成**: `python3 .claude/hooks/devaccel_pr.py --title "<要約>" --verify-notes .devaccel/pr-notes.md`(`gh` は直接使えない)
   - 迷ったら先に `--dry-run` で本文とラベルを確認。
   - `needs-human` が付いたら、理由をユーザーに伝える。ラベルを外す・理由を消すために変更を加えない。
5. 出力の URL とラベルを報告して終わる。

衝突・統合後の失敗で `needs-human` に落とされたら: rebase せず `git merge origin/<base>` → 解消してコミット → `git push origin HEAD` → 4 を再実行(既存 PR の本文とラベルが更新される)。
