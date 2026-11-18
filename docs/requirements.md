# devaccel 要求仕様

対象: devaccel 0.11.0(初版は 0.8.4 時点。0.9.0・0.10.0 の監査で追記)。作成 2026-11-18。
出典: README.md、docs/design.md(D1〜D15)、CHANGELOG.md、seed/CLAUDE.md、各 SKILL.md、kit/devaccel.py、core/.claude/hooks/*.py。tests/ は読まずに書いた(テストとの対応付けは別の担当が独立に行う)。

## 1. 前提

### 1.1 範囲

devaccel は Claude Code 用のプロジェクト配布型キットである。この文書は、キットが導入先プロジェクトに対して保証しなければならないことを、検証できる形で並べる。対象は次の 5 つ。

- キット本体: `install.sh` / `update.sh` / `doctor.sh` / `protect.sh`(実体は `kit/devaccel.py`)
- core 層: `guard.py`、`stop_gate.py`、`devaccel_pr.py`、`devaccel_land.py`、`devaccel_report.py`、`devaccel_common.py`、スキル `devaccel-{setup,tune,batch,pr}`
- project 層の初期値: `CLAUDE.md`、スキル `design` / `verify-app`、`scripts/check.sh`、`.claude/project.json`、`.claude/settings.json`、`.github/workflows/check.yml`
- 対話セッションでのオーバーヘッド
- Python 以外のプロジェクトでの最低限の挙動

### 1.2 利用者

- 個人開発と軽い実務。Python 中心、WSL2 / Linux。
- 導入先プロジェクトは、キットを持たない他の人と CI も使う。`.claude/` ごとコミットされた clone だけで同じ担保が効くこと(D8)。

### 1.3 目標(評価軸)

1. トークン削減(ユーザーの目標。実測では対話のトークンは減っておらず、キットの価値は無人経路の検証に絞った。D14・D15)
2. 正確さ
3. 高速開発
4. 多様なプロジェクトへの対応と、配布後の変化への追随

### 1.4 信頼モデル

| 対象 | 扱い |
|---|---|
| 本体チェックアウト(main checkout) | 信頼の基準(trusted root)。lock、`project.json`、`scripts/check.sh` は常にここから読む |
| /batch の単位(linked worktree) | 検証基盤については信頼しない。単位は自分の木の `project.json`・`check.sh`・フックを書き換えられる前提で設計する |
| エージェント(Claude) | 検証基盤については信頼しない。自分の変更を自分で通す経路を作らない |
| 本当の境界 | OS レベルのサンドボックスと、GitHub のブランチ保護 |
| guard | 文字列判定の best-effort。うっかりを止めるもので、意図的な回避は防げない |

### 1.5 読み方

- ID は `領域-番号`。文は「〜しなければならない(MUST)」「〜してはならない(MUST NOT)」。
- 根拠は design.md の決定番号(D)か CHANGELOG の版。版が書いてある要件は、その版で直した退行が再発しないことを意味する。
- 検証レベルは、違反を実際に捕まえられる最も安い段を選んだ。

| レベル | 意味 |
|---|---|
| unit | 関数・スクリプトを直接呼ぶ。git は一時リポジトリ程度、外部ツールは偽物でよい |
| integration | 本物の git・uv・ruff・pyright・pytest を使う。Claude Code は使わない |
| e2e-smoke | 本物の Claude Code とサンドボックスを動かす(有料・リリース前) |
| bench | vanilla との比較計測(`tests/bench/`) |
| manual | 人の操作、または本物の GitHub が必要 |

## 2. 要件

### 2.1 INSTALL

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| INST-01 | install は core の全ファイルを導入先にコピーし、各ファイルの sha256 とキットの version / ref を `.claude/devaccel.lock` に記録しなければならない。 | D9 | unit |
| INST-02 | install は、既に存在する project 層のファイル(seed 由来のファイル、`project.json`、`check.sh`、`check.yml`、`settings.json`)を上書きしてはならず、残したファイルを一覧表示しなければならない。 | D9、README | unit |
| INST-03 | install は、lock が既にある場合、または core と同じパスに内容の異なるファイルがある場合、lock を書かずに終了コード 1 で止まらなければならない。 | D9 | unit |
| INST-04 | 既存の `settings.json` がある場合、install はそれをマージ・変更してはならず、フックが未配線なら追記すべき設定を表示しなければならない。 | D9 | unit |
| INST-05 | install は `.gitignore` に不足している行(`.claude/state/`、`.claude/settings.local.json`、`.claude/worktrees/`、`.devaccel/`、`__pycache__/`)だけを追記し、既存の行を消したり重複させたりしてはならない。 | 0.3.0、0.7.1 | unit |
| INST-06 | install は Python プロジェクトを検出したとき、`presets=["python"]` の `project.json`、実行可能な `scripts/check.sh`(runner は uv か PATH)、対応する CI ワークフローを生成しなければならない。 | D10 | unit |
| INST-07 | 生成された `check.sh full` は、本物の ruff・pyright・pytest で lint エラー・型エラー・テスト失敗を非 0 で検出し、ファイルを変更せず、`.claude/` 配下を整形・lint の対象にしてはならない。ツールが無い段は full で失敗、fast で `missing`、テスト 0 件は成功としなければならない。 | D3、README「開発」 | integration |
| INST-08 | キットと core のスクリプトは python3 3.10 以上の標準ライブラリだけで動かなければならず(CI で 3.10 と 3.12 を回す)、導入後のプロジェクトはキットの clone 先のパスに依存してはならない(clone だけで他の人・CI が動かせる)。 | D5、D8 | integration |

### 2.2 UPDATE

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| UPD-01 | lock のハッシュと異なる core ファイルが 1 つでもあれば、update は何も変更せず、差分を表示して終了コード 1 で止まらなければならない。lock が無い場合も同じく止まる。 | D9 | unit |
| UPD-02 | update は core ファイルと lock 以外(`CLAUDE.md`、`check.sh`、`project.json`、`settings.json`、seed 由来のスキル、local 層)を変更してはならない。seed との差は案内だけにする。 | D9 | unit |
| UPD-03 | update は全ファイルを staging してから置換し、staging が失敗したら導入先を変更してはならない。成功後の lock は新しい core 全ファイルのハッシュと一致しなければならない。 | D9 | unit |
| UPD-04 | 新しいキットに無くなった core ファイルの削除は `.claude/` 内の通常ファイルに限り、lock の行が `.claude/` 外・絶対パス・`..`・シンボリックリンクを指す場合は無視して警告しなければならない。 | 0.1.1 | unit |

### 2.3 DOCTOR / PROTECT

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| DOC-01 | doctor は problem が 1 つ以上あれば終了コード 1、無ければ `OK` と 0 を返し、導入先のファイルを変更してはならない。 | README | unit |
| DOC-02 | doctor は core ファイルの欠落と手編集(lock とのハッシュ不一致)を problem として報告しなければならない。 | D9 | unit |
| DOC-03 | doctor は guard / stop_gate / `SubagentStop` の未配線を problem(終了コード 1)とし、`SubagentStop` には追記すべき設定を示さなければならない。 | 0.6.0, 0.9.0 | unit |
| DOC-09 | doctor は devaccel の core(`.claude/hooks`・`.claude/skills`・lock)が未コミットなら problem にしなければならない(/batch の worktree は HEAD から作られ、ロックと合わずに PR 手順が拒否される)。 | 0.9.0 | unit |
| DOC-10 | doctor は、フックの配線を構造で判定し(PreToolUse の matcher が Bash で guard、Stop に stop_gate)、permissions.deny の必須項目(`Read(**/.env)`、`Bash(gh *)`、force push)と sandbox の denyWrite の欠落を problem にしなければならない。doctor はプロジェクト内のスクリプトを実行してはならない(キット側の report を `-I` で実行)。 | 0.10.0 監査 | unit |
| DOC-04 | doctor は次を problem として報告しなければならない: サンドボックス無効、bubblewrap / socat の欠如、`~/` で始まりグロブ `**` を含む `denyRead`、`Read(/uv.lock)`・`Read(/.venv/**)`・`Read(/.claude/worktrees/**)` の deny、`Bash(git push*)` の ask、許可ドメインに `api.github.com` が無いこと。 | 0.2.0、0.4.0、0.6.4、0.7.2、0.8.1 | unit |
| DOC-05 | doctor は次を problem として報告しなければならない: `check.sh` の欠如・実行不可、`.claude/state/` と `.devaccel/` が gitignore されていないこと、`CLAUDE.md` の行数が `budget.claude_md_max_lines` を超えていること、Python プリセットで ruff・pyright・pytest が見つからないこと。 | 0.7.1、D10 | unit |
| DOC-06 | doctor は未記入の `devaccel:fill` 目印を表示し、記入済みの `devaccel:filled` を未記入と判定してはならない。 | 0.1.3 | unit |
| DOC-07 | doctor はゲートのモード(session / unit)、`gate.mode=observe` への off の案内、`DEVACCEL_GATE_MODE` の個人上書き、信頼ダイアログ未承認、ブランチ保護の状態、ゲート統計を表示しなければならない(problem にはしない)。 | 0.4.0、0.5.4、0.8.0 | unit |
| DOC-08 | protect は人が `yes` と入力した場合に限り GitHub の設定を変更し、その内容は「直接・force push と削除の禁止(管理者も)、PR 必須(承認数 0)、GitHub Actions アプリに固定した `check` 必須、strict なし」でなければならない。 | 0.5.4、D12 | unit(gh を偽装)+ manual |

### 2.4 SETTINGS(install が生成する `.claude/settings.json`)

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| SET-01 | サンドボックスは `enabled`、`failIfUnavailable`、`autoAllowBashIfSandboxed` が true、`allowUnsandboxedCommands` が false でなければならない。 | 0.2.1、0.4.0 | unit |
| SET-02 | `denyRead` はプロジェクト内の `.env` 系と、ホーム直下の秘密(`~/.ssh`、`~/.aws`、`~/.gnupg`、`~/.netrc`、`~/.docker/config.json`、`~/.kube`、`~/.npmrc`、`~/.pypirc`)を直接パスで含まなければならず、`~/` で始まるグロブと `~/.config/gh` を含んではならない。 | 0.8.1、0.8.2、D12 | unit |
| SET-03 | permissions の `Read` / `Edit` の deny は秘密(`.env` 系)だけに限り、`uv.lock`・`.venv`・`.claude/worktrees` など git・uv・worktree の動作に必要なパスを含んではならない。 | 0.6.4、0.7.2 | unit |
| SET-04 | allow の git と `check.sh` は引数まで完全一致の読み取り形だけとし、`git diff *` のような末尾ワイルドカードを含んではならない。deny は git の `--out*` / `--ext*`、`gh *`、force push、remote の add / set-url を含まなければならない。 | 0.1.4、0.1.6、0.1.9、0.4.0 | unit |
| SET-05 | 並列 PR の経路(`git add *`、`git commit *`、`git push origin HEAD`、`python3 .claude/hooks/devaccel_pr.py *`)は allow に含まれ、`Bash(git push*)` の ask を含んではならない。 | 0.4.0 | unit |
| SET-06 | 検証基盤(`scripts/check.sh`、`.claude/hooks/**`、`.claude/settings.json`、`.claude/project.json`、`.github/workflows/**`)の Edit は、本体と worktree 内(`**/` 形)の両方で ask でなければならない。 | D6、0.6.1 | unit |
| SET-07 | フックは PreToolUse(Bash) に guard、`Stop` と `SubagentStop` の両方に stop_gate を、`python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/…` の直接起動(`uv run` なし)で配線しなければならない。 | D5、0.6.0 | unit |
| SET-08 | 許可ドメインは `github.com` と `api.github.com` を常に含み、Python プリセットでは PyPI 2 ドメインと `registry.npmjs.org`、およびツールキャッシュ(`~/.cache/uv` ほか)への書き込み許可を含まなければならない。env は同時サブエージェント数 3、サブエージェントのモデル `sonnet` を設定しなければならない。 | 0.3.2、0.4.0、0.6.3、D11 | unit |
| SET-09 | 生成された設定の下で、本物の Claude Code のサンドボックス内から `uv run`・`git stash` / merge・worktree 内のファイル編集が拒否されずに動かなければならない。 | 0.3.2、0.6.4、0.7.2 | e2e-smoke |
| SET-10 | 生成された設定の下で、サンドボックス内の Bash からプロジェクトの `.env` と `~/.ssh` を読めてはならない。 | D5b | e2e-smoke |
| SET-11 | 生成された sandbox は `filesystem.denyWrite` で本体の `.claude/hooks`・`.claude/skills`・`.claude/state`・lock・`project.json`・`settings.json`・`scripts/check.sh` を守り、`.claude/worktrees/` は書き込み可のままでなければならない。 | 0.10.0 監査 | unit |

### 2.5 GATE(`stop_gate.py`)

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| GATE-01 | 既定の設定では、本体チェックアウトのセッションでゲートは `check.sh` を実行せず、何も出力せずに 0 で終わらなければならない(`gate.mode=off`)。`observe` はブロックせず `would_block` を記録するだけでなければならない。 | D15 | unit |
| GATE-02 | 検査対象が linked worktree(git-dir ≠ git-common-dir)のとき、ゲートは `gate.unit_mode`(既定 `enforce`)を適用しなければならず、判定はシンボリックリンクやパスの大小文字に左右されてはならない。 | D15、0.8.3 | integration |
| GATE-03 | ゲートは `project.json` と `scripts/check.sh` を常に trusted root から読み、worktree 内のそれらを書き換えても判定(モード、閾値、検査内容)が変わってはならない。 | 0.6.1 | integration |
| GATE-04 | ゲートは `CLAUDE_PROJECT_DIR` が本体を指していても、フックの `cwd` が同じリポジトリの worktree ならその木を検査しなければならず、木のパスは環境変数 `DEVACCEL_ROOT` で渡し、シェル本文に埋め込んではならない(worktree 名でコマンドを注入できない)。 | 0.6.0、0.6.2 | integration |
| GATE-05 | `enforce` で `check.sh fast` が失敗したら、ゲートは `decision: block` を返し、理由には失敗した段の名前・その段の出力の末尾(40 行以内)・ラウンド数だけを含めなければならない。 | D4 | unit |
| GATE-06 | 失敗が `max_rounds` を超えて続いたら、ゲートは修正の停止とユーザーへの報告を指示し、`systemMessage` で人にも表示し、`escalate` を記録し、その木が変わらない限り以後はブロックしてはならない。 | D4 | unit |
| GATE-07 | `enforce` で失敗した木を変更せずに再停止しても、ゲートは通してはならず、同じ失敗を再提示してラウンドを数えなければならない。 | 0.8.3 | unit |
| GATE-08 | ゲートは次の場合に `check.sh` を実行してはならない: git の外、`skip_branches` に一致するブランチ、未コミットの変更が `gate.ignore`(docs・`*.md` 等)だけ、前回通過した木から変化なし。通過の記憶は fast の自動整形後の木に対して行わなければならない。 | D4 | unit |
| GATE-09 | `check.sh` の timeout は通過として記憶してはならず、未検証である旨を `systemMessage` と記録に残し、次の停止で再実行しなければならない。検査の上限はフックの timeout(120 秒)より短くなければならない。 | 0.8.3 | unit |
| GATE-10 | ゲートは、非 UTF-8 のファイル名・検査出力、壊れた状態ファイル、不正な `project.json` があっても例外で落ちず、`enforce` のブロック判定を失ってはならない。それでも起きた内部エラーはセッションを壊さず、stderr に明示しなければならない。 | 0.8.3 | unit |
| GATE-11 | ラウンドと状態は単位(`agent_id`)またはセッションごとの別ファイルに持ち、並列の単位が同時に停止しても互いのブロック・ラウンドを消してはならない。判定の出力は状態の保存より先でなければならない。 | 0.6.0、0.8.3 | unit |
| GATE-12 | 記録と状態は trusted root の `.claude/state/` に書き(worktree には書かない)、各記録は `branch`・`scope`(session / unit)・`mode`・`result` を含まなければならない。変更なしの再停止によるブロック / エスカレーションも記録しなければならない。 | 0.6.4、0.8.0、0.8.4 | unit |
| GATE-13 | L 相当の規模・リスクのあるパス・テスト削除・skip / xfail の追加は人向けの `systemMessage` で表示するだけとし、それを理由にブロックしてはならず、同じ種類の表示はセッションで 1 回に限らなければならない。 | D4 | unit |
| GATE-14 | trusted root の `check.sh` が無い、または認識できない `cd` 行を持つ場合、ゲートは別の木を検査してはならず、`missing` として記録しなければならない。 | 0.8.3 | unit |
| GATE-15 | `DEVACCEL_GATE_MODE` が `off` / `observe` / `enforce` のいずれかなら対話セッションの `mode` だけを上書きし(単位の `unit_mode` は上書きしない)、それ以外の値は無視しなければならない。 | README, 0.9.0 | unit |
| GATE-16 | 本物の Claude Code で /batch の単位(サブエージェント)が終了するとき、`SubagentStop` でゲートが発火し、単位の worktree を検査して本体に記録しなければならない。 | 0.6.0、0.6.4、D13 | e2e-smoke |
| GATE-17 | ゲートと land は check.sh を bubblewrap で隔離して実行しなければならない: 作業ツリー以外は読み取り専用、作業ツリーの `.git` と本体の検証基盤も読み取り専用、`$HOME` は許可リスト(ツールチェーンは読み取り専用、ツールのキャッシュのみ書き込み可)、`.env` は隠し、環境変数は最小限。bwrap が無ければ未検査として表示しなければならない(素の権限で実行してはならない)。 | 0.10.0 監査 H1 | unit |
| GATE-18 | 作業単位は、ブランチ名(`spike/*`)や worktree の `.git` リンクの破壊でゲートを止められてはならない。判定前後で同じ「検査対象」の定義を使い、コミット済みの変更でエスカレーション後もブロックし続けてはならない。 | 0.10.0 監査 | unit |

### 2.6 GUARD(`guard.py`)

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| GRD-01 | guard は、広範囲を対象にした `rm -rf`(`/`、`~`、`$HOME`、`*`、`.`、`..`、`.git`。引用符つきを含む)、`sudo`、ダウンロードしたスクリプトのシェルへのパイプを deny しなければならない。 | D5b | unit |
| GRD-02 | guard は、force push(`--force`、`-f`、`+refspec`)、`git -c` による外部コマンド指定(pager・editor・alias 等)、diff / log / show 等での `--output` / `--ext-diff` とその省略形を、バックスラッシュや `${IFS}` で崩した形でも deny しなければならない。 | 0.1.4〜0.2.1 | unit |
| GRD-03 | guard は `git add -A` / `.`、`git reset --hard`、`git clean -f`、`git checkout .`、`DROP TABLE` 等、および展開を含む git diff / log 等を ask にしなければならず、git の ask 規則は区切りの先頭にだけ当て、ヒアドキュメント本文や文字列中の語で発火してはならない。 | 0.3.0、0.4.0 | unit |
| GRD-04 | push は、作業ブランチ上での単独の `git push origin HEAD` だけを通し、main / master / `base_branch` / origin の既定ブランチ / detached HEAD からの push、他リモート・他 refspec、`cd`・`git -C`・`GIT_DIR=` との併用、リモートや push・credential 設定の変更を deny しなければならない。 | 0.4.0 | unit |
| GRD-05 | `gh` の直接実行は、区切りの途中・環境変数の前置き・`timeout` 等のラッパー越しでも deny し、`bash -c`・`eval`・`xargs`・`python -c`・`find -exec` 等と git / gh の組み合わせも deny しなければならない。 | 0.4.0、0.4.1 | unit |
| GRD-06 | `devaccel_pr.py` の実行は `python3 .claude/hooks/devaccel_pr.py …` の形で単独(同じコマンドに並べてよいのは読むだけのコマンドのみ)に限り、環境変数の代入・`export`・`alias`・`source`・関数定義・`cd`・他コマンドへのパイプと並べた形を deny しなければならない。 | 0.5.1、0.5.2、0.8.3、0.8.4 | unit |
| GRD-07 | `devaccel_land.py` は引数なしか `--dry-run` の形だけを通し、`--merge` とその省略形(`--m…`)はコマンド内のどこにあっても(改行をまたいでも)deny しなければならない。 | 0.5.0〜0.5.2 | unit |
| GRD-08 | PR / land スクリプトの実行は、実行する木の `devaccel_pr.py`・`devaccel_land.py`・`devaccel_common.py`・`stop_gate.py` が trusted root の lock のハッシュと一致するときだけ通し、lock が無い・読めない場合は deny しなければならない。guard の設定と lock は worktree から読んではならない。 | 0.4.0、0.6.1 | unit |
| GRD-09 | guard は疑似端末ラッパー(`script`、`unbuffer`、`expect`、`empty`、`socat`)と、`.claude/hooks/` を指すワイルドカード・ブレース展開、`cd .claude/hooks` を deny しなければならない。 | 0.5.3 | unit |
| GRD-10 | guard は内部エラー時に許可してはならず(ask に倒す)、`project.json` の不正な正規表現で組み込み規則を無効にしてはならず、有効な `guard.deny_regex` / `ask_regex` は適用しなければならない。 | 0.1.1 | unit |
| GRD-11 | guard は通常の開発コマンド(具体的なパスの `rm -rf`、`git commit -F`、`2>&1`、検査語を含む引用符つき文字列やヒアドキュメントでのファイル作成、`.env` という語を含むだけのコマンド)を deny / ask にしてはならない。 | 0.1.12、0.2.0、D5b | unit |
| GRD-12 | guard は PR/land スクリプトの横(作業単位の `.claude/hooks/`)に lock 外のファイル(`json.py` 等、`__pycache__`)があれば実行を拒否しなければならない(モジュールのすり替え)。(sys.path の順序はスクリプト実行では防御にならないため、余剰ファイルの拒否と sandbox の denyWrite で守る。) | 0.10.0 監査 H3 | unit |

### 2.7 PR(`devaccel_pr.py`)

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| PR-01 | 未コミットの変更がある、ブランチが main / master / `base_branch` / detached HEAD、origin が github.com でない、HEAD が未 push、のいずれかなら、PR を作らず終了コード 2 で止まらなければならない。 | 0.4.0 | integration |
| PR-02 | PR 本文はスクリプトが機械的に組み立て、振り分けラベルと理由、`check.sh full` の結果と段、変更規模、実動作確認の記録、設計書と受け入れ条件、失敗時の出力末尾を含まなければならない。 | D11 | unit |
| PR-03 | 検査は base(merge-base)の `scripts/check.sh full` をブランチの木に対して実行したものでなければならず、ブランチ側で `check.sh` を弱めても結果に影響してはならない。設定は trusted root から読み、判定の前に origin の base を fetch しなければならない。 | 0.3.1、0.5.0、0.8.3 | integration |
| PR-04 | 次のいずれかに当たる PR は理由つきで `needs-human` にしなければならない: (a) base の `check.sh full` が失敗・timeout・欠如、(b) 実動作確認の記録が空、(c) 変更ファイル数が `large_if_files_over` 超、(d) `risky_paths` に一致、(e) テストファイルの削除、(f) 既存テストの行削除、(g) skip / xfail の追加、(h) 同じブランチでゲートがエスカレーションを記録、(i) 変更した設計書に未チェックの受け入れ条件。 | 0.3.1、0.7.0、0.6.4 | integration |
| PR-05 | 検証基盤(`scripts/check.sh`、`.claude/**`、`.github/**`、`CLAUDE.md`、`AGENTS.md`、`conftest.py`、`pytest.ini`、`setup.cfg`、`tox.ini`、`pyrightconfig.json`、`ruff.toml`、`pyproject.toml`(0.10.0 以降は変更すべて。入れ子の同名ファイルと `.gitattributes` も)に触れる PR は、`project.json` の内容にかかわらず常に `needs-human` にしなければならない。 | 0.3.1、D6 | integration |
| PR-06 | PR-04・PR-05 のどれにも当たらない変更(S / M 規模、テストは追加のみ、確認の記録あり、検査通過)は `evidence-ok` にしなければならない。docs 未更新は表示だけで判定に使ってはならない。 | 0.7.0、D12 | integration |
| PR-07 | `--verify-notes` は、リポジトリ内か一時ディレクトリにある 4096 バイト以下のファイルだけを受け付け、`.env*` という名前・認証情報らしい内容・存在しないファイルは明確なエラーで拒否しなければならない。 | 0.4.0、0.8.3 | unit |
| PR-08 | 本文の最終行は `<!-- devaccel:evidence base=<sha> head=<sha> -->` でなければならず、記録や受け入れ条件に含まれる同じ文字列は無害化して、偽のマーカーを作れないようにしなければならない。 | 0.5.0 | unit |
| PR-09 | 同じブランチに open の PR があれば新しく作らず本文とラベルを更新し(反対のラベルは外す)、その PR がフォーク由来・base 不一致・head 不一致なら更新せず終了コード 2 で止まらなければならない。 | 0.5.0 | unit(gh を偽装) |
| PR-10 | 既存 PR が `needs-human` で、ブランチが最新の base を取り込んでいない間は、再実行しても `evidence-ok` に戻してはならない。 | 0.5.0 | integration(gh を偽装) |
| PR-11 | `--dry-run` は GitHub を一切変更せず本文とラベルを出力しなければならず、`gh` の呼び出しは origin の設定から得た `-R owner/repo` に固定しなければならない。自動マージは既定で無効、有効でも `evidence-ok` かつ base に必須ステータスチェックがあるときだけ設定しなければならない。 | 0.3.1、0.4.0、D11 | unit(gh を偽装) |
| PR-12 | 振り分けはリネーム・非 ASCII のパス・ファイル種別の変更・`.gitattributes` による差分抑止に影響されてはならない。ツール/テスト設定ファイル(`pyproject.toml`、`.gitattributes`、入れ子の ruff/pytest/pyright 設定ほか)の変更はすべて needs-human。pytest を使う check.sh で 1 件も passed が無ければ失敗扱い。PR 本文に認証情報らしき文字列が入るなら作成を拒否しなければならない。自動マージは検証した head に固定しなければならない。 | 0.10.0 監査 H2/H5 | unit |
| SHIP-01 | `devaccel_ship.py` は 1 回の実行で、追跡済みの変更と `--paths` の新規ファイル(`-A` はしない)をコミットし、作業ブランチを origin へ push し、`devaccel_pr` と同じ証拠・振り分けで PR を作成/更新しなければならない。題名は `ship.md` の 1 行目、確認メモは 2 行目以降(`--verify-notes` と同じ制限)。 | 0.11.0 | unit |
| SHIP-02 | ship は main/master/base/origin HEAD/detached では何もコミット・push してはならない。push 先は origin の同名ブランチだけで、force してはならない。`--paths` はリポジトリ内の相対パスに限る。 | 0.11.0 | unit |
| SHIP-03 | `--units` は各単位のローカルブランチを `--no-ff` で統合し、衝突した単位は外して PR 本文に明記し、統合後の木に対して base の check.sh を 1 回だけ実行しなければならない。 | 0.11.0 | unit |
| SHIP-04 | 統合した PR の振り分けは単独の PR と同じ規則でなければならない(単位数で L 規模の基準を緩めない。ユーザー方針「検査の線は緩めない」、0.11.0 の緩和は撤回)。 | 0.11.0 | unit |
| SHIP-05 | guard は ship を `python3 .claude/hooks/devaccel_ship.py …` の単独実行・展開なし・lock 一致の場合だけ許可しなければならない(PR スクリプトと同じ扱い)。 | 0.11.0 | unit |
| SHIP-06 | `--branch` は保護ブランチ上でだけ、origin/<base> から作業ブランチを作って切り替えなければならない(main 自体は動かさない)。保護ブランチ名・不正な名前は拒否。 | 0.11.0 | unit |
| BATCH-01 | `devaccel_batch.py` は単位ごとに `<main>/.claude/worktrees/<x>` を作り、`claude -p` を同時に起動し、Claude Code の中(`CLAUDECODE`)からの実行は拒否しなければならない。 | 0.12.0 | integration |
| BATCH-02 | 単位を統合するのは、コミットがあり、かつゲートがその単位のブランチで `scope: unit` の pass を記録したものだけでなければならない。 | 0.12.0 | integration |
| BATCH-03 | スクリプトのコミットは本体側の git dir を明示し、フック・fsmonitor を無効にし、秘密情報らしいファイルと `.claude/`・`.devaccel/` を含めてはならない。 | 0.12.0 | unit |
| BATCH-04 | ゲートは単位の worktree の `.git` を(git を使わず)ファイルとして読み、`<anchor>/.git/worktrees/<x>` を指し、git の最上位が worktree そのものであるときだけ git を動かさなければならない。それ以外は block。 | 0.12.0 | unit |
| BATCH-05 | 同時に走らせる単位の数は固定値であってはならない。`--jobs` > `project.json` の `parallel.max_jobs` > 実行時のマシン(空きメモリ × 0.8 ÷ `parallel.unit_mem_mb`、CPU 数 × 2)の順に決め、決めた数と根拠を表示しなければならない。 | 0.12.1(ユーザー方針) | unit |

### 2.8 LAND(`devaccel_land.py`)

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| LAND-01 | land が扱うのは、base が `base_branch` で open かつ `evidence-ok` の、フォーク由来でない PR だけでなければならず、順序はコードを含む PR を番号順、docs だけの PR を最後としなければならない。 | D12、0.5.0 | unit |
| LAND-02 | 本文末尾のマーカーの head が現在の head と一致しない PR、および PR 自身の差分(merge-base から)で静的判定をやり直して理由が出た PR は、検証せずに降格しなければならない。 | 0.5.0 | integration(gh を偽装) |
| LAND-03 | land は最新の `origin/<base>` から作った一時 worktree に PR を 1 本ずつ `merge --no-ff` し、衝突した PR はマージを取り消して降格し、残りの PR の検証を続けなければならない。 | D12 | integration(gh を偽装) |
| LAND-04 | land は各マージの後に base の `check.sh full` を統合後の木で実行し、失敗した PR(単独では緑・合わせると赤)は巻き戻して降格しなければならない。 | D12 | integration(gh を偽装) |
| LAND-05 | land はラベルを `needs-human` へ下げることしかしてはならず(昇格しない)、降格のときは理由と直し方を PR にコメントしなければならない。 | D12 | unit(gh を偽装) |
| LAND-06 | `--merge` が無ければマージしてはならず、`--dry-run` ではラベル・コメント・マージのいずれも変更してはならない。 | 0.5.0 | unit(gh を偽装) |
| LAND-07 | `--merge` は、標準入力と標準出力がともに端末で、人が `merge` と入力した場合に限り進み、端末でなければ終了コード 2 で何もせず止まらなければならない。 | 0.5.0、D12 | unit |
| LAND-08 | マージは `--squash --match-head-commit <検証した head>` で行い、マージ前に `origin/<base>` が想定から動いていたら止まり、マージ後の `origin/<base>` の tree が検証した tree と一致しなければ止まらなければならない。 | D12 | integration(gh を偽装) |
| LAND-09 | land は成功・失敗・中断のいずれでも一時 worktree を片付け、本体の作業ツリーと現在のブランチを変更してはならない。重なるファイルを持つ PR の組は最初に表示しなければならない。 | D12 | integration(gh を偽装) |
| LAND-10 | 本物の GitHub 上で、衝突する 2 本と独立した 1 本の PR に対する `--merge` が、独立した PR だけをマージし、残りを理由つきで `needs-human` に落とさなければならない。 | D12、D14 | manual |

### 2.9 SKILLS / CLAUDE.md

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| SKL-01 | 配布する常駐コンテキストは、`budget.claude_md_max_lines` 以内(0.8.0 以降は約 15 行)の seed `CLAUDE.md` と、モデルが起動できるスキル 3 件(`design`、`verify-app`、`devaccel-pr`)の説明だけでなければならない。`devaccel-setup` / `tune` / `batch` は `disable-model-invocation` とし、エージェント定義・rules ファイル・スキルの `model:` 指定を配布してはならない。 | D1、D2、D15、README | unit(静的検査) |
| SKL-02 | `devaccel-pr` と `devaccel-batch` が単位に実行させる Bash は、`$(...)`・`$変数`・ループ・ヒアドキュメント・`cd`・`&&` 連結を含まない単独コマンドでなければならず、スキル本文に書かれたコマンド例はすべて guard を通り、生成される allow に一致しなければならない。 | 0.6.5、0.7.1 | unit(スキルからコマンドを抜き出して guard と allow に当てる) |
| SKL-03 | PR メモとコミットメッセージの置き場は gitignore された `.devaccel/` とし、スキルは `.claude/` 配下へ Write させてはならない。 | 0.7.1 | unit(静的検査) |
| SKL-04 | `devaccel-batch` は、独立した S / M が 4 件以上の場合だけ `/batch` を使い(L は並列化しない)、各単位への指示にコンテキストパック・Bash の注意・「最後に devaccel-pr で PR にする」を必ず埋め込まなければならない。 | D13、D15 | unit(静的検査) |
| SKL-05 | seed `CLAUDE.md` は、検査を `check.sh` にまとめて個別のツールを回さないこと、L は design スキルで承認を得てから実装すること、テストを消す・skip することで通さないこと、同じ修正に 3 回失敗したら止まることを含まなければならない。 | D7、0.8.3 | unit(静的検査) |
| SKL-06 | 本物の Claude Code で、worktree の単位が確認待ち・拒否なしに、編集 → `check.sh` → コミット → `devaccel_pr.py --dry-run` の本文出力まで到達しなければならない。 | 0.4.0、0.6.5、0.7.1 | e2e-smoke |
| SKL-07 | `devaccel-setup` と `devaccel-tune` は変更を差分で示して承認後にだけ適用し、ゲートや検査を緩める変更は明示的な承認なしに適用してはならない。`--redetect` は人が書いた `CLAUDE.md` の文章を再生成してはならない。 | D10 | manual |

### 2.10 PERFORMANCE

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| PERF-01 | 既定設定の対話セッションで、小課題ベンチのコストは vanilla 比 +5% 以内でなければならない(超えたら常駐行をアブレーションで削る)。 | D15 | bench |
| PERF-02 | 同じ条件で、所要時間は vanilla 比 +10% 以内でなければならない。 | D15 | bench |
| PERF-03 | 同じ条件で、正確さ(隠しテストと `check.sh full` の通過)が vanilla を下回ってはならない。 | D14 | bench |
| PERF-04 | 生成された設定の下で、サンドボックス内の単純な Bash 1 回(`ls` 相当)に、ホームの大きさに比例する遅延があってはならない(目安 2 秒未満。数値は本書の提案で、0.8.1 の退行は 1 回 4〜15 秒)。 | 0.8.1 | e2e-smoke |
| PERF-05 | guard の 1 回の判定と、`off` のときの stop_gate は、`check.sh` を起動せず、それぞれ 0.5 秒未満で終わらなければならない(数値は本書の提案。D5 の実測は python3 起動 0.009 秒)。 | D5、D15 | integration |

### 2.11 NON-PYTHON

| ID | 要件 | 根拠 | 検証 |
|---|---|---|---|
| NPY-01 | Python を検出しないプロジェクトでも install は成功し、プリセットなしの `project.json`、Python 専用の allow・ドメイン・キャッシュを含まない `settings.json`、`no checks configured` を出す `check.sh` を生成しなければならない。 | D10 | unit |
| NPY-02 | `check.sh` が空(`no checks configured`)の間、doctor は「ゲートが何でも通す」ことを problem として報告しなければならない。 | 0.7.0 | unit |
| NPY-03 | ゲート・PR・land は `check.sh` の終了コードと `== stage / ok / failed / missing` の行だけに依存し、任意の言語のコマンドを並べた段の失敗を Python の場合と同じく検出しなければならない。 | D9 | integration |
| NPY-04 | `/devaccel-setup` は、`check.sh` が空のとき `package.json`・`Makefile`・`Cargo.toml`・`go.mod` から段と allow を差分で提案しなければならない。 | 0.7.0 | manual |

## 3. 受け入れたリスク(保証しないこと)

| ID | 保証しないこと | 根拠 |
|---|---|---|
| RISK-01 | guard は意図的な回避を防がない。文字列判定の正規表現は 0.1.10 と 0.5.3 で打ち止めにしている。 | D5b、D12 |
| RISK-02 | 「マージは人だけ」は完全には守れない。サンドボックス内からも gh の認証情報と `api.github.com` に届くため、緑の `needs-human` PR を Claude が API で直接マージしうる。完全にするには権限の弱い別アカウント / トークンが要る。 | D12 |
| RISK-03 | `~/.config/gh` はサンドボックス内から読める(PR 作成と push に必要)。 | D12 |
| RISK-04 | ホーム以下にある他のチェックアウトの `.env` は守らない(Bash 1 回ごとのホーム走査を避けるため)。 | 0.8.1、0.8.2 |
| RISK-05 | フックと Read / Edit ツールはサンドボックスの外で動く。Read ツール経由の秘密は permissions の deny だけが守る。guard は秘密を扱わない。 | D5b、README |
| RISK-06 | ブランチ保護が使えない環境(無料プランの非公開リポジトリ)では、guard と PR の振り分けだけが頼りになる。 | D12、README |
| RISK-07 | ブランチ保護に「承認必須」と strict(最新必須)は入れない。Claude が同じアカウントで動くためと、統合の検証は land が担うため。 | D12 |
| RISK-08 | 対話セッションには既定でゲートが無い。小さな対話作業での正確さの上積みは主張しない(実測で vanilla と同等)。 | D14、D15 |
| RISK-09 | ゲートはテストの弱体化(削除・skip)を表示するだけで止めない。assert 数の減少や期待値の書き換えは検出しない。 | D4、D6 |
| RISK-10 | `settings.json` は install 時に 1 回書くだけで、マージも自動更新もしない。既存プロジェクトの設定の退行は doctor の指摘を見て人が手で直す。 | D9 |
| RISK-11 | bubblewrap / socat が無い環境では Claude Code が起動しない。WSL1 とネイティブ Windows は対象外。 | D5、D5b、README |
| RISK-12 | Python 以外は検査の段を利用者が書く必要がある。 | README、D10 |
| RISK-13 | 単位の判定は「linked worktree かどうか」だけで、人が手で作った worktree での対話作業にも `unit_mode` が掛かる。 | D15 |
| RISK-14 | 並列の単位どうしでの docs の食い違いは検出しない(docs 未更新を表示するだけ)。 | D12 |
| RISK-15 | land は PR 数だけ `check.sh full` を直列に実行する(遅さは受け入れ、見直し条件としている)。 | D12 |
| RISK-16 | ベンチは各条件 1〜2 回で、差の大きさは不確か。 | D14 |

## 4. 文書とコードの食い違い(0.9.0 で決着)

要件の作成時に見つけた 12 件。どちらを正としたかと、対応した版。

| # | 内容 | 決定 |
|---|---|---|
| 1 | D15 の目標と README の数値が古い | README を 0.8.3 の実測(ほぼ同等、コスト +4〜10%)に更新。PERF-01/02 の目標は維持し、ベンチで追う。 |
| 2 | 単位がコミットしてから止まるとゲートが動かない | **コードを修正**: 単位では base に未マージのコミット済み変更も検査対象(GATE-05/08/16)。 |
| 3 | 「3 回で人へ」とコードの 4 回目 | **コードを正**: 3 回直しても通らなければ 4 回目の失敗で人へ。README・要件の文言を合わせた(GATE-06)。 |
| 4 | enforce で missing / timeout / 内部エラーが黙って通る | **コードを修正**: missing は enforce で表示、内部エラーは記録(result=error)、report は missing/error も集計。timeout は未検証として次回再実行+表示(従来どおり)。ブロックはしない(ループ防止)。 |
| 5 | land が実行した木の設定を読む | **コードを修正**: trusted root(本体)の設定。 |
| 6 | README の設定例に api.github.com が無い | README を修正。 |
| 7 | update が新しく core になるパスの利用者ファイルを黙って置き換える | **コードを修正**: 止めて一覧を出す。 |
| 8 | install が途中で止まると lock なしの core が残る | **コードを修正**: 衝突を全部調べてから書く。 |
| 9 | SubagentStop の未配線が doctor で表示だけ | **コードを修正**: problem(終了コード 1)。 |
| 10 | `DEVACCEL_GATE_MODE` が単位のゲートも止める | **コードを修正**: 対話セッションだけに効く。 |
| 11 | design.md・docstring の古い記述 | 修正(D1・D4・D5 に追記、guard の参照を D5b/D12 に)。 |
| 12 | force-with-lease のメッセージ、`-u` の扱い | メッセージを「禁止」に統一。スキルは「`-u` は不要」(guard は許可のまま)。 |

## 5. テストで見つかった挙動の扱い(0.9.0)

- GRD-03: ヒアドキュメント本文の行頭の `git add -A` も ask になる → **意図どおり**(規則は本文も見る。パーサの読み違いを作らない、0.1.x の教訓)。
- GRD-11: `echo "sudo"` が deny になる → **誤検知として受け入れ**(実害が小さく、引用の解釈を足すと抜け道の元になる)。0.10.0 で `git commit -m "..."` の(`$` やバッククォートを含まない)メッセージは判定から外した(「Add push docs」等の誤検知)。
- 未テスト: SET-09/10・GATE-16 の SubagentStop 実発火(e2e-smoke)、GATE-09 の 110 秒上限(実時間が要る)、DOC-07 のブランチ保護表示(gh ログインが要る)。


## 6. 0.10.0 の監査(公開前、独立 4 本)で受け入れたリスクの追記

- 隔離した check.sh からもネットワークには出られる(依存の取得に必要)。リポジトリのコードを外に送れる残余リスク(コードは GitHub にも上がる)。
- ツールのキャッシュ(`~/.cache/uv` 等)は書き込める(Claude Code のサンドボックスも同じ範囲を許可)。キャッシュ汚染は防がない。
- guard の正規表現の網羅は D12 のとおり打ち止め。境界はサンドボックス + ブランチ保護。
