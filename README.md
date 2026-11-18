# devaccel

Claude Code を **少ないトークンで、正確に、速く** 回すための、プロジェクト配布型キット(Python 中心 / WSL・Linux)。
研究用の重装備版(claude-ml-template)とは独立。設計の理由は [docs/design.md](docs/design.md)。

- 常駐するのは短い `CLAUDE.md`(約15行)とスキル説明 3 行だけ。自作エージェントは 0。対話セッションには検証の儀式を挟まない(実測で効かなかった)。
- 正確さは LLM の審査ではなく **機械ゲート + 実際に動かす確認** で担保する。
- 小さい作業には何も挟まない。L 規模だけ設計書と仕様照合。
- 配布後は各プロジェクトで育てる(`project.json` / `/devaccel-tune`)。

**正直な現状(2026-11 の実測)**: 小さな機能追加 3 課題(sonnet、各 1 回)では、素の Claude Code と正確さは同等(隠しテスト全通過)。devaccel のコストは 0.6 系でトークン約 +25%・時間 2〜3 倍、0.7.1(S の verify-app 省略)で約 +13%・時間 +29% まで縮んだ。価値の主張は「人が見ていない並列・PR 経路での信頼」(ゲート、証拠つき PR、振り分け、land)にあり、小さな対話作業での上積みはまだ示せていない。計測は `tests/bench/`。

**これは何でないか**: セキュリティ境界ではない(guard は文字列判定の best-effort。本当の境界はサンドボックスと GitHub のブランチ保護)。Python 以外は検査の段を自分で書く必要がある(`/devaccel-setup` が提案)。サンドボックスに bubblewrap/socat が必要で、無いと Claude Code が起動しない設定にしている(`failIfUnavailable`)。

## 使い方

```bash
git clone <this repo> ~/devaccel && cd ~/devaccel && git checkout <tag>   # タグで固定
cd /path/to/project            # git リポジトリのルート
~/devaccel/install.sh          # 導入(既存ファイルは上書きしない)
claude                         # 起動して信頼ダイアログを承認(必須・1台1回)→ /devaccel-setup
git add -A && git commit       # .claude/ ごとコミット → 他の人は clone するだけで同じ環境
```

| コマンド | 用途 |
|---|---|
| `~/devaccel/update.sh` | core を最新に。core が手編集されていたら止まって差分を表示 |
| `~/devaccel/doctor.sh` | 改変・配線・ツール・CLAUDE.md 行数・ゲート統計の点検 |
| `/devaccel-setup` | 初回生成(CLAUDE.md・verify-app・計測)。`--redetect` |
| `/devaccel-tune` | ゲート記録と PR 振り分けから追加・削除・調整を提案(承認後に適用) |
| `/devaccel-batch` | 独立した S/M が 4 件以上のとき、コンテキストパックつきで `/batch` を呼ぶ |

前提: python3 ≥ 3.8、git、bash。Python プリセットは uv・ruff・pyright・pytest(`uv add --dev ruff pyright pytest`)。

## 導入されるもの

| ファイル | 層 | 役割 |
|---|---|---|
| `.claude/hooks/guard.py` | core | うっかりの破壊的 Bash(広範囲 rm -rf、sudo、force push、curl\|sh、git の --output 等)を拒否/確認。秘密は扱わない |
| `.claude/hooks/stop_gate.py` | core | 終了時に `check.sh fast`。失敗段だけ返す・3 ラウンドで人に報告・L/テスト弱体化を表示 |
| `.claude/skills/devaccel-{setup,tune,batch}` | core | 手動専用(説明は常駐しない) |
| `.claude/skills/devaccel-pr` + `hooks/devaccel_pr.py` | core | 証拠つき PR と `evidence-ok` / `needs-human` の振り分け |
| `hooks/devaccel_land.py` | core | 並列 PR を最新 base 上でまとめて再検証し、通ったものをマージ(人が実行) |
| `CLAUDE.md` | project | 進め方(S/M/L)と検証の作法 |
| `.claude/skills/design` | project | L 規模: 質問 → 受け入れ条件つき設計書 → 仕様照合 |
| `.claude/skills/verify-app` | project | 「完了」前に実際に動かす手順(setup が生成) |
| `scripts/check.sh` | project | `fast`(ゲート・自動整形あり)/ `full`(CI)。段を並べるだけ |
| `.claude/project.json` | project | 挙動の調整点はすべてここ |
| `.claude/settings.json` | project | permissions・サンドボックス・フック 2 行(install 時に 1 回だけ書く) |
| `.github/workflows/check.yml` | project | CI で `check.sh full` |

