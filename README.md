# devaccel

> **English summary**: devaccel is a distributable Claude Code kit for Python work on WSL/Linux. You ask as usual. Claude picks the route (a single feature, a design doc plus parallel units, or a design-approved large change), runs the project's checks inside a sandbox, and opens a PR with mechanically built evidence, labeled `evidence-ok` or `needs-human`. Measured against vanilla Claude Code (Opus 5.5, medium effort): about 1.1–1.8x faster at about a quarter to three quarters of the cost, with quality close to Opus (lower on some feature requests; see below). Docs are in Japanese. `docs/requirements.md` lists what it guarantees and what it deliberately does not.

Claude Code に入れて使う、プロジェクトごとのキットです(Python 向け、WSL・Linux)。いつもどおり頼むだけで、Claude が進め方を選びます。検査はサンドボックスの中で通し、結果をそのまま証拠として載せた PR を作ります。

- **速く安く**: 素の Claude Code(Opus 5.5)に比べて、時間は約 1.1〜1.8 倍速く、費用は約 1/4〜3/4 です(依頼の種類で変わります。下の実測)。
- **正確さは機械で確かめる**: LLM の審査には頼りません。`scripts/check.sh`(lint・型・テスト)と、実際に動かす確認で担保します。
- **人は証拠を見て判断する**: PR は `evidence-ok`(証拠だけ見てマージしてよい)か `needs-human`(差分を読む、理由つき)に振り分けます。マージするのは人です。

設計の理由は [docs/design.md](docs/design.md)、保証すること・しないことは [docs/requirements.md](docs/requirements.md)、変更履歴は [CHANGELOG.md](CHANGELOG.md) にあります。

## 実測

比較の相手は、素の Claude Code です(Opus 5.5、思考の深さ medium、1 セッション、テストと commit まで)。devaccel 側は、親が sonnet、並列の単位が haiku で、数字には検査つき PR を作るまでを含みます。品質は 10 点満点で、sonnet の採点者が、どちらの結果か伏せたまま同じ確認項目で付けました。生データは `tests/bench/parallel/results.jsonl` にあります。

**実際の規模のコード(click のスナップショット、0.15.8、2026-11-22、各 2〜3 回)**

| 依頼 | devaccel | 素の Opus | 品質(devaccel 対 Opus) |
|---|---|---|---|
| 不具合の修正 | 40〜43 秒・$0.15〜0.17 | 45〜64 秒・$0.18〜0.25 | — |
| 既存の機能の変更 | 55〜87 秒・$0.20〜0.29 | 94〜103 秒・$0.30〜0.34 | 7.4 対 7.5 |
| 新しい機能 | 67〜78 秒・$0.23〜0.28 | 102〜126 秒・$0.47〜0.52 | 6.7〜7.1 対 8.1 |

**試験用の小さなプロジェクト(家計簿、2026-11-21)**

| 頼み方 | devaccel | 素の Opus | 品質(devaccel 対 Opus) |
|---|---|---|---|
| 1 つの機能(6 種類の平均) | 約 1.4 倍速・費用 約 41% | — | 8.0 対 7.1 |
| ざっくり複数(4 機能) | 152〜199 秒・約 $0.40 | 270〜277 秒・$1.03〜1.17 | 7.25 対 6.25 |
| 番号付きの仕様(4 件) | 102〜109 秒・約 $0.20 | 178〜192 秒・$0.81〜0.92 | 隠しテストは両方満点 |
| 大きい変更(複数口座への対応) | 114〜185 秒・$0.31〜0.50 | 215 秒・$0.99 | 8.0〜8.4 対 8.0 |

正直なところ:
- **新しい機能は品質で Opus に届いていない**(click で 7 前後 対 8.1)。差は細かな判断にあります(名前の付け方、境界の扱い、公開する補助関数を作るかなど)。規則を足して埋める試みは、効果が出ないか遅くなったので取り下げました。
- **極小の 1 機能(関数 1 つ)は素の Opus より遅いことがある**: 2026-11-21 の計測では、検査つき PR を作る時間の分だけ遅くなりました(42 秒 対 27 秒、品質は 9 対 5)。その後、PR を作る部分は 9〜12 秒に縮んでいます。急ぐときは「PR 不要」と書いてください。
- 採点は 1 本あたり ±1.5 点ほど、時間は同じ依頼でも ±20% ほどばらつきます。
- 時間の約 7 割は、モデルが考えて書いている時間です。
- まだ測っていないこと: 実際の PR での振り分けの誤り率、`/devaccel-tune` を続けたときの効果、Python 以外。

