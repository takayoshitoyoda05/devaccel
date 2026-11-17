# devaccel core — DO NOT EDIT. Add project rules via .claude/project.json "guard".
"""PreToolUse(Bash) guard: only rules that permission patterns cannot express.

Best-effort: a determined bypass (eval, base64, scripts) is not prevented.
The real safety net is permissions + review + CI. On internal error it asks.

Declarative rules (sudo, .env reads, edits to the checks themselves) live in
.claude/settings.json permissions; this hook covers argument-dependent cases.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
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
    (  # read-only git commands that can write files or run programs (bypass allow rules)
        re.compile(
            r"\bgit\b[^;&|]*(\s|\$\{?IFS\}?)"
            r"(--(o(u(t(p(u(t)?)?)?)?)?|ext(-(d(i(f(f)?)?)?)?)?)(=|\s|$)"  # incl. abbreviations
            r"|-c\s*\S*(pager|editor|ssh|exec|textconv|fsmonitor|alias)\S*=)",
            re.I,
        ),
        "git の --output / --ext-diff / -c による外部コマンド指定は使えません。",
    ),
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
    (  # backstop, independent of the directory listing: .e*, .en?, .en[v], .e{n,x}v ...
        re.compile(r"(?<![\w.-])\.e[\w.-]*[*?\[{]"),
        ".env を含みうるワイルドカードは使わないでください。",
    ),
    (  # bare-dot globs: .?nv, .*, .[a-z]nv ... (bash matches dotfiles only with a leading dot)
        re.compile(r"(?<![\w.-])\.[*?\[{]"),
        "ドットファイルにマッチするワイルドカードは使わないでください。",
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


_ENV_NAME = re.compile(r"^\.env(\.[\w.-]+)?$")
_GLOB = re.compile(r"[*?\[{]")


def _secret_files(directory: Path) -> list[str]:
    try:
        return [n for n in os.listdir(directory) if _ENV_NAME.match(n) and n != ".env.example"]
    except OSError:
        return []


def _expands_to_secret(command: str, cwd: Path) -> str | None:
    """Expand glob-like words against the real directory instead of guessing with regexes.

    Returns "deny" if a glob/brace word can match an existing .env* file, "ask" if a
    dot-word is built from $var / `cmd` expansion (cannot be resolved statically).
    """
    try:
        words = shlex.split(command, comments=False, posix=True)
    except ValueError:
        words = command.split()
    moved = False  # after cd/pushd, globs resolve against a directory we did not list
    for w in words:
        if w in ("cd", "pushd"):
            moved = True
        for part in re.split(r"[=:<>();&|]", w):
            if not part:
                continue
            head, base = os.path.split(part)
            dynamic = "$" in part or "`" in part
            if dynamic and ("/." in part or part.startswith(".") or "{" in part):
                return "ask"
            if not (_GLOB.search(base) and base.startswith(("." , "{", "["))):
                continue
            if base.count("{") > 1 or re.search(r"\{[^}]*\{", base):
                return "deny"  # nested / multiple brace groups: do not try to emulate bash
            if dynamic or moved or "~" in head or _GLOB.search(head):
                return "ask"
            directory = (cwd / head) if head else cwd
            if not directory.is_dir():
                return "ask"
            names = _secret_files(directory)
            alts = [base]
            m = re.search(r"\{([^{}]*)\}", base)
            if m:
                alts = [base[: m.start()] + a + base[m.end():] for a in m.group(1).split(",")]
            if any(fnmatch.fnmatchcase(n, a) for n in names for a in alts if a):
                return "deny"
    return None


def _git_check(command: str) -> tuple[str, str] | None:
    """Token-level git check: abbreviations of --output/--ext-diff, dynamic words."""
    if not re.search(r"\bgit\b", command):
        return None
    if "$" in command or "`" in command:
        return "ask", "git コマンドに変数・コマンド展開が含まれています。内容を確認してください。"
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return "ask", "git コマンドを解析できません。内容を確認してください。"
    for w in words:
        if w.startswith("--") and len(w) > 2:
            name = w[2:].split("=", 1)[0].lower()
            if "output".startswith(name) or "ext-diff".startswith(name):
                return "deny", "git の --output / --ext-diff(省略形を含む)は使えません。"
    return None


def decide(command: str, cfg: dict, cwd: Path | None = None) -> tuple[str, str] | None:
    git_hit = _git_check(command)
    if git_hit and git_hit[0] == "deny":
        return git_hit
    hit = _expands_to_secret(command, cwd or Path.cwd())
    if hit == "deny":
        return "deny", "このワイルドカードは .env に展開されます。.env には触れないでください。"
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
    if git_hit:
        return git_hit
    if hit == "ask":
        return "ask", "変数展開でドットファイル名を組み立てています。対象を確認してください。"
    return None


def main() -> int:
    data = read_stdin_json()
    command = (data.get("tool_input") or {}).get("command", "")
    if not command:
        return 0
    root = project_root(data)
    verdict = decide(command, load_config(root), Path(data.get("cwd") or root))
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
