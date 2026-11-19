# Changelog

## 0.14.0 (2026-11-19)
**ざっくりした依頼は設計書から**: 依頼が番号付きの仕様になっていなければ、Claude が `docs/design/` に設計書を書き、それをそのまま作業単位の指示書にしてファンアウトし、設計書も PR に入れる(人は判断一覧・例の表・証拠を見る)。
- 設計書の形(2 つのサーベイから): 規則 R#、ID 付きの例の表 E#-#、判断一覧 D#(既定と代替)、不変条件、長さの上限。書くときに「その拒否で弾かれる正当な入力は?」と領域別の端のチェック表で確かめる。
- 単位は例の表を ID ごとテストに写し、端のケースを洗い直さない。終了時のゲートが ID の抜けを差し戻し、ファンアウトがコミットに全 ID があるかを機械で確かめる(抜けた単位は統合しない)。
- 実測(ざっくりした 4 機能の依頼、伏せた採点・同じ 40 個の確認項目): 設計書なし 5〜5.5 点 → 初版の設計書 7.5〜8 → 改訂版の設計書 8〜9(34〜37/40)。時間 117〜128 秒 → 174〜265 秒、費用 $0.18〜0.21 → $0.29〜0.36。品質を優先して改訂版を採用。
- 試して戻したもの: 件ごとの並列設計者(sonnet)。設計の待ちは約 75 → 45 秒になったが、品質 4〜5 点(28〜30/40)・費用 +$0.10。
- 安全: 依頼ファイルは repo 内の本物の `.devaccel/`・`docs/design/` だけ(リンクのディレクトリは拒否)。例の ID 探索はリンクをたどらず通常ファイルのみ・サイズ上限つき。

## 0.13.3 (2026-11-18)
- PR の証拠づくりを短縮(検査の中身は同じ): base の取得と HEAD の取り出しを並行、check.sh full とテスト収集の照合を並行。
- devaccel-pr の説明に直行手順(本文を開かずに ship.md → ship)。
- ベンチに 1 件の課題(`tasks_single.md`・隠しテスト)。実測(ヒントなし、各 2 回、隠しテスト満点): 1 件 38・40 秒・$0.12〜0.14(PR まで)、中 4 件 69・83 秒・$0.10〜0.12、12 件 78・84 秒・$0.13〜0.15。

## 0.13.2 (2026-11-18)
- 単位は終える前に自分のファイルへ `ruff check --fix` を 1 回かけ、残った指摘を直す(単位のゲート失敗 50 回中 47 回が lint で、1 往復 10 秒以上。導入後の 14 単位はすべて一発で pass)。検査の基準は同じ。
- doctor: このプロジェクトで毎セッション読み込まれるプラグインと claude.ai コネクタを表示し、個人設定で切る方法を案内(実測でセッション開始が約 27% 安い)。
- 実測(ヒントなし、プラグイン・コネクタを切った試用プロジェクト): 中 4 件 65・74 秒・$0.09(逐次の約 1.7〜2 倍速・約 1/4)、12 件 77・80 秒・$0.12〜0.15(約 2.2 倍速・約 1/4〜1/5)。隠しテスト満点。

## 0.13.1 (2026-11-18)
最終チェック(脆弱性・トークン)。High/Critical なし。
- 品質: PR の確認メモ(`.devaccel/ship.md`)を ship が使用後に消す(書き込みに失敗したセッションが前回の別 PR のメモで ship していた)。ファンアウトは専用のメモ・`prompt.md` も使い切りで消す。
- 安全: サンドボックス外の `.devaccel/` への書き込み・削除は、ファイルとディレクトリの両方で symlink を辿らない(O_NOFOLLOW)。`scripts/check.sh`・`.github/` に触れた単位は統合しない。
- トークン: 番号付きの依頼はスキル本文を開かずに直接ファンアウト(親のターン 4〜9 → 2)。スキル本文を分割(番号なし・会話内並列の手順は reference.md)。拒否されるパイプ付きコマンドを使わないよう明記。12 件 83〜99 秒・$0.14〜0.16、中 4 件 93〜98 秒・$0.12〜0.14(隠しテスト満点)。

