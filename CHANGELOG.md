# Changelog

## 0.8.0 (2026-11-18)
実測(D14)にもとづき、検証を「人が見ていない境界」に絞る(D15)。
- ゲート: 対話セッションの既定を `off`、/batch の単位(worktree)は新設の `gate.unit_mode`(既定 `enforce`)。記録に `scope`。`promote`(observe→enforce の昇格)を削除。既存プロジェクトの `observe` には doctor が off を案内。
- seed CLAUDE.md を 15 行に(進め方・検証は 6 行)。S/M の作法、ゲートの説明、/batch・PR・Bash の注意を削除。
- 新スキル `devaccel-batch`(手動): 4 件以上の独立 S/M を、コンテキストパックと単位向けの注意(Bash は単純に・最後に devaccel-pr)を付けて `/batch` に渡す。
- verify-app の起動条件を「PR の前、または入口を通るテストが無い変更」に。
- Codex 併用オプションを削除。
- bench: devaccel 条件で enforce を強制しない。`devaccel-nosandbox` / `devaccel-enforce` 条件を追加。

## 0.7.2 (2026-11-18)
- **修正(0.6.0 の退行)**: `Read(/.venv/**)` と `Read(/uv.lock)` の deny を削除。サンドボックスでは Read deny がファイルシステムの読み取り禁止になり、git(マージ時の stash)や uv が uv.lock を読めず失敗した。Read deny は秘密情報専用とする。既存プロジェクトは settings.json から手で削除(doctor が警告)。

## 0.7.1 (2026-11-18)
- /batch の単位が PR まで届かなかった件(0/3)の修正: `.claude/` 配下への Write は常に確認が要るため、PR メモとコミットメッセージの置き場を `.devaccel/`(gitignore、install が追記、doctor が点検)へ。seed CLAUDE.md に「Bash は単純なコマンドを 1 つずつ、ファイルは Write/Edit」(単位がヒアドキュメントや for ループでテストを書こうとして拒否されていた)。

## 0.7.0 (2026-11-18)
fable の改善計画(短期)より。
- seed CLAUDE.md: verify-app を規模依存に(S で追加テストが入口を通るなら省略可。PR は常に必須)。実測で devaccel のターン増の主因と推定。
- 振り分けの欠陥注入テスト: 検査失敗・テスト削除/行削除・skip・risky・検証基盤・未チェックの受け入れ条件・実動作確認なしの 8 種がすべて needs-human、無害な変更は evidence-ok。
- 非 Python: check.sh が空なら doctor が problem を出し、`/devaccel-setup` が package.json / Makefile / Cargo.toml / go.mod から段を提案。
- bench: stream-json でツール別呼び出し回数を記録、アブレーション条件(`devaccel-noverify`, `devaccel-gateonly`)、`summarize.py`。
- LICENSE(MIT)、README に実測の正直な結果と「何でないか」。

## 0.6.5 (2026-11-18)
- devaccel-pr スキル: `$(mktemp)`・変数・ヒアドキュメントを使わない手順に(展開を含む Bash は確認なしで許可されず、/batch の単位では拒否されて 3 単位中 2 単位が PR 前に止まった)。メモは Write で `.claude/state/pr-notes.md`、コミットは `git commit -F .claude/state/commit-msg.txt`。

## 0.6.4 (2026-11-18)
- **修正(0.6.0 の退行)**: `Read(/.claude/worktrees/**)` の deny を削除。Read deny は Edit も止めるため、/batch の単位が自分の worktree を編集できず全滅した。既存プロジェクトは settings.json から手で削除。
- ゲートの記録と状態を本体(trusted root)に書く。単位の worktree に書いていたため、worktree の片付けと一緒に消えていた(ゲート自体は単位内で動いていたことを実機の SubagentStop 入力で確認)。記録に `branch` を追加し、PR スクリプトは自分のブランチの判断依頼だけを数える。

## 0.6.3 (2026-11-18)
- settings 生成: `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`(/batch の単位・Explore などサブエージェントの既定モデル)。既存プロジェクトは settings.json の env に手で追加。

## 0.6.2 (2026-11-18)
- ゲート・PR スクリプト・bench: check.sh を別の木に向けるとき、パスをシェル本文に埋め込まず環境変数 `DEVACCEL_ROOT` で渡す(worktree 名によるコマンド注入の対策)。