**core は編集しない層**(update で置き換わる)。変えたい挙動は `project.json` か project 層で。

## ゲート(`.claude/project.json` の `gate`)

- 置き場所で既定が違う(0.8.0): 対話セッション `mode` = `off`(人が見ている。実測で正確さの上積みなし・時間だけ増えた)、/batch の単位(worktree)`unit_mode` = `enforce`(誰も見ていない。失敗段を返して直させ、3 回でユーザーへ)。値は `off` / `observe`(記録のみ)/ `enforce`。
- 個人で一時的に変える: `.claude/settings.local.json` に `{"env": {"DEVACCEL_GATE_MODE": "off"}}`(doctor が表示)。
- `spike/*` ブランチ、docs だけの変更、前回から変化のないターンでは走らない。
- 失敗段の修正が `max_rounds`(3)回続いたら、Claude は修正をやめてユーザーに判断を仰ぐ。

## 注意

- settings.json の `allow` は信頼ダイアログ承認後に有効(deny/ask とフックは常に有効)。
- 既存の `.claude/settings.json` があるプロジェクトでは マージしない。install が表示するフック 2 行を自分で追記する。
- チーム利用: `scripts/check.sh`・`.claude/`・`.github/workflows/` を CODEOWNERS とブランチ保護で守ると、ゲートを緩める変更に人の承認が必要になる。
- セッション途中でモデルを変えない、スキルに `model:` を書かない(キャッシュが作り直しになる)。

## 並列開発(Anthropic 式: 人は差分ではなく証拠を見る)

検証ループ(ゲート・verify-app・仕様照合)で 1 本の作業を信頼できるものにし、それを並列に回して、人は振り分けられた PR だけを読む。

1. 独立した S/M 作業の束(4 件以上)を `/devaccel-batch <一覧>` に渡す。コンテキストパックと単位向けの注意を付けて公式 `/batch` を呼ぶ(単位ごとに worktree で並列実装)。L は並列化せず design スキルで 1 本ずつ。
2. 各単位は devaccel-pr スキルで PR を作る。本文はスクリプトが機械的に組み立てる証拠: `check.sh full` の結果、実動作確認の記録、受け入れ条件、変更規模。
3. ラベルで振り分け:
   - `evidence-ok`: 検査通過・実動作確認あり・S/M・リスクのあるパスなし → 証拠だけ見てマージ
   - `needs-human`: 理由つき(検査失敗、確認なし、L 規模、risky_paths、テスト削除/skip、ゲートの判断依頼、未チェックの受け入れ条件) → 差分を読む