## 0.13.0 (2026-11-18)
**普通に頼むだけで速く安く**: 独立した作業が 4 件以上なら Claude が自分でファンアウトを選び、PR まで作る。ヒントなしの依頼で 12 件 84〜86 秒・$0.16〜0.18(素の逐次 176 秒・$0.60 の約 2.1 倍速・約 3 割、親セッション込み)。
- 自動化: devaccel-batch / devaccel-pr をモデルが自分で使う(判断基準つき)。ファンアウトはサンドボックスの外で確認なしに起動(設定の `sandbox.excludedCommands` と allow。ユーザー方針。**既存プロジェクトは settings.json に 2 行を足す必要がある**: doctor が案内)。ガードとスクリプトが形を `.devaccel/<名前>.md --branch batch/<名前> [--dry-run]` に固定。
- 依頼の打ち直しなし: 依頼文が番号付きなら、ガードがユーザーの依頼文を `.devaccel/prompt.md` に書き出す(12 件で約 20 秒・$0.07 減)。見出し・太字の番号も件として読む。
- 対話セッションが未コミットのコード変更を残して止まると、1 回だけ PR 化を促す(`pr.auto`、既定 on。同じ状態で再び止まれば通す)。
- **v0.12.3 監査の修正**: PR/ship の base 検査を Claude Code の外では隔離(High: ファンアウト経由で単位のテストが人の権限で動いていた)。ファンアウトは単位のコミットを自分で隔離検査し直す(単位が書けるゲート記録を信用しない)。worktree リンクの付け替え防止。秘密・設定ファイルの除外を広げ、単位自身のコミットも検査。参照ファイルの埋め込みは追跡済み・秘密以外だけ。単位の文の無害化(端末・PR 本文)。単位ごとの時間・ターン上限と後始末。事前点検。ゲートは git を動かす前にリンクを検証。`pytest.toml` 等は常に人。統合 PR は単位のエスカレーションも数える。
- ship: `--dry-run` は何も変えない(`--no-push` が従来の手元実行)。`--paths .` は拒否。
- 文書: README の古い版・数字・「全回満点」・並列数の既定を訂正。

## 0.12.3 (2026-11-18)
- devaccel_batch: 単位のセッションを軽く(`--strict-mcp-config` で MCP なし、`--tools` で 6 つ、`--disable-slash-commands`)。毎ターン送る文脈が約 6 割減り、12 件で 64〜77 秒・$0.058〜0.07(素の Claude Code 逐次 176 秒・$0.60 の約 2.3〜2.75 倍速・約 1/9)。フック・サンドボックス・CLAUDE.md はそのまま。
- `--speculate`(遅れた単位に予備): 効果が出なかったため既定は無効。

## 0.12.2 (2026-11-18)
- ship の固定費を約 12 秒 → 約 8 秒: push を証拠づくり(HEAD のスナップショットと base の check)と並行、gh のラベル作成と既存 PR の照会も並行(push 後に古ければ照会し直す)。段階ごとの秒数を `DEVACCEL_TIMING=1` で表示。
- devaccel_batch: `--effort`、`--strong K`(長い K 件を sonnet)、参照ファイルの埋め込み(課題文が `` `path` `` で名指す 8 KB 以下のファイルを最大 3 つ。`--no-context` で無効)。計測の結果、既定は haiku・effort low のまま(D17)。

## 0.12.1 (2026-11-18)
- devaccel_batch の並列数をマシンとプロジェクトに合わせて実行時に決める(固定しない): `--jobs` > `project.json` の `parallel.max_jobs` > 空きメモリ × 0.8 ÷ `parallel.unit_mem_mb`(既定 300)と CPU 数 × 2。使う数と根拠を表示。doctor がそのマシンでの目安を表示。

