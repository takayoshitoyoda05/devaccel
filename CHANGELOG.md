# Changelog

## 0.4.1 (2026-11-18)
- guard: `git push` / `gh <サブコマンド>` を区切りの途中でも検出し、`bash -c`・`eval`・`xargs`・`python -c`・`find -exec` 等の起動手段と git/gh の組み合わせを拒否(サンドボックスの自動許可と組み合わさる経路を塞ぐ)。README に「本当の境界は GitHub のブランチ保護」を明記。

## 0.4.0 (2026-11-18)
- 並列 PR フローを実機の失敗(/batch の 3 単位すべてが commit/push で拒否)から修正。
- guard: push は作業ブランチからの `git push origin HEAD` のみ(main/master・デフォルトブランチ・force・他リモート・cd/git -C 併用は拒否)。リモート設定の変更と `gh` の直接実行を拒否。PR スクリプトは lock とハッシュが一致する時だけ実行可。git の展開チェックは diff/log 等のサブコマンドに限定、コマンドは区切りごとに判定。ASK 規則は区切りの先頭のみ。
- devaccel_pr.py: デフォルトブランチ・未 push では実行しない。`-R owner/repo` で対象を固定。`--verify-notes` はリポジトリ内か一時ディレクトリの 4KB 以下、認証情報らしき内容は拒否。
- settings 生成: `Bash(git push*)` の ask を削除し、add/commit/`git push origin HEAD`/PR スクリプトを allow、`gh *`・force push・remote 変更を deny。サンドボックスに `autoAllowBashIfSandboxed` と github.com / api.github.com。
- devaccel-pr スキル: commit・push・PR を別コマンドで、`git add <パス>`。
- doctor: 信頼ダイアログ未承認、残った push の ask 規則、api.github.com、gh 認証、origin の形式を点検。

## 0.3.2 (2026-11-18)
- サンドボックス: Python プリセットにツールキャッシュの書き込み許可(`~/.cache/uv` ほか)と registry.npmjs.org(pyright 用)を追加。実機でサンドボックス内の `uv run pytest` が読み取り専用エラーで動かなかった。

## 0.3.1 (2026-11-18)
- devaccel-pr: 「変更は自分のチェックを変えられない」を徹底。check.sh は base ブランチ版で実行。検証基盤(check.sh・.claude/・.github/・CLAUDE.md・conftest・ツール設定)の変更と、既存テストの行削除は常に needs-human。自動マージは必須ステータスチェックつきのブランチ保護がある時だけ。