4. 任意: `.claude/project.json` の `"parallel": {"auto_merge": true}` で `evidence-ok` を自動マージ(GitHub 側で auto-merge を許可し、`check` ワークフローを必須チェックにしたブランチ保護が必要)。最初は off で振り分けの精度を見て、evidence-ok のリバートが出ない期間が続いてから。
5. 押し出しの規則(guard が強制): push は作業ブランチから `git push origin HEAD` のみ(main/master・デフォルトブランチ・force・他リモート不可)。`gh` は直接使えず、PR は lock と一致する `devaccel_pr.py` だけが作る。サンドボックス内のコマンドは確認なしで動く(`autoAllowBashIfSandboxed`)ので、並列の単位が確認待ちで止まらない。**本当の境界は GitHub 側**: guard は文字列判定の best-effort(`bash -c` 等の経由も拒否するが、完全ではない)。デフォルトブランチを保護する(PR 必須・force push 禁止・`check` を必須チェック)のが最後の砦で、`~/devaccel/protect.sh`(人が実行、確認あり)で設定できる。Claude も同じアカウントで動くため「承認必須」は個人開発では自分を締め出すだけなので入れない。サーバーが保証するのは「main に直接入らない・CI が赤いものはマージできない」まで。プランによっては非公開リポジトリでブランチ保護が使えないので、その場合は guard と PR 判定のみが頼り。より厳密にするなら、push と PR 作成だけができる fine-grained token を使う。
6. **統合(land)**: 各 PR の証拠は分岐時点の base に対するもの。兄弟 PR が先に入ると古くなる(テキスト衝突、「単独では緑・合わせると赤」)。マージは `python3 .claude/hooks/devaccel_land.py --merge`(人が実行)で行う: `evidence-ok` の PR をコード → docs の順に最新 base へ一時 worktree で 1 本ずつ合わせ、そのつど base 側の `check.sh full` を実行。衝突・失敗した PR は理由つきで `needs-human` に落とし(昇格はしない)、通った PR を squash merge する(検証した木 = マージ後の木。途中で base が動いたら止まる)。`--merge` なしは検証と降格だけ、`--dry-run` は何も変えない。重なるファイルを持つ PR は最初に表示される。落ちた PR は担当の作業ツリーで `git merge origin/main` → push → devaccel-pr 再実行で直す(force push 不要)。
7. 並列度は settings.json の `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`(既定 3)。単位(サブエージェント)のモデルは `CLAUDE_CODE_SUBAGENT_MODEL`(既定 `sonnet`。単位は親のキャッシュを共有しないので単価が効く。計画役のメインは自分のモデルのまま)。並列数だけトークンも増える(公式)。`/devaccel-tune` が PR の振り分け実績(件数・マージ・リバート)を見て閾値を調整する。

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
既存の settings.json があるプロジェクトでは、次を自分で追記する(公式: https://code.claude.com/docs/en/sandboxing):
```json
"sandbox": {
  "enabled": true,
  "failIfUnavailable": true,
  "allowUnsandboxedCommands": false,
  "filesystem": {
    "denyRead": ["./**/.env", "./**/.env.*", "~/.ssh", "~/.aws", "~/.gnupg", "~/.netrc", "~/.docker/config.json", "~/.kube", "~/.npmrc", "~/.pypirc"],
    "allowWrite": ["~/.cache/pip", "~/.cache/pyright-python", "~/.cache/ruff", "~/.cache/uv"]
  },
  "network": { "allowedDomains": ["files.pythonhosted.org", "github.com", "pypi.org", "registry.npmjs.org"] }
}
```
- `failIfUnavailable: true` のため、bubblewrap/socat が無いと Claude Code は起動しない(黙って保護なしで動くより安全)。協業者にも初回のインストールを案内する。
- `allowUnsandboxedCommands: false` で、Claude がサンドボックス外での再実行を求める抜け道を閉じる。
- フックと Read/Edit ツールはサンドボックスの外で動く(Read の秘密は permissions が担当)。
- 読み取りは既定で広い。ほかに守りたい場所は `denyRead` に**パスを直接**足す(`~/**/x` のようなホーム全体のグロブは Bash のたびに $HOME を走査して数秒〜十数秒遅くなる)。そのため**他のプロジェクトの `.env` は守られない**(速度との引き換え。気になるなら秘密は `~/.config/<app>/` 等にまとめて直接指定)。`~/.config/gh` は PR 作成と push に必要なので読める(D12)。

## 開発

品質の担保は 4 層。単体テストでは Claude Code 本体・サンドボックスとの組み合わせの不具合を捕まえられない(0.6〜0.8 の退行はすべてこの種類)ので、3 を必ず挟む。

1. **CI**(`.github/workflows/ci.yml`): ruff・pyright・単体テスト(guard / ゲート / 振り分けの欠陥注入 / land / install・update・doctor)。
2. 手元: `python3 -m unittest discover -s tests -v`
3. **リリース前スモーク**(実際の Claude Code、約 $0.3): `python3 tests/smoke/release_smoke.py` — サンドボックス内の Bash 1 回の遅延と、worktree の単位が拒否なしにコミットと PR 本文まで行けるかを確認。
4. 大きい変更は、結論を伝えずにコードだけ渡した別エージェントでレビュー(`/code-review`、ultra は使わない)。計測は `tests/bench/`。