## 0.12.0 (2026-11-18)
**速さとコストの目標を束の作業で達成**(12 件: 素の Claude Code 逐次の約 2.2 倍速・約 1/6、隠しテスト満点、伏せた品質採点は同等以上。D17)。
- `devaccel_batch.py`(新規、人が実行): 親なしファンアウト。件ごとに worktree と `claude -p`(haiku・effort low・単位の規則)。単位は実装と自分のテストだけ、検査は終了時のゲート 1 回(整形込み・enforce・隔離)。ゲートを通った作業ツリーをスクリプトがコミット(本体側の git dir、フック/fsmonitor 無効、秘密/状態ファイル除外)。合格記録とコミットのある単位だけを ship で統合。`--hedge K`(効果なしのため既定 1)。
- ゲートの強化(fan-out と /batch の単位共通): 信頼の基準を worktree のパスから決める(環境変数・git メタデータでは決めない)、worktree の `.git` をファイルとして検証してから git を動かす、git の最上位が worktree そのものでなければ block、単位では内部エラーも block、判定は 1 回だけ、devaccel の git 呼び出しはすべて fsmonitor/フック無効。
- ship: `--branch`(保護ブランチ上なら作業ブランチを `--no-track` で作る)、重複・無変更の単位を数えない、統合 PR の振り分けは単独 PR と同じ(L 規模の緩和は撤回)。
- 単位の規則: 仕様の端のケースを先にテストにしてから実装する。単位の指示文は短く(起動のずれ対策)。
- bench: 逐次/並列/ファンアウトの比較(`tests/bench/parallel/`、小 4・小 8・中 4・12 件の課題と隠しテスト、`--cap`、パッチ保存と伏せた品質採点)。

## 0.11.0 (2026-11-18)
逐次・並列の実測(D14)を受けた速度・コストの改善(fable の設計)。
- **`devaccel_ship.py`(新規)**: コミット・push・証拠つき PR を 1 コマンドで(従来の devaccel-pr は 5〜6 ターン)。push の規則(作業ブランチのみ・origin のみ・force なし)はスクリプト内で再実装し、guard は lock 一致の単独実行だけを許可。devaccel-pr スキルは ship を使う 3 手順に。
- **並列の作り替え**: 作業単位は実装・テスト・コミットだけ(PR を作らない)。親が `ship --units` で機械的に統合し、check を 1 回、PR を 1 本。単位は新しいエージェント定義 `devaccel-unit`(haiku・effort low・worktree)。(L 規模の判定を単位数で緩める案は撤回し、単独の PR と同じ規則。)並列度 3 → 8。
- devaccel-batch の「使う条件」: 既定は逐次。並列は逐次で 5 分を超えそうな 4 件以上・ファイルの重なりなしのときだけ。

## 0.10.3 (2026-11-18)
- 逐次 対 並列を初めて計測(`tests/bench/parallel/`): 独立した小さな 4 課題で、逐次 93 秒・$0.24・4/4、並列 129 秒・$0.80・3/4。README・D14・devaccel-batch スキルの「使う条件」を実測に合わせた(4 件では逐次を推奨)。
- guard: PR タイトル中の `x=y` を環境変数の変更と誤検知して PR 作成を拒否していた(並列計測で 1 単位が停止)。許可リスト方式で不要になっていた環境変数の走査を削除。

## 0.10.2 (2026-11-18)
- PR: HEAD のスナップショットを git のオブジェクトから直接書き出す(`git archive` は枝の `.gitattributes` の `export-ignore` に従うので、落ちるテストを検査から外せた)。取り出せない・空のときは検査失敗(素通しにしない)。

