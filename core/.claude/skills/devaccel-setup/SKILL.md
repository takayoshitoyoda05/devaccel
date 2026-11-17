---
name: devaccel-setup
description: devaccel の初回セットアップと再検出(--redetect)。プロジェクトを読んで CLAUDE.md・verify-app・check.sh・project.json を合わせる。
disable-model-invocation: true
---

# devaccel-setup

引数: なし = 初回セットアップ / `--redetect` = 構成変化の差分だけ提案 / `--codex on|off` = Codex 併用の切替

現状:
!`python3 .claude/hooks/devaccel_report.py 2>/dev/null; ls pyproject.toml uv.lock requirements*.txt setup.py AGENTS.md 2>/dev/null; cat .claude/project.json 2>/dev/null | head -40`

## 原則
- 生成物はすべて差分で見せ、ユーザーの承認後に書く。コミットはユーザーに任せる。
- CLAUDE.md には「コードや lint 設定から分からないこと」だけを書く。規約は ruff / pyright の設定へ。
- `<!-- devaccel:... -->` コメントは目印。残してよい(コンテキストを消費しない)。

## 初回セットアップ
1. **把握**: README、pyproject.toml、エントリポイント、テスト構成を必要最小限だけ読む。
2. **CLAUDE.md**: `devaccel:fill` の箇所(概要3行・コマンド)を埋める。全体で `budget.claude_md_max_lines` 以内。
3. **開発ツール**: ruff / pyright / pytest が無ければ `uv add --dev ruff pyright pytest` を提案(実行前に確認)。
4. **check.sh の計測**: `scripts/check.sh fast` を実行し、各段の秒数(`== ok: <段> (Ns)`)を見る。
   - 合計が `gate.fast_budget_sec` を超えたら、遅い段について案を出す: テストを `-m "not slow"` で絞る / 遅いテストに `slow` マーカー / pyright を変更ファイルのみにする(呼び出し側の型エラーは CI で拾う、と project.json に注記)。
   - `missing` の段があればツール導入を提案。
5. **verify-app スキル**: 実行形態を判定(CLI / API / ライブラリ / バッチ)し、`.claude/skills/verify-app/SKILL.md` の `devaccel:fill` を埋める。中身は「起動・確認コマンド」と「落とし穴」に限る。**書いたら1回実際に実行して通ることを確かめる。**
6. **Codex**: 併用するか聞く。on なら `--codex on` の手順を実行。
7. **ゲート**: `gate.mode` は `observe` のまま。昇格は運用後に `/devaccel-tune` で判断する、と伝える。
8. 最後に変更ファイル一覧と「コミットしてください」を示す。

## --redetect
- 依存・ディレクトリ構成の変化から、**check.sh の段 / settings.json の allow / project.json の値** の変更案だけを出す。
- CLAUDE.md の人が書いた文章は再生成しない(コマンド節の差し替え提案のみ可)。

## --codex on|off
- on: CLAUDE.md の本文を `AGENTS.md` に移し、CLAUDE.md は `@AGENTS.md` と Claude 固有の行(スキル参照・ゲート)だけにする。Codex には Stop フックが無いので、Codex 側の担保は AGENTS.md の検証指示と CI だけになる、と伝える。
- off: 逆の操作。AGENTS.md を CLAUDE.md に戻す。
