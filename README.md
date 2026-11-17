# devaccel

Claude Code を **少ないトークンで、正確に、速く** 回すための、プロジェクト配布型キット(Python 中心 / WSL・Linux)。
研究用の重装備版(claude-ml-template)とは独立。設計の理由は [docs/design.md](docs/design.md)。

- 常駐するのは短い `CLAUDE.md`(約30行)とスキル説明 2 行だけ。自作エージェントは 0。
- 正確さは LLM の審査ではなく **機械ゲート + 実際に動かす確認** で担保する。
- 小さい作業には何も挟まない。L 規模だけ設計書と仕様照合。
- 配布後は各プロジェクトで育てる(`project.json` / `/devaccel-tune`)。

## 使い方

```bash
git clone <this repo> ~/devaccel && cd ~/devaccel && git checkout <tag>   # タグで固定
cd /path/to/project            # git リポジトリのルート
~/devaccel/install.sh          # 導入(既存ファイルは上書きしない)
claude                         # 起動して信頼ダイアログを承認 → /devaccel-setup
git add -A && git commit       # .claude/ ごとコミット → 他の人は clone するだけで同じ環境
```

| コマンド | 用途 |
|---|---|
| `~/devaccel/update.sh` | core を最新に。core が手編集されていたら止まって差分を表示 |
| `~/devaccel/doctor.sh` | 改変・配線・ツール・CLAUDE.md 行数・ゲート統計の点検 |
| `/devaccel-setup` | 初回生成(CLAUDE.md・verify-app・計測)。`--redetect` / `--codex on\|off` |
| `/devaccel-tune` | ゲート記録から追加・削除・昇格を提案(承認後に適用) |

前提: python3 ≥ 3.8、git、bash。Python プリセットは uv・ruff・pyright・pytest(`uv add --dev ruff pyright pytest`)。

## 導入されるもの

| ファイル | 層 | 役割 |
|---|---|---|
| `.claude/hooks/guard.py` | core | うっかりの破壊的 Bash(広範囲 rm -rf、sudo、force push、curl\|sh、git の --output 等)を拒否/確認。秘密は扱わない |
| `.claude/hooks/stop_gate.py` | core | 終了時に `check.sh fast`。失敗段だけ返す・3 ラウンドで人に報告・L/テスト弱体化を表示 |
| `.claude/skills/devaccel-{setup,tune}` | core | 手動専用(説明は常駐しない) |
| `.claude/skills/devaccel-pr` + `hooks/devaccel_pr.py` | core | 証拠つき PR と `evidence-ok` / `needs-human` の振り分け |
| `CLAUDE.md` | project | 進め方(S/M/L)と検証の作法 |
| `.claude/skills/design` | project | L 規模: 質問 → 受け入れ条件つき設計書 → 仕様照合 |
| `.claude/skills/verify-app` | project | 「完了」前に実際に動かす手順(setup が生成) |
| `scripts/check.sh` | project | `fast`(ゲート・自動整形あり)/ `full`(CI)。段を並べるだけ |
| `.claude/project.json` | project | 挙動の調整点はすべてここ |
| `.claude/settings.json` | project | permissions・サンドボックス・フック 2 行(install 時に 1 回だけ書く) |
| `.github/workflows/check.yml` | project | CI で `check.sh full` |

**core は編集しない層**(update で置き換わる)。変えたい挙動は `project.json` か project 層で。

## ゲート(`.claude/project.json` の `gate`)

- `mode`: `off` / `observe`(記録のみ・既定)/ `enforce`(ブロック)。
  observe で `promote.min_runs` 回以上動かし、誤検知が無ければ `/devaccel-tune` で enforce へ。
- 個人で一時的に変える: `.claude/settings.local.json` に `{"env": {"DEVACCEL_GATE_MODE": "off"}}`(doctor が表示)。
- `spike/*` ブランチ、docs だけの変更、前回から変化のないターンでは走らない。
- 失敗段の修正が `max_rounds`(3)回続いたら、Claude は修正をやめてユーザーに判断を仰ぐ。