## 0.10.1 (2026-11-18)
修正後の再監査 2 本と自動レビューの指摘を修正。テスト 112 → 125 本(すべてミューテーションで失敗を確認)。
- guard: コミットメッセージを判定から外すのは、コマンド全体が素の `git commit … -m "…"` 1 つで改行を含まないときだけ(0.10.0 のこの処理は `echo 'git commit -m ' ; sudo … ; echo '` で中間のコマンドを隠せた。v0.10.0 タグにはこの穴がある)。`(rm -rf /)`・`$(rm -rf ~)`・`rm -rf ./*`・`rm -rf ~/.` を拒否。
- 隔離: pid/ipc/uts 名前空間を分け、新しいセッション(端末への文字注入を防ぐ)、標準入力なし。`$HOME` の許可リストを必要な下位ディレクトリに限定(`~/.cargo/credentials.toml`・`~/.gitconfig` などは見えない)。入れ子の `.env` と本体側の `.env` も隠す。
- ゲート: 状態ファイル・project.json の型違い(トップレベルが配列等を含む)で落ちない。壊れた worktree でも通知ではなくブロックし、上限回数で人へ。エラーの記録に session/scope/mode/branch。
- PR: 証拠は HEAD を取り出したきれいなツリーで作る(未追跡・ignore されたファイルが結果に効かない)。pytest は別プロセスで収集した件数と実行件数を照合(偽の要約を出して `os._exit(0)` するテストを検出、テスト 0 件のプロジェクトは失敗にしない)。
- doctor: denyWrite の全項目を確認、matcher `Bash|Edit` も配線ありと判定。install: core・lock・.gitignore もシンボリックリンク越しに書かない。settings: `.claude/state`・lock・skills・`settings.local.json` の Edit に確認、`settings.local.json` も denyWrite。CI と生成 workflow の Actions を SHA で固定。
- 文書: README・requirements・traceability・design の古い記述と数値を修正。難課題を sonnet・各 3 回で再計測(正確さ・コスト・時間とも同等)。

## 0.10.0 (2026-11-18)
公開前の独立監査 4 本(脆弱性・約束の検証・改善余地・初見利用者)と自動レビューの指摘を修正。テスト 85 → 112 本(すべてミューテーションで失敗を確認)。
- **H1 検査の隔離(D16)**: ゲートと land は check.sh を bubblewrap で実行(読み取り専用、`$HOME` は許可リスト、書けるのは作業ツリーだけ、`.git` と本体の検証基盤は読み取り専用、`.env` を隠し、環境変数は最小限)。フックはサンドボックスの外で動くため、エージェントの書いたテストが利用者の全権限で動いていた。bwrap が無ければ未検査と表示。
- **H2/H5 振り分けのすり抜け**: git はパスを引用符で囲まずリネームを対にしない。`--no-renames --text`。ツール/テスト設定ファイル(pyproject.toml、.gitattributes、入れ子の ruff/pytest/pyright 設定ほか)の変更はすべて needs-human。種類の変わったファイル、バイナリ化したテストも needs-human。pytest で passed が 1 件も無い成功は失敗扱い。
- **H3 モジュールのすり替え**: フックは自分のディレクトリを sys.path の末尾に。guard は PR/land スクリプトの横に lock 外のファイル(`json.py`、`__pycache__`)があれば拒否。
- **H4 単位ゲート**: 判定前後で同じ検査対象の定義を使う(コミット済みの変更でブロックが止まらなかった 0.9.0 の退行)。
- ゲート: project.json の型違いは既定値に戻す(落ちて素通しだった)。単位はブランチ名や `.git` リンクの破壊で検査を止められない。notice/error の記録に branch・scope・mode。
- guard: `rm -Rf /`・`${HOME}`・`~/*`、`git -c diff.external=` 等を拒否。`git commit -m "…"` の素のメッセージは判定から外す(「Add push docs」等の誤検知)。
- PR: 自動マージは検証した head に固定(`--match-head-commit`)。本文に認証情報らしき文字列があれば作成を拒否。証拠の段の行は形式を限定。land は PR タイトルの制御文字を除く。
- 設定: sandbox `denyWrite` で本体の `.claude/hooks`・`skills`・`state`・lock・`project.json`・`settings.json`・`scripts/check.sh` を守る。生成する CI は `permissions: contents: read`、Python 以外には汎用の workflow。
- doctor: フック配線を構造で判定、permissions.deny と denyWrite の欠落を problem、キット側の report を `-I` で実行(プロジェクトのスクリプトを実行しない)。install: 既存 settings.json には設定一式を表示、シンボリックリンク越しに書かない、既存 check.sh の権限を変えない。report: notice は種類だけ(ファイル名をスキルの文脈に入れない)。
- README: 看板を実測に合わせて修正(トークン削減キットではない、並列の速さ・実 PR での振り分け精度は未計測)、前提(Claude Code・gh・bubblewrap)を手順の前に、更新手順、サンドボックス設定例を最新に。bench/smoke は個人の既定パスをやめ `--trial` 必須。

