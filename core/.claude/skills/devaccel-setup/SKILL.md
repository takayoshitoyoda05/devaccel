---
name: devaccel-setup
description: devaccel の初回セットアップと再検出(--redetect)。プロジェクトを読んで CLAUDE.md・verify-app・check.sh・project.json を合わせる。
disable-model-invocation: true
---

# devaccel-setup

引数: なし = 初回セットアップ / `--redetect` = 構成変化の差分だけ提案

現状:
!`python3 .claude/hooks/devaccel_report.py 2>/dev/null; ls pyproject.toml uv.lock requirements*.txt setup.py package.json Makefile Cargo.toml go.mod AGENTS.md 2>/dev/null; cat .claude/project.json 2>/dev/null | head -40`

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
   - **check.sh が空(`no checks configured`、Python 以外)なら**: package.json の scripts / Makefile / Cargo.toml / go.mod などから lint・型・テストのコマンドを読み、`stage <名前> <コマンド>` の段と settings.json の allow を差分で提案する。空のままではゲートが何でも通す。
5. **verify-app スキル**: 実行形態を判定(CLI / API / ライブラリ / バッチ)し、`.claude/skills/verify-app/SKILL.md` の `devaccel:fill` を埋める。中身は「起動・確認コマンド」と「落とし穴」に限る。**書いたら1回実際に実行して通ることを確かめる。**
6. **ゲート**: 対話セッションでは既定 off(人が見ている)、/batch の単位では enforce(`gate.unit_mode`)と伝える。
7. 最後に変更ファイル一覧と「コミットしてください」を示す。

## --redetect
- 依存・ディレクトリ構成の変化から、**check.sh の段 / settings.json の allow / project.json の値** の変更案だけを出す。
- CLAUDE.md の人が書いた文章は再生成しない(コマンド節の差し替え提案のみ可)。