## 注意

- settings.json の `allow` は信頼ダイアログ承認後に有効(deny/ask とフックは常に有効)。
- 既存の `.claude/settings.json` があるプロジェクトでは マージしない。install が表示するフック 2 行を自分で追記する。
- Codex 併用時(`/devaccel-setup --codex on`)、Codex には Stop フックが無いので担保は AGENTS.md の指示と CI のみ。
- チーム利用: `scripts/check.sh`・`.claude/`・`.github/workflows/` を CODEOWNERS とブランチ保護で守ると、ゲートを緩める変更に人の承認が必要になる。
- セッション途中でモデルを変えない、スキルに `model:` を書かない(キャッシュが作り直しになる)。

## 並列開発(Anthropic 式: 人は差分ではなく証拠を見る)

検証ループ(ゲート・verify-app・仕様照合)で 1 本の作業を信頼できるものにし、それを並列に回して、人は振り分けられた PR だけを読む。

1. 独立した S/M 作業の束を `/batch <指示>` に渡す(公式機能。作業を単位に分け、単位ごとに worktree で並列実装)。L は並列化せず design スキルで 1 本ずつ。
2. 各単位は devaccel-pr スキルで PR を作る。本文はスクリプトが機械的に組み立てる証拠: `check.sh full` の結果、実動作確認の記録、受け入れ条件、変更規模。
3. ラベルで振り分け:
   - `evidence-ok`: 検査通過・実動作確認あり・S/M・リスクのあるパスなし → 証拠だけ見てマージ
   - `needs-human`: 理由つき(検査失敗、確認なし、L 規模、risky_paths、テスト削除/skip、ゲートの判断依頼、未チェックの受け入れ条件) → 差分を読む
4. 任意: `.claude/project.json` の `"parallel": {"auto_merge": true}` で `evidence-ok` を自動マージ(GitHub 側で auto-merge を許可し、`check` ワークフローを必須チェックにしたブランチ保護が必要)。最初は off で振り分けの精度を見て、evidence-ok のリバートが出ない期間が続いてから。
5. 並列度は settings.json の `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`(既定 3)。並列数だけトークンも増える(公式)。`/devaccel-tune` が PR の振り分け実績(件数・マージ・リバート)を見て閾値を調整する。

## 守りの分担

| 守るもの | 担当 | 仕組み |
|---|---|---|
| 秘密(`.env` 等) | **サンドボックス**(OS レベル) | `sandbox.filesystem.denyRead`。シェル経由の読み取りをどんな書き方でも拒否 |
| 秘密(Read ツール経由) | permissions | `deny: Read(/.env)` 等 |
| ネットワーク | サンドボックス | 許可ドメイン(Python は PyPI と GitHub)以外は確認 |
| うっかりの破壊的操作 | guard フック | 正規表現の best-effort。意図的な回避は防げない |
| 検査の改ざん | permissions `ask` + CI + ブランチ保護 | check.sh・フック・settings の編集は確認 |

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
    "denyRead": ["./**/.env", "./**/.env.*", "~/**/.env", "~/**/.env.*"],
    "allowWrite": ["~/.cache/pip", "~/.cache/pyright-python", "~/.cache/ruff", "~/.cache/uv"]
  },
  "network": { "allowedDomains": ["files.pythonhosted.org", "github.com", "pypi.org", "registry.npmjs.org"] }
}
```
- `failIfUnavailable: true` のため、bubblewrap/socat が無いと Claude Code は起動しない(黙って保護なしで動くより安全)。協業者にも初回のインストールを案内する。
- `allowUnsandboxedCommands: false` で、Claude がサンドボックス外での再実行を求める抜け道を閉じる。
- フックと Read/Edit ツールはサンドボックスの外で動く(Read の秘密は permissions が担当)。
- 読み取りは既定で広い。ほかに守りたいもの(`~/.ssh` 等)は `denyRead` に足す。

## 開発

```bash
python3 -m unittest discover -s tests -v
```
