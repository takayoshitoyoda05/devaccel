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
| `.claude/hooks/guard.py` | core | 危険な Bash(広範囲 rm -rf、sudo、force push、curl\|sh、.env 読み取り)を拒否/確認 |
| `.claude/hooks/stop_gate.py` | core | 終了時に `check.sh fast`。失敗段だけ返す・3 ラウンドで人に報告・L/テスト弱体化を表示 |
| `.claude/skills/devaccel-{setup,tune}` | core | 手動専用(説明は常駐しない) |
| `CLAUDE.md` | project | 進め方(S/M/L)と検証の作法 |
| `.claude/skills/design` | project | L 規模: 質問 → 受け入れ条件つき設計書 → 仕様照合 |
| `.claude/skills/verify-app` | project | 「完了」前に実際に動かす手順(setup が生成) |
| `scripts/check.sh` | project | `fast`(ゲート・自動整形あり)/ `full`(CI)。段を並べるだけ |
| `.claude/project.json` | project | 挙動の調整点はすべてここ |
| `.claude/settings.json` | project | permissions とフック 2 行(install 時に 1 回だけ書く) |
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

## より強い保護: サンドボックス(任意・推奨)

guard は「うっかり」を止める best-effort です(シェルは表現力が高く、正規表現では完全に塞げない)。
シェルコマンドを OS レベルで縛るには Claude Code のサンドボックスを併用する(公式: https://code.claude.com/docs/en/sandboxing)。

```bash
sudo apt-get install bubblewrap socat   # WSL2 / Linux。WSL1 は非対応
```
`.claude/settings.json` に追記(コミットすれば全員に効く。`/sandbox` は local 設定に書く):
```json
{
  "sandbox": {
    "enabled": true,
    "filesystem": { "denyRead": ["~/**/.env"] }
  }
}
```
- 書き込みは作業ディレクトリと一時領域のみ、ネットワークは許可ドメイン経由のみになる。読み取りは既定で広いので `denyRead` で秘密を閉じる。
- フックと Read/Edit ツールはサンドボックスの外で動く。Read ツールの `.env` は permissions の deny が担う(devaccel が設定済み)。
- 起動後 `/sandbox` の Dependencies タブで有効を確認。

## 開発

```bash
python3 -m unittest discover -s tests -v
```