## 0.3.0 (2026-11-18)
- 並列開発(Anthropic 式): devaccel-pr スキルと `hooks/devaccel_pr.py`。PR 本文を証拠(check.sh full・実動作確認・受け入れ条件・規模)から機械的に組み立て、`evidence-ok` / `needs-human` を理由つきで付与。`parallel.auto_merge`(既定 off)で evidence-ok を自動マージ。
- settings 生成: `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=3`、`.claude/worktrees/` を gitignore。
- CLAUDE.md: S/M の束は `/batch`、PR は devaccel-pr。tune: PR 振り分け実績を入力に。
- guard: 展開($ ` {)を含む git コマンドは確認。

## 0.2.1 (2026-11-18)
- サンドボックス: `failIfUnavailable: true`(依存が無ければ起動しない)と `allowUnsandboxedCommands: false`(サンドボックス外での再試行を禁止)。denyRead をプロジェクト相対 `./**/.env*` にも拡大。Read/Edit の deny に `**/.env*`。
- guard: git の判定をバックスラッシュ除去・`${IFS}` 区切りの後に実施。`$`/バッククォートを含む git コマンドは確認。

## 0.2.0 (2026-11-18)
- **方針変更**: guard から `.env` などの秘密の検出を削除し、破壊的操作の検出に専念。秘密は OS レベルのサンドボックス(`sandbox.filesystem.denyRead`)と Read の deny で守る(docs/design.md D5b)。0.1.x の正規表現による検出は誤検知と抜け道の修正が交互に続き、並列・非対話実行の速度を落としていた。
- guard: 規則はヒアドキュメント本文を含む生のコマンドに適用(パーサ差異を作らない)。
- install: settings.json にサンドボックス設定(denyRead、Python 用の許可ドメイン)を生成。bubblewrap/socat が無ければ案内。
- doctor: サンドボックスの有効化と依存の有無を点検。

## 0.1.12 (2026-11-18)
- guard: ヒアドキュメント本文(ファイル内容・スクリプト)を検査対象から除外。L 規模タスクの実地テストで設計書・Python コードの書き込みが誤ブロックされていた。`$` とドットの組み合わせの判定を `.e`・先頭ドット・env・波括弧に限定。引用符で完全に囲まれた単語はワイルドカード検査の対象外(bash は展開しないため。`grep '.*foo'` 等の誤検知を解消)。

## 0.1.11 (2026-11-18)
- README: サンドボックス併用の節を追加(guard は best-effort、強い保護は OS レベルで)。
- settings 生成: .env の deny に公式のプロジェクト相対表記 `/.env` を追加。

## 0.1.10 (2026-11-18)
- guard: `shopt`/`dotglob`/`GLOBIGNORE` と `$'...'` は確認、`{.` / `,.` の波括弧は拒否、`cd`/`pushd`/`popd`/`git -C`/`env -C` を区切り記号の後でも検出。guard はここで打ち止め(best-effort)。強い保護はサンドボックスで。

## 0.1.9 (2026-11-18)
- guard: git を単語単位で判定。`--output` / `--ext-diff` の任意の省略形を拒否、`$`・バッククォートを含む git コマンドは確認に回す。
- settings 生成: git と check.sh の自動許可を引数なしの完全一致のみに。deny に `--out*` / `--ext*`。

## 0.1.8 (2026-11-18)
- guard: 0.1.7 で `cd` を含むコマンドを一律に確認に回していたのを、`cd` 後にドットファイル向けワイルドカードがある場合だけに限定。

## 0.1.7 (2026-11-18)
- guard: 0.1.5 で外した `.e*` 系の拒否規則を最後の歯止めとして復活(実ディレクトリ展開は追加検査に)。`.?nv` などドット直後のワイルドカード、多重・入れ子の波括弧は拒否。`cd`/`pushd` を含む・展開先が不明・`$`/`~`/バッククォートを含むパスは確認に回す。

## 0.1.6 (2026-11-18)
- settings 生成: git の自動許可を安全な形だけに限定(`git diff --stat` 等)。git は長いオプションの省略(`--out=`)を受け付けるため、`git diff *` は deny では守れない。
- guard: `--output` / `--ext-diff` の省略形、`${IFS}` 区切り、`-c alias.*=` も拒否。
- 既存プロジェクト: `.claude/settings.json` の `git diff *` / `git log *` / `git show *` の allow は手で削除を推奨(guard が補うが二重化のため)。

## 0.1.5 (2026-11-18)
- guard: .env 検出を正規表現の列挙から「ワイルドカード・波括弧を実ディレクトリに展開して .env* に当たるか」に変更。`$`/バッククォートで組み立てたドットファイル名は確認に回す。

## 0.1.4 (2026-11-18)
- guard: git の `--output` / `--ext-diff` / `-c <pager等>=` を拒否(読み取り系 allow を経由した書き込み・外部実行を防止)。
- settings 生成: allow をサブコマンド完全一致に(`git diff*` が `git difftool` に一致していた)、deny に git `--output` / `--ext-diff` を追加。既存プロジェクトの settings.json は自動更新されないので、必要なら手で合わせる。

## 0.1.3 (2026-11-18)
- doctor: setup 済みの `devaccel:filled` 目印を未記入と誤判定していたのを修正。

## 0.1.2 (2026-11-18)
- guard: `.env*` / `{.env,}` / `.env>x` / `.e*` などワイルドカード・波括弧・リダイレクト経由の .env 参照も拒否。

## 0.1.1 (2026-11-18)
- guard: 内部エラー時は許可せず確認に倒す / 不正なカスタム正規表現で組み込み規則が無効にならない / クォート・長いフラグ・`+refspec` push・コマンドを問わない .env 参照に対応。best-effort であることを明記。
- update/doctor: `.claude/` 外を指すロック行を無視(パス・トラバーサルによる削除を防止)。

## 0.1.0 (2026-11-18)
- 初版: guard / stop_gate フック、setup・tune・design・verify-app スキル、Python プリセット(ruff/pyright/pytest)、install・update・doctor。
