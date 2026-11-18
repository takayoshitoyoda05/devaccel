# devaccel core — DO NOT EDIT. Add project rules via .claude/project.json "guard".
"""PreToolUse(Bash) guard: stop *accidental* destructive commands.

Scope is deliberately narrow (see docs/design.md D6):
- Destructive / irreversible operations: broad rm -rf, sudo, force push, curl|sh,
  git options that write files or run programs, history-destroying git, DROP TABLE.
- Parallel-PR policy: push only `git push origin HEAD` from a non-default branch, no remote
  changes, no direct gh (the verified PR script is the only gateway).
- It does NOT try to protect secrets such as .env: parsing shell text cannot do that
  reliably. Secrets are protected by the OS-level sandbox (sandbox.filesystem.denyRead)
  and permissions.deny for the Read tool, both in .claude/settings.json.
Rules run on the raw command (heredoc bodies included) to avoid parser differentials.
On internal error it asks instead of allowing.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from devaccel_common import emit, load_config, read_stdin_json, trusted_root  # noqa: E402

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

# ASK rules are convenience checks (not a security boundary): they match only at the start of a
# command segment, so text inside heredoc bodies or strings does not trigger them.
ASK: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*git\s+add\s+(-A\b|--all\b|\.(\s|$))"), "git add -A/. は秘密情報やゴミを含めがちです。対象を確認してください。"),
    (re.compile(r"^\s*git\s+reset\s+--hard\b"), "未コミットの変更が消えます。"),
    (re.compile(r"^\s*git\s+clean\s+-[a-zA-Z]*f"), "未追跡ファイルが消えます。"),
    (re.compile(r"^\s*git\s+(checkout|restore)\s+(--\s+)?\.(\s|$)"), "未コミットの変更が消えます。"),
    (re.compile(r"\b(DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE)\b", re.I), "破壊的な DB 操作です。案を先に示してください。"),
]


# ---- git policy (segment-based; a compound "a && b" is checked per segment) ----
FD = re.compile(r"\s*\d*>&\d+")  # 2>&1 is not a separator
SEP = re.compile(r"&&|\|\||[;&|\n]")
WRAP = r"(?:(?:timeout\s+\S+|time|nice|nohup|command|builtin|env)\s+)*"
GITOPT = r"(?:-\S+\s+(?:[^-\s]\S*\s+)?)*"  # git global options before the subcommand
PUSH = re.compile(r"^\s*(?:\w+=\S*\s+)*" + WRAP + r"git\s+" + GITOPT + r"push\b")
OK_PUSH = re.compile(r"^\s*" + WRAP + r"git push(?: (?:-u|--set-upstream))? origin HEAD\s*$")
REDIRECT = re.compile(r"(?:^|[\s;&|(])(?:cd|pushd)\s|\bgit\s+(?:-C|--git-dir|--work-tree)\b|\bGIT_(?:DIR|WORK_TREE)=")
REMOTE = re.compile(
    r"\bgit\s+" + GITOPT + r"(?:remote\s+(?:add|set-url|rename|remove|rm)\b"
    r"|config\b[^;&|\n]*\b(?:remote\.|url\.|branch\.\S*\.(?:remote|pushremote|merge)|push\.|credential\.))"
)
GH = re.compile(r"^\s*(?:\w+=\S*\s+)*" + WRAP + r"gh\s")
OUTPUT_CMDS = re.compile(r"\bgit\s+" + GITOPT + r"(diff|log|show|format-patch|difftool|grep|stash\s+show)\b")
# matched on quote/backslash-stripped text. The scripts run only in these exact forms; merging is human-only.
PR_SCRIPT = re.compile(r"devaccel_(?:pr|land)\b")
# no expansions or redirections: $(...) in an argument runs after the lock check (TOCTOU)
PR_RUN = re.compile(r"^\s*python3 \.claude/hooks/devaccel_pr\.py(?:\s[^`$<>]*)?\s*$")
LAND_RUN = re.compile(r"^\s*python3 \.claude/hooks/devaccel_land\.py(?: --dry-run)?\s*$")
# reads that cannot execute anything (no sed/less/rg: they have exec escapes)
READERS = re.compile(r"^\s*(?:cat|head|tail|wc|ls|grep|git (?:diff|log|show|status))\s[^`$<>]*$")
LAND_MERGE = re.compile(r"devaccel_land.*\s-+m", re.S)  # defense in depth, anywhere in the command
PIPE = re.compile(r"(?<!\|)\|(?!\|)")
# env changes before running the PR/land script could shadow python3 or its imports (PATH, PYTHONPATH, ...)
ENV_CHANGE = re.compile(r"(?:^|[\s;&|(])(?:export|env|declare|typeset|alias|source|unset|\.)\s|(?:^|[\s;&|(])\w+=")
HOOKS_GLOB = re.compile(r"\.claude/hooks/\S*[*?\[{]|\.claude/hooks/?\s|\.claude/hook[*?\[{]|\.claude/[*?\[{]")
PTY = re.compile(r"(?:^|[\s;&|(])(?:script|unbuffer|expect|empty|socat)\s")
# anywhere in a segment (bash -c "git push ...", xargs git push, eval ...): not just at the start
PUSH_ANY = re.compile(r"(?<![\w./-])git\s+(?:\S+\s+)*?push\b")
GH_ANY = re.compile(r"(?<![\w./-])gh\s+(?:pr|api|repo|release|run|workflow|auth|secret|variable|issue|label|"
                    r"gist|ssh-key|gpg-key|ruleset|cache|codespace|extension|alias)\b")
LAUNCHER = re.compile(r"(?<![\w./-])(?:eval|exec|xargs|(?:ba|z|da)?sh\s+-\w*c|python3?\s+-c|perl\s+-e|"
                      r"node\s+-e|ruby\s+-e|find\b[^;&|\n]*-exec)\b")
PR_FILES = ("devaccel_pr.py", "devaccel_land.py", "devaccel_common.py", "stop_gate.py")


def _segments(command: str) -> list[str]:
    flat = command.replace("'", "").replace('"', "").replace("\\", "")
    return [s for s in SEP.split(FD.sub(" ", flat)) if s.strip()]


def _current_branch(cwd: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(cwd), "symbolic-ref", "--short", "-q", "HEAD"],
                           capture_output=True, text=True, errors="replace", timeout=5)
        return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _protected_branches(cwd: Path, cfg: dict) -> set[str]:
    names = {"main", "master", cfg.get("scale", {}).get("base_branch", "main")}
    try:
        r = subprocess.run(["git", "-C", str(cwd), "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD"],
                           capture_output=True, text=True, errors="replace", timeout=5)
        if r.stdout.strip():
            names.add(r.stdout.strip().split("/", 1)[-1])
    except (OSError, subprocess.TimeoutExpired):
        pass
    return names


def _pr_script_intact(cwd: Path, project: Path) -> bool:
    """The PR script runs from the (possibly modified) worktree: compare with the main lock."""
    lock = project / ".claude" / "devaccel.lock"
    try:
        locked = {ln.split()[1]: ln.split()[0] for ln in lock.read_text().splitlines()
                  if ln and not ln.startswith(("#", "version", "ref"))}
    except (OSError, IndexError):
        return False
    for name in PR_FILES:
        rel = f".claude/hooks/{name}"
        try:
            if hashlib.sha256((cwd / rel).read_bytes()).hexdigest() != locked.get(rel):
                return False
        except OSError:
            return False
    return True


def _git_policy(command: str, cfg: dict, cwd: Path, project: Path) -> tuple[str, str] | None:
    segs = _segments(command)
    for s in segs:
        if LAUNCHER.search(s) and re.search(r"(?<![\w./-])(?:git|gh)\b", s):
            return "deny", "bash -c / eval / xargs などを経由した git・gh は使えません。直接実行してください。"
        if GH_ANY.search(s) and not GH.search(s):
            return "deny", "gh は直接使えません。PR は python3 .claude/hooks/devaccel_pr.py で作ってください。"
        if PUSH_ANY.search(s) and not OK_PUSH.search(s):
            return "deny", "push は `git push origin HEAD`(作業ブランチを origin へ)を単独で実行する形だけです。"
        if REMOTE.search(s):
            return "deny", "git のリモート設定・push 設定は変更できません。"
        if GH.search(s):
            return "deny", "gh は直接使えません。PR は python3 .claude/hooks/devaccel_pr.py で作ってください。"
    pushes = [s for s in segs if PUSH.search(s)]
    if pushes:
        if any(not OK_PUSH.search(s) for s in pushes):
            return "deny", "push は `git push origin HEAD`(作業ブランチを origin へ)だけです。force・他ブランチ・他リモートは不可。"
        if REDIRECT.search(command):
            return "deny", "push と cd / git -C を同じコマンドにしないでください(別コマンドで)。"
        branch = _current_branch(cwd)
        if not branch or branch in _protected_branches(cwd, cfg):
            return "deny", f"デフォルトブランチ({branch or 'detached HEAD'})へは push できません。作業ブランチを切ってください。"
    flat = command.replace("'", "").replace('"', "").replace("\\", "")
    if PTY.search(flat):
        return "deny", "script / unbuffer / expect などの疑似端末ラッパーは使えません(人の確認を偽装できるため)。"
    if HOOKS_GLOB.search(flat):
        return "deny", ".claude/hooks/ のファイルはワイルドカードや展開を使わず、名前を正確に書いてください。"
    if LAND_MERGE.search(flat):
        return "deny", "devaccel_land.py --merge(マージ)は人が端末で実行します。"
    segs_flat = [s for s in SEP.split(FD.sub(" ", flat)) if s.strip()]
    runs = [s for s in segs_flat if PR_SCRIPT.search(s) and not READERS.search(s)]
    if runs and (len(runs) > 1 or any(not READERS.search(s) for s in segs_flat if s not in runs)
                 or ENV_CHANGE.search(flat)):
        # allowlist, not a denylist: the script runs alone (only plain reads may share the command)
        return "deny", "devaccel_pr/land は単独のコマンドで実行してください(環境変数・cd・関数定義などと並べない)。"
    if PR_SCRIPT.search(flat) and PIPE.search(flat) and not all(READERS.search(s) for s in segs_flat):
        return "deny", "devaccel_pr/land を名指しするコマンドで、他のコマンドへのパイプは使えません。"
    for s in segs_flat:
        if not PR_SCRIPT.search(s) or READERS.search(s):
            continue
        if "devaccel_land" in s and not LAND_RUN.search(s):
            return "deny", ("devaccel_land.py は `python3 .claude/hooks/devaccel_land.py [--dry-run]` の形だけ。"
                            "--merge(マージ)は人が端末で実行します。")
        if "devaccel_pr" in s and not PR_RUN.search(s):  # its arguments are harmless; the path is not
            return "deny", "devaccel_pr.py は `python3 .claude/hooks/devaccel_pr.py ...` の形で直接実行してください。"
    if PR_SCRIPT.search(flat) and not _pr_script_intact(cwd, project):
        return "deny", "devaccel_pr.py / devaccel_land.py(または依存)が lock と一致しません。改変されたスクリプトは実行できません。"
    for s in segs:  # --output / --ext-diff (incl. abbreviations) only matter for these subcommands
        if OUTPUT_CMDS.search(s):
            if re.search(r"[`]|\$(?!\{?IFS)|\{[^}]*(,|\.\.)|\{[^}]*$", s.replace("@{", "")):
                return "ask", "git diff/log 等に展開が含まれています。内容を確認してください。"
            for w in re.split(r"(?:\s|\$\{?IFS\}?|[()<>])+", s):
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


def decide(command: str, cfg: dict, cwd: Path | None = None, project: Path | None = None) -> tuple[str, str] | None:
    flat = command.replace('"', "").replace("'", "").replace("\\", "")  # rm -rf "/" -> rm -rf /
    extra = cfg.get("guard", {})
    for rx, why in DENY + _compile_extra(extra.get("deny_regex", []), "guard.deny_regex"):
        if rx.search(flat):
            return "deny", why
    cwd = cwd or Path.cwd()
    hit = _git_policy(command, cfg, cwd, project or cwd)
    if hit:
        return hit
    for rx, why in ASK:
        if any(rx.search(s) for s in _segments(command)):
            return "ask", why
    for rx, why in _compile_extra(extra.get("ask_regex", []), "guard.ask_regex"):
        if rx.search(flat):
            return "ask", why
    return None


def main() -> int:
    data = read_stdin_json()
    command = (data.get("tool_input") or {}).get("command", "")
    if not command:
        return 0
    project = trusted_root(data)  # lock and config come from the main checkout, never a worktree
    verdict = decide(command, load_config(project), Path(data.get("cwd") or project), project)
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
