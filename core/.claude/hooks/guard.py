# devaccel core — DO NOT EDIT. Add project rules via .claude/project.json "guard".
"""PreToolUse(Bash) guard: only rules that permission patterns cannot express.

Best-effort: a determined bypass (eval, base64, scripts) is not prevented.
The real safety net is permissions + review + CI. On internal error it asks.

Declarative rules (sudo, .env reads, edits to the checks themselves) live in
.claude/settings.json permissions; this hook covers argument-dependent cases.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from devaccel_common import emit, load_config, project_root, read_stdin_json  # noqa: E402

# rm with both -r and -f aimed at a broad target (/, ~, $HOME, *, ., .., .git)
_RM = re.compile(
    r"\brm\s+(?=[^;&|]*(-[a-zA-Z]*r|--recursive))(?=[^;&|]*(-[a-zA-Z]*f|--force))[^;&|]*?"
    r"(?:\s|^)(?:/|~/?|\$HOME/?|\*|\./?|\.\./?|\.git/?|/\*)(?=\s|$|;|&|\|)"
)

DENY: list[tuple[re.Pattern, str]] = [
    (_RM, "広範囲の rm -rf は禁止です。対象を具体的なパスに絞ってください。"),
    (re.compile(r"\bsudo\b"), "sudo は使えません。必要ならユーザーに依頼してください。"),
    (
        re.compile(r"\bgit\s+push\b[^;&|]*\s(--force(?!-with-lease)|-f\b|\+\S)"),
        "force push は禁止です(--force-with-lease はユーザー確認の上で)。",
    ),
    (
        re.compile(r"\b(curl|wget)\b[^;&]*\|\s*(sudo\s+)?(ba|z)?sh\b"),
        "ダウンロードしたスクリプトをそのまま実行しないでください。",
    ),
    (
        re.compile(r"(^|[\s=:/<>(){},])\.env(?!\.example\b)(\.[\w-]+)?(?=$|[\s/;&|)<>(){},*?\[\]])"),
        ".env には触れないでください(.env.example は可)。",
    ),
    (  # globs that could expand to .env without spelling it: .e*, .en?, .en[v], {.e,...}
        re.compile(r"(?<![\w.-])\.e[\w.-]*[*?\[{]"),
        ".env を含みうるワイルドカードは使わないでください。",
    ),
]

ASK: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bgit\s+add\s+(-A\b|--all\b|\.(\s|$))"), "git add -A/. は秘密情報やゴミを含めがちです。対象を確認してください。"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "未コミットの変更が消えます。"),
    (re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"), "未追跡ファイルが消えます。"),
    (re.compile(r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)"), "未コミットの変更が消えます。"),
    (re.compile(r"\b(DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE)\b", re.I), "破壊的な DB 操作です。案を先に示してください。"),
]


def _compile_extra(patterns: list, label: str) -> list[tuple[re.Pattern, str]]:
    out = []
    for p in patterns:
        try:
            out.append((re.compile(p), f"project.json {label}"))
        except (re.error, TypeError) as e:  # a bad custom rule must not disable the built-ins
            print(f"[devaccel] ignoring invalid {label} {p!r}: {e}", file=sys.stderr)
    return out


def decide(command: str, cfg: dict) -> tuple[str, str] | None:
    command = command.replace('"', "").replace("'", "").replace("\\", "")  # rm -rf "/" -> rm -rf /
    extra = cfg.get("guard", {})
    deny = DENY + _compile_extra(extra.get("deny_regex", []), "guard.deny_regex")
    ask = ASK + _compile_extra(extra.get("ask_regex", []), "guard.ask_regex")
    for rx, why in deny:
        if rx.search(command):
            return "deny", why
    for rx, why in ask:
        if rx.search(command):
            return "ask", why
    return None


def main() -> int:
    data = read_stdin_json()
    command = (data.get("tool_input") or {}).get("command", "")
    if not command:
        return 0
    verdict = decide(command, load_config(project_root(data)))
    if verdict:
        decision, why = verdict
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": f"[devaccel guard] {why}",
                }
            }
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # fail closed: ask the human instead of silently allowing
        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                     "permissionDecisionReason": f"[devaccel guard] internal error: {e}"}})
        sys.exit(0)