**これは何でないか**: セキュリティの境界ではありません。guard は文字列で判定する best-effort で、本当の境界はサンドボックスと GitHub のブランチ保護です。Python 以外は、検査の段を自分で書く必要があります(`/devaccel-setup` が提案します)。macOS では確かめていません。

## 前提(先に入れる)

- Claude Code、python3 ≥ 3.10、git、bash、[gh](https://cli.github.com/)(`gh auth login` 済み)
- **bubblewrap と socat**: サンドボックスと検査の隔離に必須です。無いと Claude Code が起動しない設定にしています。
  `sudo apt-get install bubblewrap socat`(WSL1 には対応していません)
- Python のプリセット: uv・ruff・pyright・pytest(`uv add --dev ruff pyright pytest`)

## 導入と更新

```bash
git clone https://github.com/takayoshitoyoda05/devaccel ~/devaccel && cd ~/devaccel && git checkout v0.15.8   # タグで固定
cd /path/to/project            # git リポジトリのルート
~/devaccel/install.sh          # 導入(既存ファイルは上書きしない)
claude                         # 起動して信頼ダイアログを承認(必須・1 台 1 回)→ /devaccel-setup
git add -A && git commit       # .claude/ ごとコミット → 他の人は clone するだけで同じ環境(bubblewrap は各自)
~/devaccel/protect.sh          # GitHub の main を保護(公開リポジトリか Pro。マージの本当の境界)
```

**更新**: `cd ~/devaccel && git fetch --tags && git checkout <新しいタグ>` を実行し、プロジェクトで `~/devaccel/update.sh` を実行して、`.claude/` をコミットします。未コミットのままだと、並列の単位が PR を作れません(doctor が知らせます)。
- update.sh は `.claude/settings.json` を書き換えません。
- 0.15.6 からの速い PR 作成(下書き PR を先に開き、証拠は裏で作る)を使うには、install が表示する settings の `hooks.PostToolUse`(finalize)を自分の settings.json に足してください。無ければ、これまでどおり ship が証拠を待ってから PR を作ります(doctor が知らせます)。

## 頼み方

特別な書き方は要りません。依頼の形を見て、Claude が進め方を選びます。

| 頼み方 | 例 | devaccel がすること |
|---|---|---|
| **1 つの機能・修正** | 「CSV 取り込みを実装して。列名や金額の書き方は会社ごとにバラバラ」 | 端のケースの扱いを先に決めて(docstring に `D1: …`)、テストにしてから実装し、検査して PR |
| **ざっくり複数** | 「〜と〜と〜を足してほしい」(箇条書きでも文章でも) | `docs/design/` に設計書(判断の一覧・規則・判断を固定する例)を書き、件ごとに並列で実装して 1 本の PR |
| **番号付きの仕様(4 件以上)** | `1. src/x.py に f(a: int) -> str: …` | 設計書なしで、件ごとに並列で実装して 1 本の PR |
| **大きい変更(L)** | 3 ファイル超(文書は数えない)・設計の判断あり・認証/DB/削除/秘密情報 | 設計書を見せて承認を待ってから、1 セッションで実装(並列にはしない) |

- やめたいとき: 「PR 不要」「コミットしないで」と書きます。質問だけなら何も変えません。
- WSL では、Claude Code を起動するたびに約 5 秒待つことがあります(Windows のレジストリへの問い合わせが止まるため。devaccel の並列の単位では避けています)。

## コマンド

| コマンド | 用途 |
|---|---|
| `~/devaccel/update.sh` | core をキットの版に合わせる。core が手で編集されていたら、止まって差分を表示 |
| `~/devaccel/doctor.sh` | 改変・配線・権限・サンドボックス・ツール・CLAUDE.md の行数・ゲートの統計を点検 |
| `~/devaccel/protect.sh` | base ブランチを保護する(人が実行、確認あり) |
| `/devaccel-setup` | 初回の生成(CLAUDE.md・verify-app・計測)。`--redetect` で検出し直す |
| `/devaccel-tune` | ゲートの記録と PR の振り分けの実績から、追加・削除・調整を提案(承認後に適用) |
| `python3 .claude/hooks/devaccel_batch.py <tasks.md> --branch batch/<名前>` | 束の作業。ふだんは Claude が自分で起動します。件ごとに `claude -p` を同時に動かし、ゲートを通った単位を統合して PR 1 本。同時に動かす数は、空きメモリ・CPU と `parallel.max_jobs`・`unit_mem_mb` から自動で決まる。いちばん重い件(`parallel.strong` 件)は sonnet で動かす |
| `/devaccel-batch` | 会話の中で束を並列に実装する(親 + 作業単位)。速さは上のファンアウトに劣る |
| `python3 .claude/hooks/devaccel_land.py --merge` | 並列の PR を最新の base 上でまとめて検査し直してからマージ(人が実行) |

## PR の流れ

1. **作る**: `devaccel_ship.py` が、コミット・push・PR 作成を 1 コマンドで行います。本文はスクリプトが機械的に組み立てた証拠です(`check.sh` の結果、実際に動かした確認の記録、受け入れ条件、変更の規模、統合した/外した単位)。
   - finalize のフックを入れていれば、先に下書き PR を開いて返り、証拠は GitHub から取り直したコミットに対して裏で作ります。下書きはマージできず、検査が通ってから正式な PR になります。
   - `check.sh fast` が失敗したら、GitHub のブランチを元に戻し、手元のコミットも取り消して直させます。
2. **振り分け**:
   - `evidence-ok`: 検査が通り、実際に動かした確認があり、S/M 規模で、リスクのあるパスに触れていない → 証拠だけ見てマージしてよい
   - `needs-human`: 理由つき(検査の失敗、確認なし、L 規模、`risky_paths`、テストの削除/skip、ゲートの判断依頼、未チェックの受け入れ条件) → 差分を読む
3. **マージ**: 人が行います。並列の PR が複数あるときは `devaccel_land.py --merge` を使います。
   - 各 PR の証拠は、分岐した時点の base に対するものです。兄弟の PR が先に入ると古くなります(テキストの衝突や、単独では緑なのに合わせると赤になる場合)。
   - land は `evidence-ok` の PR を、コード → docs の順に最新の base へ 1 本ずつ一時 worktree で合わせ、そのつど `check.sh full` を実行します。
   - 衝突・失敗した PR は理由つきで `needs-human` に落とし、通った PR を squash merge します。検証した木とマージ後の木は同じで、途中で base が動いたら止まります。
   - `--merge` なしなら検証と降格だけ、`--dry-run` なら何も変えません。落ちた PR は、その作業ツリーで `git merge origin/main` → push → devaccel-pr をやり直せば直ります(force push は要りません)。
4. **自動マージ(任意)**: `.claude/project.json` で `"parallel": {"auto_merge": true}` にすると、`evidence-ok` を自動でマージします。GitHub 側で auto-merge を許可し、`check` ワークフローを必須チェックにしたブランチ保護が必要です。最初は off のまま振り分けの精度を見て、evidence-ok のリバートが出ない期間が続いてから入れてください。

**push の規則**: push できるのは、作業ブランチから origin の同名ブランチへだけです。main/master・デフォルトブランチ・force・他のリモートへは押せません。
- シェルの `git push origin HEAD` は guard が、`devaccel_ship.py` の push はスクリプト自身が、同じ規則で調べます。
- `gh` は直接使えません。PR を作るのは、lock と一致する `devaccel_pr.py` / `devaccel_ship.py` だけです。
- **本当の境界は GitHub 側です。** デフォルトブランチを保護してください(PR 必須・force push 禁止・`check` を必須チェック)。`~/devaccel/protect.sh` で設定できます。
  - Claude も同じアカウントで動くので、個人開発で「承認必須」にすると自分を締め出すだけです。そのため入れていません。サーバーが保証するのは「main に直接入らない・CI が赤いものはマージできない」までです。
  - プランによっては、非公開リポジトリでブランチ保護が使えません。その場合は guard と PR の判定だけが頼りです。より厳しくしたいなら、push と PR 作成だけができる fine-grained token を使ってください。

## ゲート(`.claude/project.json` の `gate`)

- 対話のセッション(`mode`)は既定で `off` です。人が見ているうえ、実測で正確さの上積みがなく、時間だけ増えました。
- 並列の単位(`unit_mode`)は既定で `enforce` です。誰も見ていないので、失敗した段を返して直させます。3 回直しても通らなければ、4 回目の失敗でユーザーに判断を仰ぎます。
- 値は `off` / `observe`(記録のみ)/ `enforce` です。
- 個人で一時的に変えるなら、`.claude/settings.local.json` に `{"env": {"DEVACCEL_GATE_MODE": "off"}}` と書きます(対話のセッションだけに効き、並列の単位のゲートは止まりません。doctor が表示します)。
- `spike/*` ブランチ(対話のみ)、docs だけの変更、前回から変化のないターンでは走りません。
- 何も変えずにもう一度止めても、失敗は再び示されます。並列の単位では、コミット済みで base にまだ入っていない変更も検査の対象です。
- 検査できなかった場合(check.sh が無い・timeout・内部エラー)は記録し、enforce では表示します。

## 守りの分担

| 守るもの | 担当 | 仕組み |
|---|---|---|
| 秘密(`.env` 等) | **サンドボックス**(OS レベル) | `sandbox.filesystem.denyRead`。シェル経由の読み取りを、どんな書き方でも拒否 |
| 秘密(Read ツール経由) | permissions | `deny: Read(/.env)` 等 |
| ネットワーク | サンドボックス | 許可したドメイン(Python は PyPI と GitHub)以外は確認 |
| うっかりの破壊的な操作 | guard フック | 正規表現による best-effort。意図的な回避は防げない |
| 検査の改ざん | permissions `ask` + CI + ブランチ保護 + PR の判定 | check.sh・フック・settings の編集は確認が必要。PR は base 側の check.sh で判定し、検証の基盤に触れる変更は needs-human |
| push・PR | guard + permissions の deny | 作業ブランチの `git push origin HEAD` と、検証済みの PR スクリプトだけ |

シェルの文字列を解析して秘密を守ることは原理的にできないので、guard は破壊的な操作を防ぐことに専念しています(0.2.0 で `.env` の検出を削除)。

### サンドボックス

install が `.claude/settings.json` にサンドボックスの設定を書きます。起動後に `/sandbox` の Dependencies タブで有効になっているか確認してください。doctor も依存の有無を点検します。

既存の settings.json があるプロジェクトでは、install は上書きしません。install が表示する設定一式(hooks・permissions・sandbox・env)を自分でマージし、doctor で確認してください。サンドボックスの部分は次のとおりです(Python のプリセット。公式: https://code.claude.com/docs/en/sandboxing)。

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

- `failIfUnavailable: true` なので、bubblewrap/socat が無いと Claude Code は起動しません(黙って保護なしで動くより安全です)。一緒に作業する人にも、初回のインストールを案内してください。
- `allowUnsandboxedCommands: false` で、Claude がサンドボックスの外で再実行を求める抜け道を閉じています。
- `autoAllowBashIfSandboxed: true` で、サンドボックス内の Bash は確認なしで動きます(並列の単位が確認待ちで止まらないように)。`denyWrite` で、検証の基盤(`.claude/hooks` 等・`scripts/check.sh`)とゲートの状態を、エージェントの Bash から守っています。
- フックと Read/Edit ツールはサンドボックスの外で動きます(Read での秘密は permissions が担当)。そのためゲートと land は、check.sh(エージェントが書いたテストを含む)を**自前の bubblewrap で隔離して**実行します。
  - ファイルシステムは読み取り専用です。書けるのは作業ツリーだけで、`.git` は読み取り専用です。
  - `$HOME` は空です。ツールチェーンは読み取り専用で戻し、ツールのキャッシュだけ書けます。
  - `.env` は隠し、環境変数は最小限にしています。
  - `/run` は空です(docker.sock・D-Bus・ssh-agent・WSL interop のソケットに届きません)。
  - ネットワークは、依存を取得するため許可しています。リポジトリのコードを外に送れるという残余リスクがあります(抽象名前空間の Unix ソケットも同じ理由で残ります)。
- 読み取りは既定で広く許しています。ほかに守りたい場所は、`denyRead` に**パスを直接**足してください。`~/**/x` のようなホーム全体のグロブは、Bash のたびに $HOME を走査して数秒〜十数秒遅くなります。
  - そのため、**他のプロジェクトの `.env` は守られません**(速度との引き換えです)。気になるなら、秘密は `~/.config/<app>/` などにまとめて直接指定してください。
  - `~/.config/gh` は、PR 作成と push に必要なので読めます(D12)。

## 注意

- settings.json の `allow` は、信頼ダイアログを承認したあとに有効になります(deny/ask とフックは常に有効)。
- チームで使うなら、`scripts/check.sh`・`.claude/`・`.github/workflows/` を CODEOWNERS とブランチ保護で守ってください。ゲートを緩める変更に、人の承認が必要になります。
- セッションの途中でモデルを変えたり、スキルに `model:` を書いたりしないでください(キャッシュが作り直しになります)。
- `.github/workflows/check.yml` は PR と push のたびに `check.sh full` を動かします。非公開リポジトリでは GitHub Actions の無料枠を使うので、PR をたくさん作るなら止めるか削除してください。
- セッションの最初に読み込まれる文脈の大半は、devaccel ではなく、入れているプラグインと claude.ai コネクタです。そのプロジェクトで使わないなら、`.claude/settings.local.json`(個人用・コミットされない)に `{"enabledPlugins": {"<plugin>@<marketplace>": false}, "disableClaudeAiConnectors": true}` と書くと、1 セッションが約 27% 安くなりました(実測)。doctor が該当するものを表示します。

## 導入されるもの

**core の層は編集しません**(update で置き換わります)。挙動を変えたいときは、`.claude/project.json` か project の層で変えてください。

| ファイル | 層 | 役割 |
|---|---|---|
| `.claude/hooks/guard.py` | core | うっかりの破壊的な Bash(広範囲の rm -rf、sudo、force push、curl\|sh、git の --output 等)を拒否・確認する。秘密は扱わない |
| `.claude/hooks/stop_gate.py` | core | 終了時に `check.sh fast`。失敗した段だけを返す。3 ラウンドで人に報告。L 規模やテストの弱体化を表示 |
| `.claude/hooks/devaccel_ship.py` | core | コミット・push・証拠つき PR を 1 コマンドで(`--units` で並列の単位を統合) |
| `.claude/hooks/devaccel_pr.py` + `.claude/skills/devaccel-pr` | core | 証拠つき PR と `evidence-ok` / `needs-human` の振り分け |
| `.claude/hooks/devaccel_batch.py` | core | 束の作業のファンアウト |
| `.claude/hooks/devaccel_land.py` | core | 並列の PR を最新の base 上でまとめて検査し直し、通ったものをマージ(人が実行) |
| `.claude/hooks/devaccel_common.py`・`devaccel_report.py` | core | 共通の処理(隔離実行を含む)・ゲートの記録の要約(doctor / tune 用) |
| `.claude/agents/devaccel-unit.md` | core | 並列の作業単位(haiku・worktree・実装のみ) |
| `.claude/skills/devaccel-{setup,tune,batch}` | core | 手動専用(説明は常駐しない) |
| `CLAUDE.md` | project | 進め方(S/M/L)と検証の作法(約 15 行) |
| `.claude/skills/design` | project | L 規模: 質問 → 受け入れ条件つきの設計書 → 仕様との照合 |
| `.claude/skills/verify-app` | project | 「完了」の前に実際に動かす手順(setup が生成) |
| `scripts/check.sh` | project | `fast`(ゲート用・自動整形あり)/ `full`(CI 用)。段を並べるだけ |
| `.claude/project.json` | project | 挙動の調整点はすべてここ |
| `.claude/settings.json` | project | permissions・サンドボックス・フック(install のときに 1 回だけ書く) |
| `.worktreeinclude`・`docs/design/TEMPLATE.md`・`docs/adr/TEMPLATE.md` | project | worktree に持ち込むファイル・設計書と ADR のひな形 |
| `.github/workflows/check.yml` | project | CI で `check.sh full` |

並列の度合いは settings.json の `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`(devaccel の設定では 8)で決まります。サブエージェントの既定のモデルは `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` です。

## 開発

品質は 4 つの層で担保しています。単体テストだけでは、Claude Code 本体やサンドボックスとの組み合わせの不具合を捕まえられません(0.6〜0.8 の退行はすべてこの種類でした)。そのため、3 は必ず通してください。

1. **CI**(`.github/workflows/ci.yml`): ruff・pyright・単体テスト(guard / ゲート / 振り分けへの欠陥注入 / land / ship / install・update・doctor)。結合テスト `tests/integration/generated_check.sh` は、新しい uv プロジェクトに install し、生成された check.sh を本物の ruff / pyright / pytest で実行します。
2. **手元**: `python3 -m unittest discover -s tests -v`
3. **リリース前のスモーク**(実際の Claude Code、約 $0.3): `python3 tests/smoke/release_smoke.py --trial <devaccel を入れた信頼済みのプロジェクト>`。サンドボックス内の Bash 1 回の遅延と、worktree の単位が拒否されずにコミットと PR 本文まで行けるかを確認します。
4. **大きな変更のレビュー**: 結論を伝えずにコードだけを別のエージェントに渡してレビューします(`/code-review`)。

計測は `tests/bench/` で行います。`tests/bench/parallel/run.py` に依頼(`tasks_*.md`)と比較する経路(`auto_med`・`vanilla_opus_med` など)を渡して実行し、結果を `results.jsonl` に追記します。
