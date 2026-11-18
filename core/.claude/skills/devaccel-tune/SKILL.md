---
name: devaccel-tune
description: ゲートの記録と運用の摩擦から、ルール・検査・設定の追加/削除/調整案を出す(承認後に適用、PR 推奨)。
disable-model-invocation: true
---

# devaccel-tune

ゲートの記録(要約):
!`python3 .claude/hooks/devaccel_report.py 2>/dev/null`

最近のリバート:
!`git log --oneline -n 200 2>/dev/null | grep -i revert | head -5`

PR の振り分け(直近 30 件):
!`gh pr list --state all --limit 30 --json labels,state --jq '[.[] | {l: ([.labels[].name] | map(select(. == "evidence-ok" or . == "needs-human")) | first // "none"), s: .state}] | group_by(.l) | map("\(.[0].l): \(length)件 (merged \(map(select(.s == "MERGED")) | length))") | .[]' 2>/dev/null`

## 入力
上の要約に加え、使えるなら公式の診断(`/context`、`/usage`、`/insights`、`/doctor`)の結果をユーザーに貼ってもらう。ユーザーの「最近 Claude に何度も言ったこと」も聞く(1 問だけ)。

## 判断規則
1. **追加**は「2 回以上起きた」かつ「再発を機械的に検出できる」ものだけ。追加先は上から優先:
   1. ruff / pyright の設定、またはテスト(決定的・トークン 0)
   2. `scripts/check.sh` の 1 段
   3. settings.json の permissions(ask / deny)
   4. フック(`.claude/project.json` の guard.deny_regex / ask_regex)
   5. verify-app / design スキルの本文
   6. CLAUDE.md の 1 行 —— 検出できないが常に必要なものだけ。**1 行足すなら 1 行消す。**
2. **削除**候補: 一度も発火していない規則、発火しても結果を変えていない規則、現行モデルなら不要そうな指示(モデル世代が変わったら全行を再評価)。
3. **調整**: would_block / escalate が多い段は誤検知か本当の問題かをユーザーと確認。遅い段(stage avg secs)は fast から外す・絞る案。
4. **振り分けの評価**: `evidence-ok` で後にリバート・不具合が出たものがあれば、その原因を検出できる段(check / verify-app / risky_paths)を足す。`needs-human` ばかりなら理由の内訳を見て閾値を見直す。自動マージは、evidence-ok のリバートが 0 の期間が続いてから提案する。
5. **単位ゲート**: `scope: unit` の block / escalate を見て、誤ブロック(段の誤検知)か本当の問題かを確認。誤検知が続く段は直すか fast から外す案。
6. **ゲートや検査を緩める変更**(段の削除、mode を下げる、max_rounds を上げる、ignore を広げる)は、理由を明示し、必ずユーザーの明示的な承認を得る。

## 出力
- 提案ごとに「根拠(件数)/ 変更先 / 差分」を示す。CLAUDE.md の文言はユーザーが短く書き直す前提で案を出す。
- 承認されたものだけ適用。チーム利用ならブランチを切って PR にし、根拠を PR 本文に書く。
- 他のプロジェクトでも 2 回以上同じ拡張をしたものは、devaccel 本体への逆輸入候補としてメモする。