## 0.9.0 (2026-11-18)
要件とテストの見直し。
- `docs/requirements.md`: 検証できる要件 94 件と、受け入れたリスク 16 件(テストを読まない別エージェントが文書とコードから作成)。文書とコードの食い違い 12 件を決着させた。
- `docs/traceability.md`: 要件とテストの対応表(別エージェントの監査)。監査時点で完全にカバーされた要件は 6 件だけだった。
- テスト 34 → 84 本(`tests/test_requirements.py`)。各テストは、対応するコードをわざと壊すと失敗することを確認済み(65 通り)。空振りしていたテスト 2 本を修正。
- 食い違いの修正: 単位ではコミット済み・未マージの変更も検査、enforce で検査できなかった場合を表示・記録、`DEVACCEL_GATE_MODE` は対話セッションだけ、land は本体の設定を読む、install は衝突を全部調べてから書く、update は新しく core になるパスの利用者ファイルを上書きしない、`SubagentStop` 未配線は doctor の problem。
- guard: PR スクリプトの実行に展開・リダイレクトを禁止(ロック照合後の差し替え対策)。
- doctor: devaccel の core が未コミットなら problem(/batch の worktree は HEAD から作られ、ロックと合わず PR 手順が拒否される。リリース前スモークで発見)。
- python3 の最低版を 3.10 に(CI で 3.10 と 3.12)。スモークの Bash 遅延の上限を 2 秒に。

## 0.8.4 (2026-11-18)
- guard: devaccel_pr/land を動かすコマンドは、そのスクリプト単独(前後は読むだけのコマンドのみ)に限る許可リスト方式に(関数定義・hash・`true &&` などの列挙漏れを塞ぐ)。
- ゲート: 変更なしの再停止で出したブロック/エスカレーションも記録する(PR の振り分けが判断依頼を数え漏らしていた)。

## 0.8.3 (2026-11-18)
独立したコードレビュー(結論を渡さず別エージェント)の指摘 1〜9 を修正。
- guard: devaccel_pr/land の実行と同じコマンドで環境変数・alias・source を変える形を拒否(`PATH=`/`PYTHONPATH=` で python や import を差し替えられた)。
- ゲート: 非 UTF-8 のファイル名・出力で落ちて素通しになっていた → 置換デコード。状態をセッション/単位ごとのファイルに分け、並列単位の同時書き込みで block が消える競合を解消(判定を先に出してから保存)。enforce で「何も変えずにもう一度止める」と通れた → 同じ木なら失敗を再提示(3 回で人へ)。timeout は未検証として次回再実行、検査の上限をフックの 120 秒より下に。単位の判定を git-dir ≠ common-dir に(シンボリックリンク・大小文字に強い)。
- check.sh の cd 行を `${DEVACCEL_ROOT:-...}` に。見慣れない cd 行の check.sh は別の木に向けず missing 扱い。
- devaccel_pr: 設定は本体から読む(単位の project.json の base_branch で差分を空にできた)。base check の timeout と、メモファイルが無い場合を明確なエラーに。
- seed CLAUDE.md: 「check.sh fast がまとめて回すので個別に回さない」(実測でターン 15→12、Bash 5.8→3.7、コスト -6%、正確さ同等)。README に任意の高速化手段(`/effort low`、`/fast`)。

## 0.8.2 (2026-11-18)
- サンドボックス denyRead にホーム直下の秘密を追加(`~/.netrc`、`~/.docker/config.json`、`~/.kube`、`~/.npmrc`、`~/.pypirc`)。他のチェックアウトの `.env` は対象外になったことを README に明記(0.8.1 の速度修正との引き換え)。

## 0.8.1 (2026-11-18)
- **高速化**: サンドボックスの denyRead から `~/**/.env` 系を削除し、`~/.ssh`・`~/.aws`・`~/.gnupg` を直接指定。ホーム全体のグロブは Bash 呼び出しごとに $HOME を走査し、1 回 4〜15 秒かかっていた(ホーム 190 万 inode で `find` 5.6 秒、`ls` 単体が 9.4 秒)。0.8.0 のベンチで devaccel の時間が vanilla の約 2 倍、サンドボックスなしなら +10% だった原因。既存プロジェクトは settings.json を手で直す(doctor が problem を出す)。

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
