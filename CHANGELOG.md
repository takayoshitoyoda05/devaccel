# Changelog

## 0.1.3 (2026-11-18)
- doctor: setup 済みの `devaccel:filled` 目印を未記入と誤判定していたのを修正。

## 0.1.2 (2026-11-18)
- guard: `.env*` / `{.env,}` / `.env>x` / `.e*` などワイルドカード・波括弧・リダイレクト経由の .env 参照も拒否。

## 0.1.1 (2026-11-18)
- guard: 内部エラー時は許可せず確認に倒す / 不正なカスタム正規表現で組み込み規則が無効にならない / クォート・長いフラグ・`+refspec` push・コマンドを問わない .env 参照に対応。best-effort であることを明記。
- update/doctor: `.claude/` 外を指すロック行を無視(パス・トラバーサルによる削除を防止)。

## 0.1.0 (2026-11-18)
- 初版: guard / stop_gate フック、setup・tune・design・verify-app スキル、Python プリセット(ruff/pyright/pytest)、install・update・doctor。
