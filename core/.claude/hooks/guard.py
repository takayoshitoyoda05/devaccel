# devaccel core — DO NOT EDIT. Add project rules via .claude/project.json "guard".
"""PreToolUse(Bash) guard: stop *accidental* destructive commands.

Scope is deliberately narrow (see docs/design.md D6):
- Destructive / irreversible operations: broad rm -rf, sudo, force push, curl|sh,
  git options that write files or run programs, history-destroying git, DROP TABLE.
- It does NOT try to protect secrets such as .env: parsing shell text cannot do that
  reliably. Secrets are protected by the OS-level sandbox (sandbox.filesystem.denyRead)
  and permissions.deny for the Read tool, both in .claude/settings.json.
Rules run on the raw command (heredoc bodies included) to avoid parser differentials.
On internal error it asks instead of allowing.
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
        re.compile(r"\bgit\b[^;&|]*-c\s*\S*(pager|editor|ssh|exec|textconv|fsmonitor|alias)\S*=", re.I),
        "git -c による外部コマンド指定は使えません。",
    ),
]

ASK: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bgit\s+add\s+(-A\b|--all\b|\.(\s|$))"), "git add -A/. は秘密情報やゴミを含めがちです。対象を確認してください。"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "未コミットの変更が消えます。"),
    (re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"), "未追跡ファイルが消えます。"),
    (re.compile(r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)"), "未コミットの変更が消えます。"),
    (re.compile(r"\b(DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE)\b", re.I), "破壊的な DB 操作です。案を先に示してください。"),
]


def _git_options(command: str) -> tuple[str, str] | None:
    """git accepts abbreviated long options (--out= == --output=): check per token."""
    flat = command.replace("'", "").replace('"', "").replace("\\", "")
    if not re.search(r"\bgit\b", flat):
        return None
    if re.search(r"[$`{]", flat):  # any expansion (vars, commands, braces): let the human look
        return "ask", "git コマンドに展開($ ` {)が含まれています。内容を確認してください。"
    for w in re.split(r"(?:\s|\$\{?IFS\}?|[;&|()<>])+", flat):
        if w.startswith("--") and len(w) > 2:
            name = w[2:].split("=", 1)[0].lower()
            if "output".startswith(name) or "ext-diff".startswith(name):
                return "deny", "git の --output / --ext-diff(省略形を含む)は使えません。"
    return None


def _compile_extra(patterns: list, label: str) -> list[tuple[re.Pattern, str]]:
    out = []
    for p in patterns:
        try:
            out.append((re.compile(p), f"project.json {label}"))
        except (re.error, TypeError) as e:  # a bad custom rule must not disable the built-ins
            print(f"[devaccel] ignoring invalid {label} {p!r}: {e}", file=sys.stderr)
    return out


def decide(command: str, cfg: dict, cwd: Path | None = None) -> tuple[str, str] | None:  # noqa: ARG001
    flat = command.replace('"', "").replace("'", "").replace("\\", "")  # rm -rf "/" -> rm -rf /
    extra = cfg.get("guard", {})
    for rx, why in DENY + _compile_extra(extra.get("deny_regex", []), "guard.deny_regex"):
        if rx.search(flat):
            return "deny", why
    hit = _git_options(command)
    if hit:
        return hit
    for rx, why in ASK + _compile_extra(extra.get("ask_regex", []), "guard.ask_regex"):
        if rx.search(flat):
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