## 0.6.1 (2026-11-18)
- 0.6.0 の退行を修正: worktree を検査対象にした際、guard の lock 照合・ゲートの設定・check.sh まで worktree(単位が書き換えられる)から読んでいた。信頼の基準 `trusted_root()`(本体)と検査対象 `project_root()`(worktree)を分け、lock・project.json・check.sh は常に本体から。settings 生成の ask に worktree 内の検証基盤(`**/scripts/check.sh` ほか)を追加。

## 0.6.0 (2026-11-18)
- **修正: /batch の単位内でゲートが動いていなかった**。単位はサブエージェントなので終了は `SubagentStop`(未登録だった)。さらに `CLAUDE_PROJECT_DIR` は worktree 内でも本体を指すため、発火しても本体の木を検査していた。settings 生成に `SubagentStop` を追加し、ゲートは hook の `cwd` が同じリポジトリの worktree ならそちらを検査、ラウンドは `agent_id` ごと。既存プロジェクトは settings.json に手で追記(doctor が表示)。
- トークン削減(fable の調査より): seed CLAUDE.md の /batch 規則を「独立 S/M が 4 件以上のときだけ、先に fetch、各単位にコンテキストパック(編集ファイル・参照・受け入れ条件・テスト・範囲外)」に。settings 生成で `.claude/worktrees/**`・`.venv/**`・`uv.lock` の Read を deny。

## 0.5.4 (2026-11-18)
- `protect.sh`(新規、人が実行): base ブランチに GitHub のブランチ保護を設定(直接・force push・削除の禁止を管理者にも、PR 必須、CI `check` 必須)。非公開リポジトリの無料プランでは使えない旨を表示。必須チェックは GitHub Actions アプリに固定(トークンで投稿した commit status では満たせない)。
- doctor: ブランチ保護の状態(on / off / unavailable)を表示。

## 0.5.3 (2026-11-18)
- guard: 疑似端末ラッパー(script / unbuffer / expect / empty / socat)を拒否(land の端末確認を偽装できたため)。`.claude/hooks/` を含むコマンドでのワイルドカード・ブレース展開と `cd .claude/hooks` を拒否(名前をぼかした実行の対策)。

## 0.5.2 (2026-11-18)
- guard: devaccel_pr/land を名指しするコマンドは、読むだけのコマンド同士以外へのパイプを拒否(`cat … | python3 -` 対策)。`--merge` の検出は改行をまたいでも効く。

## 0.5.1 (2026-11-18)
- guard: devaccel_pr/land を名指しする区切りのうち、読むだけの除外を実行手段を持たないコマンド(cat/head/tail/wc/ls/grep/git diff 等)に限定。`devaccel_land` と `--m…` はコマンドのどこにあっても拒否。
- tests/bench: 素の Claude Code と devaccel の比較ベンチ(配布対象外)。

## 0.5.0 (2026-11-18)
- 並列 PR の統合 `devaccel_land.py`(新規、人が実行): `evidence-ok` の PR を最新 base 上で 1 本ずつ合わせて base の `check.sh full` を再実行し、衝突・統合後の失敗を `needs-human` に降格。`--merge` で通過分を squash merge(検証した木と一致を確認)、`--dry-run`。guard は Claude からの `--merge` を拒否し、land も lock 照合の対象に。
- devaccel_pr.py: base の最新を fetch してから判定、本文に検証時の base/head を記録、既存 PR があれば本文とラベルを更新、docs 未変更を表示(判定には使わない)。リポジトリ名は insteadOf 展開前の origin 設定から取る。
- land は PR 本文末尾の証拠マーカーの head と現在の head が一致する PR だけを扱い、PR 自身の差分(merge-base から)で静的判定をやり直す。フォークの PR は扱わない。`--merge` は対話端末での確認入力が必須、guard は land を `python3 .claude/hooks/devaccel_land.py [--dry-run]` の形だけ許可。PR の再実行による `needs-human` の解除は、ブランチが最新の base を取り込んだ後だけ。
- seed CLAUDE.md: /batch の単位はファイルが重ならないよう切り、docs は振る舞いを変えた単位が更新する。devaccel-pr スキル: 降格されたら merge origin/base → push → 再実行。

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
