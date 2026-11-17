# Changelog

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
