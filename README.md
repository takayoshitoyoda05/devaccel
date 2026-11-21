# devaccel

> **English summary**: devaccel is a small, distributable Claude Code kit for personal and light professional Python work (WSL/Linux). It keeps interactive sessions close to vanilla Claude Code (measured), and adds a safety net only where nobody is watching: a verification gate inside `/batch` worktree units, evidence-based PRs triaged into `evidence-ok` / `needs-human`, and a local merge queue (`devaccel_land.py`) that re-verifies parallel PRs together before a human merges. Docs are in Japanese; see `docs/requirements.md` for what it guarantees and what it deliberately does not.

Claude Code で **並列・無人の作業に検証の安全網を足す** プロジェクト配布型キット(Python 中心 / WSL・Linux)。対話セッションは素の Claude Code とほぼ同じ手間に保つ(実測)。設計の理由は [docs/design.md](docs/design.md)、保証すること・しないことは [docs/requirements.md](docs/requirements.md)。

- **無人の経路に足すもの**: `/batch` の作業単位(worktree)の中で検査を強制するゲート(check.sh を bubblewrap で隔離して実行)、機械的に組み立てた証拠つき PR と `evidence-ok` / `needs-human` の振り分け、並列 PR を最新 base 上でまとめて再検証してから人がマージする `devaccel_land.py`。
- **対話には挟まない**: 常駐は短い `CLAUDE.md`(約15行)とスキル説明 3 行。対話セッションのゲートは既定 off。
- 正確さは LLM の審査ではなく **機械の検査 + 実際に動かす確認** で担保する。

**実測(2026-11、`tests/bench/`、docs/design.md D14・D17。比較対象は素の Claude Code(sonnet)を 1 セッションで順に使った場合。隠しテストは小 8 件のファンアウト 1 回で 1 件落ちたのを除き満点。生データは `tests/bench/parallel/results.jsonl`)**
- **普通に頼むだけで自動(0.13)**: 独立した作業が 4 件以上ある依頼なら Claude が自分でファンアウトを選び、終われば PR まで作る(1 件なら実装して PR)。ヒントなしの依頼で(0.13.2、プラグインと claude.ai コネクタをこのプロジェクトで切った状態)、12 件 77・80 秒・$0.12〜0.15(**逐次 176 秒・$0.60 の約 2.2 倍速・約 1/4〜1/5**)、中規模 4 件 65・74 秒・$0.09(**逐次 114〜142 秒・$0.34〜0.43 の約 1.7〜2 倍速・約 1/4**)。切らない状態では中規模 69〜94 秒・$0.11〜0.13。1 件 38〜44 秒・$0.12〜0.14(実装・検査・PR まで、隠しテスト満点)。親セッション(sonnet)の分も含む。時間のばらつきは主に最も遅い単位(haiku)。
- **セッションの床を下げる(任意)**: 毎セッションの最初に読み込まれる文脈の大半は devaccel ではなく、入れているプラグインのスキル・エージェント一覧と claude.ai コネクタ。そのプロジェクトで使わないなら `.claude/settings.local.json`(個人用・コミットされない)に `{"enabledPlugins": {"<plugin>@<marketplace>": false}, "disableClaudeAiConnectors": true}` を置くと、セッション開始が約 3.1 万 → 2.65 万トークン・約 27% 安くなった(実測)。doctor が該当するものを表示する。
- **ざっくりした依頼は設計書から(0.14)**: 番号付きの仕様でない依頼は、Claude が先に `docs/design/` に設計書(判断一覧・列挙した規則・判断を固定する例)を書き、書いた件から並列に実装する。伏せた採点で設計書なし 5〜5.5 点 → 7〜8 点。時間・費用は 117〜128 秒・$0.18〜0.21 → 146〜151 秒・$0.21〜0.24(4 機能)。
- **束の作業(独立した 4 件以上。件数が多く 1 件が重いほど効く)**: `devaccel_batch.py`(親なしファンアウト、単位は haiku)で、12 件は逐次 176 秒・$0.60(1 回)→ **64〜77 秒・$0.058〜0.07(0.12.3 以降の 3 回。約 2.3〜2.75 倍速・約 1/9)**。中規模 4 件は中央値で約 1.8 倍速・約 1/9。小さい 8 件では 1.1〜1.7 倍速・約 1/4〜1/5 にとどまる。伏せた状態での品質採点(sonnet の採点者、手元の記録のみでリポジトリには未収録)は同等以上。
- **対話の 1 件**: 素の Claude Code とほぼ同等(時間・コスト・正確さ)。トークン削減はしない。小さな作業 1〜3 件なら逐次のほうが速い。
- 未計測: 実際の PR での振り分けの誤検知・見逃し率、`/devaccel-tune` の継続調整の効果、Python 以外。

**これは何でないか**: セキュリティ境界ではない(guard は文字列判定の best-effort。本当の境界はサンドボックスと GitHub のブランチ保護)。トークン削減キットでもない。Python 以外は検査の段を自分で書く(`/devaccel-setup` が提案)。macOS は未検証。

## 前提(先に入れる)

- Claude Code、python3 ≥ 3.10、git、bash、[gh](https://cli.github.com/)(PR の流れを使う場合、`gh auth login` 済み)
- **bubblewrap と socat**(サンドボックスとゲートの隔離に必須。無いと Claude Code が起動しない設定にしている):
  `sudo apt-get install bubblewrap socat`
- Python プリセット: uv・ruff・pyright・pytest(`uv add --dev ruff pyright pytest`)

## 使い方

```bash
git clone https://github.com/takayoshitoyoda05/devaccel ~/devaccel && cd ~/devaccel && git checkout v0.15.0   # タグで固定
cd /path/to/project            # git リポジトリのルート
~/devaccel/install.sh          # 導入(既存ファイルは上書きしない)
claude                         # 起動して信頼ダイアログを承認(必須・1台1回)→ /devaccel-setup
git add -A && git commit       # .claude/ ごとコミット → 他の人は clone するだけで同じ環境(bubblewrap は各自)
~/devaccel/protect.sh          # GitHub の main を保護(公開リポジトリか Pro。マージの本当の境界)
```

更新: `cd ~/devaccel && git fetch --tags && git checkout <新しいタグ>` → プロジェクトで `~/devaccel/update.sh` → `.claude/` をコミット(未コミットだと /batch の単位が PR を作れない。doctor が知らせる)。

| コマンド | 用途 |
|---|---|
| `~/devaccel/update.sh` | core をキットの版に合わせる。core が手編集されていたら止まって差分を表示 |
| `~/devaccel/doctor.sh` | 改変・配線・権限・サンドボックス・ツール・CLAUDE.md 行数・ゲート統計の点検 |
| `~/devaccel/protect.sh` | base ブランチの保護(人が実行、確認あり) |
| `/devaccel-setup` | 初回生成(CLAUDE.md・verify-app・計測)。`--redetect` |
| `/devaccel-tune` | ゲート記録と PR 振り分けから追加・削除・調整を提案(承認後に適用) |
| `python3 .claude/hooks/devaccel_batch.py <tasks.md> --branch batch/<名前>` | **束の作業**(普段は Claude が自分で起動する。人が端末から実行してもよく、そのときは `--jobs`・`--model` などのオプションも使える): 件ごとに `claude -p`(haiku)を同時に起動し、ゲートを通った単位を統合して PR 1 本(D17)。同時に走らせる数はマシンの空きメモリ・CPU とプロジェクト設定(`parallel.max_jobs`・`unit_mem_mb`)から自動で決まる |
| `/devaccel-batch` | 会話の中から束を並列実装する(親 + 作業単位)。速さはファンアウトに劣る |

## 頼み方(どう書けば速くなるか)

特別な書き方は要らない。依頼の形を Claude が見て、経路を自動で選ぶ。下の数字は 2026-11-21 の実測で、比較対象は **素の Claude Code(Opus 5.5、1 セッション、思考の深さ medium、テストと commit まで)**。devaccel 側は親が sonnet(medium)、並列の単位が haiku で、検査つき PR まで含む。品質は sonnet の採点者が結果を伏せて、同じ確認項目で付けた 10 点満点。

| 頼み方 | 例 | devaccel がすること | 実測(devaccel 対 素の Opus) |
|---|---|---|---|
| **1 つの機能をふつうに** | 「家計簿に CSV 取り込みを実装して。列名や金額の書き方は会社ごとにバラバラ」 | 端のケース集で扱いを先に決め(docstring に `D1: …`)、テストにしてから実装 → 検査 → PR | 6 種類の平均: 品質 **8.0 対 7.1**、時間 **約 1.4 倍速**(重い機能ほど速い: CSV 102 秒 対 223 秒)、費用 **約 41%** |
| **ざっくり複数** | 「〜と〜と〜を足してほしい」(箇条書きでも文章でも) | 設計書(判断一覧・規則)を書き、件ごとに並列実装 → 1 本の PR | 4 機能: 品質 **7.25 対 6.25**、時間 210〜232 秒 対 270〜277 秒、費用 約 $0.30 対 $1.03〜1.17 |
| **番号付きの仕様** | `1. src/x.py に f(a: int) -> str: …` を 4 件以上 | 設計書を書かず、そのまま件ごとに並列実装 → 1 本の PR | 4 件: 隠しテストは両方満点、時間 110〜140 秒 対 178〜192 秒、費用 約 $0.15 対 $0.81〜0.92 |
| **大きい変更(L)** | 3 ファイル超・設計判断あり・認証/DB/削除/秘密情報 | 設計書を見せて承認を待ってから実装(並列にしない) | 未計測 |

正直なところ:
- **速さが効くのは重い依頼**。極小の 1 機能(関数 1 つ)は検査つき PR を作る約 18 秒の分だけ素の Opus より遅い(42 秒 対 27 秒、品質は 9 対 5)。急ぐときは「PR 不要」と書けば PR を作らない。
- 品質は 6 種類中 4 種類で上、予算の機能では少し下(7.75 対 8.5)。採点のばらつきは 1 本あたり ±1.5 点ほどある。
- 時間は最も遅い並列の単位で決まり、同じ依頼でも 180〜327 秒とばらつく。
- やめたいとき: 「PR 不要」「コミットしないで」/ 質問だけなら何も変えない。

## 導入されるもの

| ファイル | 層 | 役割 |
|---|---|---|
| `.claude/hooks/guard.py` | core | うっかりの破壊的 Bash(広範囲 rm -rf、sudo、force push、curl\|sh、git の --output 等)を拒否/確認。秘密は扱わない |
| `.claude/hooks/stop_gate.py` | core | 終了時に `check.sh fast`。失敗段だけ返す・3 ラウンドで人に報告・L/テスト弱体化を表示 |
| `.claude/skills/devaccel-{setup,tune,batch}` | core | 手動専用(説明は常駐しない) |
| `.claude/skills/devaccel-pr` + `hooks/devaccel_pr.py` | core | 証拠つき PR と `evidence-ok` / `needs-human` の振り分け |
| `hooks/devaccel_ship.py` | core | コミット・push・証拠つき PR を 1 コマンドで(`--units` で並列単位を統合) |
| `agents/devaccel-unit.md` | core | 並列の作業単位(haiku・worktree・実装のみ) |
| `hooks/devaccel_land.py` | core | 並列 PR を最新 base 上でまとめて再検証し、通ったものをマージ(人が実行) |
| `hooks/devaccel_common.py`・`hooks/devaccel_report.py` | core | 共通処理(隔離実行を含む)・ゲート記録の要約(doctor / tune) |
| `.worktreeinclude`・`docs/design/TEMPLATE.md`・`docs/adr/TEMPLATE.md` | project | worktree に持ち込むファイル・設計書と ADR のひな形 |
| `CLAUDE.md` | project | 進め方(S/M/L)と検証の作法 |
| `.claude/skills/design` | project | L 規模: 質問 → 受け入れ条件つき設計書 → 仕様照合 |
| `.claude/skills/verify-app` | project | 「完了」前に実際に動かす手順(setup が生成) |
| `scripts/check.sh` | project | `fast`(ゲート・自動整形あり)/ `full`(CI)。段を並べるだけ |
| `.claude/project.json` | project | 挙動の調整点はすべてここ |
| `.claude/settings.json` | project | permissions・サンドボックス・フック(PreToolUse / Stop / SubagentStop。install 時に 1 回だけ書く) |
| `.github/workflows/check.yml` | project | CI で `check.sh full` |

**core は編集しない層**(update で置き換わる)。変えたい挙動は `project.json` か project 層で。

## ゲート(`.claude/project.json` の `gate`)

- 置き場所で既定が違う(0.8.0): 対話セッション `mode` = `off`(人が見ている。実測で正確さの上積みなし・時間だけ増えた)、/batch の単位(worktree)`unit_mode` = `enforce`(誰も見ていない。失敗段を返して直させ、3 回直しても通らなければ 4 回目の失敗でユーザーへ)。値は `off` / `observe`(記録のみ)/ `enforce`。
- 個人で一時的に変える: `.claude/settings.local.json` に `{"env": {"DEVACCEL_GATE_MODE": "off"}}`(doctor が表示)。
- `spike/*` ブランチ(対話セッションのみ。作業単位はブランチ名で止められない)、docs だけの変更、前回から変化のないターンでは走らない。
- 失敗段の修正を `max_rounds`(3)回しても通らなければ(4 回目の失敗で)、Claude は修正をやめてユーザーに判断を仰ぐ。何も変えずにもう一度止めても失敗は再提示される。作業単位では、コミット済みで base に未マージの変更も検査対象。検査できなかった場合(check.sh なし・timeout・内部エラー)は記録し、enforce では表示する。
- 個人の一時的な上書き `DEVACCEL_GATE_MODE` は対話セッションだけに効く(作業単位のゲートは止まらない)。

## 注意

- settings.json の `allow` は信頼ダイアログ承認後に有効(deny/ask とフックは常に有効)。
- 既存の `.claude/settings.json` があるプロジェクトでは マージしない。install が表示する設定一式(hooks・permissions・sandbox・env)を自分でマージし、doctor で確認する。
- チーム利用: `scripts/check.sh`・`.claude/`・`.github/workflows/` を CODEOWNERS とブランチ保護で守ると、ゲートを緩める変更に人の承認が必要になる。
- セッション途中でモデルを変えない、スキルに `model:` を書かない(キャッシュが作り直しになる)。

## 並列開発(Anthropic 式: 人は差分ではなく証拠を見る)

検証ループ(ゲート・verify-app・仕様照合)で 1 本の作業を信頼できるものにし、それを並列に回して、人は振り分けられた PR だけを読む。

1. **既定は逐次**: 1 セッションで順に実装し、`devaccel-pr`(`devaccel_ship.py` で コミット・push・証拠つき PR を 1 コマンド)で 1 本にする。小さな作業 4 件では逐次のほうが並列より速く安かった(D14)。
2. 大きな独立作業の束(逐次で 5 分を超えそう・4 件以上・ファイルの重なりなし)は `/devaccel-batch <一覧>`: 作業単位 `devaccel-unit`(haiku・worktree)が実装・テスト・コミットだけを並列に行い、親が `devaccel_ship.py --units` で統合(衝突した単位は外す)→ base の check.sh を 1 回 → PR 1 本。本文はスクリプトが機械的に組み立てる証拠: `check.sh full` の結果、実動作確認の記録、受け入れ条件、変更規模、統合した/外した単位。L は並列化せず design スキルで 1 本ずつ。
3. ラベルで振り分け:
   - `evidence-ok`: 検査通過・実動作確認あり・S/M・リスクのあるパスなし → 証拠だけ見てマージ
   - `needs-human`: 理由つき(検査失敗、確認なし、L 規模、risky_paths、テスト削除/skip、ゲートの判断依頼、未チェックの受け入れ条件) → 差分を読む
4. 任意: `.claude/project.json` の `"parallel": {"auto_merge": true}` で `evidence-ok` を自動マージ(GitHub 側で auto-merge を許可し、`check` ワークフローを必須チェックにしたブランチ保護が必要)。最初は off で振り分けの精度を見て、evidence-ok のリバートが出ない期間が続いてから。
5. 押し出しの規則: push は作業ブランチから origin の同名ブランチへだけ(main/master・デフォルトブランチ・force・他リモート不可)。シェルの `git push origin HEAD` は guard が、`devaccel_ship.py` の push はスクリプト自身が同じ規則で検査する。`gh` は直接使えず、PR は lock と一致する `devaccel_pr.py` / `devaccel_ship.py` だけが作る。サンドボックス内のコマンドは確認なしで動く(`autoAllowBashIfSandboxed`)ので、並列の単位が確認待ちで止まらない。**本当の境界は GitHub 側**: guard は文字列判定の best-effort(`bash -c` 等の経由も拒否するが、完全ではない)。デフォルトブランチを保護する(PR 必須・force push 禁止・`check` を必須チェック)のが最後の砦で、`~/devaccel/protect.sh`(人が実行、確認あり)で設定できる。Claude も同じアカウントで動くため「承認必須」は個人開発では自分を締め出すだけなので入れない。サーバーが保証するのは「main に直接入らない・CI が赤いものはマージできない」まで。プランによっては非公開リポジトリでブランチ保護が使えないので、その場合は guard と PR 判定のみが頼り。より厳密にするなら、push と PR 作成だけができる fine-grained token を使う。
6. **統合(land)**: 各 PR の証拠は分岐時点の base に対するもの。兄弟 PR が先に入ると古くなる(テキスト衝突、「単独では緑・合わせると赤」)。マージは `python3 .claude/hooks/devaccel_land.py --merge`(人が実行)で行う: `evidence-ok` の PR をコード → docs の順に最新 base へ一時 worktree で 1 本ずつ合わせ、そのつど base 側の `check.sh full` を実行。衝突・失敗した PR は理由つきで `needs-human` に落とし(昇格はしない)、通った PR を squash merge する(検証した木 = マージ後の木。途中で base が動いたら止まる)。`--merge` なしは検証と降格だけ、`--dry-run` は何も変えない。重なるファイルを持つ PR は最初に表示される。落ちた PR は担当の作業ツリーで `git merge origin/main` → push → devaccel-pr 再実行で直す(force push 不要)。
7. 並列度は settings.json の `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`(devaccel の設定では 8)。単位(サブエージェント)のモデルは `CLAUDE_CODE_SUBAGENT_MODEL`(既定 `sonnet`。単位は親のキャッシュを共有しないので単価が効く。計画役のメインは自分のモデルのまま)。並列数だけトークンも増える(公式)。`/devaccel-tune` が PR の振り分け実績(件数・マージ・リバート)を見て閾値を調整する。

## 守りの分担

| 守るもの | 担当 | 仕組み |
|---|---|---|
| 秘密(`.env` 等) | **サンドボックス**(OS レベル) | `sandbox.filesystem.denyRead`。シェル経由の読み取りをどんな書き方でも拒否 |
| 秘密(Read ツール経由) | permissions | `deny: Read(/.env)` 等 |
| ネットワーク | サンドボックス | 許可ドメイン(Python は PyPI と GitHub)以外は確認 |
| うっかりの破壊的操作 | guard フック | 正規表現の best-effort。意図的な回避は防げない |
| 検査の改ざん | permissions `ask` + CI + ブランチ保護 + PR 判定 | check.sh・フック・settings の編集は確認。PR は base の check.sh で判定し、検証基盤の変更は needs-human |
| 押し出し(push・PR) | guard + permissions deny | 作業ブランチの `git push origin HEAD` と検証済み PR スクリプトのみ |

シェル文字列の解析で秘密を守るのは原理的に不可能なので、guard は破壊的操作に専念する(0.2.0 で `.env` 検出を削除)。

### サンドボックスの準備(WSL2 / Linux、初回のみ)
```bash
sudo apt-get install bubblewrap socat   # WSL1 は非対応
```
install が `.claude/settings.json` にサンドボックス設定を書く。起動後 `/sandbox` の Dependencies タブで有効を確認。doctor が依存の有無を点検する。
既存の settings.json があるプロジェクトでは、install が表示する設定一式(hooks・permissions・sandbox・env)を自分でマージし、doctor で確認する。サンドボックス部分は次のとおり(Python プリセット。公式: https://code.claude.com/docs/en/sandboxing):
```json
"sandbox": {
  "enabled": true,
  "failIfUnavailable": true,
  "allowUnsandboxedCommands": false,
  "autoAllowBashIfSandboxed": true,
  "filesystem": {
    "denyWrite": [
      "./.claude/hooks",
      "./.claude/skills",
      "./.claude/state",
      "./.claude/devaccel.lock",
      "./.claude/project.json",
      "./.claude/settings.json",
      "./scripts/check.sh"
    ],
    "denyRead": [
      "./**/.env",
      "./**/.env.*",
      "~/.ssh",
      "~/.aws",
      "~/.gnupg",
      "~/.netrc",
      "~/.docker/config.json",
      "~/.kube",
      "~/.npmrc",
      "~/.pypirc"
    ],
    "allowWrite": [
      "~/.cache/pip",
      "~/.cache/pyright-python",
      "~/.cache/ruff",
      "~/.cache/uv"
    ]
  },
  "network": {
    "allowedDomains": [
      "api.github.com",
      "files.pythonhosted.org",
      "github.com",
      "pypi.org",
      "registry.npmjs.org"
    ]
  }
}
```
- `failIfUnavailable: true` のため、bubblewrap/socat が無いと Claude Code は起動しない(黙って保護なしで動くより安全)。協業者にも初回のインストールを案内する。
- `allowUnsandboxedCommands: false` で、Claude がサンドボックス外での再実行を求める抜け道を閉じる。
- `autoAllowBashIfSandboxed: true` で、サンドボックス内の Bash は確認なしで動く(/batch の単位が確認待ちで止まらない)。`denyWrite` で、本体の検証基盤(`.claude/hooks` 等・`scripts/check.sh`)とゲートの状態をエージェントの Bash から守る。
- フックと Read/Edit ツールはサンドボックスの外で動く(Read の秘密は permissions が担当)。そのためゲートと land は check.sh(エージェントが書いたテストを含む)を**自前の bubblewrap で隔離して**実行する: ファイルシステムは読み取り専用、`$HOME` は空(ツールチェーンは読み取り専用で戻し、ツールのキャッシュだけ書ける)、書けるのは作業ツリーだけ(`.git` は読み取り専用)、`.env` は隠し、環境変数は最小限。ネットワークは依存の取得のため許可(リポジトリのコードを外に送れる残余リスク)。
- 読み取りは既定で広い。ほかに守りたい場所は `denyRead` に**パスを直接**足す(`~/**/x` のようなホーム全体のグロブは Bash のたびに $HOME を走査して数秒〜十数秒遅くなる)。そのため**他のプロジェクトの `.env` は守られない**(速度との引き換え。気になるなら秘密は `~/.config/<app>/` 等にまとめて直接指定)。`~/.config/gh` は PR 作成と push に必要なので読める(D12)。

## 開発

品質の担保は 4 層。単体テストでは Claude Code 本体・サンドボックスとの組み合わせの不具合を捕まえられない(0.6〜0.8 の退行はすべてこの種類)ので、3 を必ず挟む。

1. **CI**(`.github/workflows/ci.yml`): ruff・pyright・単体テスト(guard / ゲート / 振り分けの欠陥注入 / land / install・update・doctor)。
   結合テスト `tests/integration/generated_check.sh`: 新しい uv プロジェクトに install し、生成された check.sh を本物の ruff / pyright / pytest で実行(lint・型エラーを検出し、.claude/ を書き換えないこと)。
2. 手元: `python3 -m unittest discover -s tests -v`
3. **リリース前スモーク**(実際の Claude Code、約 $0.3): `python3 tests/smoke/release_smoke.py --trial <devaccel を入れた信頼済みのプロジェクト>` — サンドボックス内の Bash 1 回の遅延と、worktree の単位が拒否なしにコミットと PR 本文まで行けるかを確認。
4. 大きい変更は、結論を伝えずにコードだけ渡した別エージェントでレビュー(`/code-review`、ultra は使わない)。計測は `tests/bench/`。
