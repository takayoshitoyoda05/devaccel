#!/usr/bin/env python3
"""devaccel kit: install / update / doctor (python3 stdlib only).

Run from the root of the target project:
    ~/devaccel/install.sh      # first time
    ~/devaccel/update.sh       # replace core files (refuses if hand-edited)
    ~/devaccel/doctor.sh       # health check
    ~/devaccel/protect.sh      # protect the base branch on GitHub (public repo or Pro)
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
CORE = KIT / "core"
SEED = KIT / "seed"
LOCK = ".claude/devaccel.lock"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE / ".claude" / "hooks"))
from devaccel_common import DEFAULTS  # noqa: E402

HOOK_CMDS = {
    "guard": 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/guard.py',
    "stop": 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/stop_gate.py',
}

# Tool-level pieces: each contributes check stages and allow rules. Presets are lists of pieces.
PIECES = {
    "ruff": {
        "fast": [
            "stage format $R ruff format --extend-exclude .claude .",
            "stage lint $R ruff check --fix --quiet --output-format concise --extend-exclude .claude .",
        ],
        "full": [
            "stage format $R ruff format --check --extend-exclude .claude .",
            "stage lint $R ruff check --output-format concise --extend-exclude .claude .",
        ],
        "allow": ["Bash(uv run ruff *)", "Bash(ruff *)"],
    },
    "pyright": {
        "fast": ["stage types $R pyright"],
        "full": ["stage types $R pyright"],
        "allow": ["Bash(uv run pyright*)", "Bash(pyright*)"],
    },
    "pytest": {
        "fast": ['stage tests pt -x -q --tb=short -m "not slow"'],
        "full": ["stage tests pt -q --tb=short"],
        "allow": ["Bash(uv run pytest*)", "Bash(pytest*)"],
    },
}
PRESETS = {"python": ["ruff", "pyright", "pytest"]}

CHECK_HEAD = """#!/usr/bin/env bash
# scripts/check.sh — project-owned: edit freely (one `stage` per line).
# usage: scripts/check.sh fast   (devaccel Stop gate; may auto-fix formatting)
#        scripts/check.sh full   (CI / before push; never modifies files)
# Timeouts, output trimming and logging live in .claude/hooks/stop_gate.py.
set -uo pipefail
cd "${DEVACCEL_ROOT:-$(dirname "$0")/..}"  # DEVACCEL_ROOT: gate/PR point it at a worktree
MODE="${1:-full}"
R="__RUNNER__"   # command prefix, e.g. "uv run" ("" = tools on PATH)

stage() {
  local name="$1"; shift
  local t0=$SECONDS out rc
  echo "== stage: $name"
  out="$("$@" 2>&1)"; rc=$?
  [ -n "$out" ] && printf '%s\\n' "$out"
  if [ $rc -eq 127 ] || { [ $rc -eq 2 ] && grep -q "Failed to spawn" <<<"$out"; }; then
    if [ "$MODE" = full ]; then echo "== failed: $name ($((SECONDS-t0))s) tool missing"; exit 1; fi
    echo "== missing: $name ($((SECONDS-t0))s)"; return 0
  fi
  if [ $rc -ne 0 ]; then echo "== failed: $name ($((SECONDS-t0))s)"; exit 1; fi
  echo "== ok: $name ($((SECONDS-t0))s)"
}
pt() { $R pytest "$@"; local rc=$?; [ $rc -eq 5 ] && return 0; return $rc; }  # 5 = no tests

case "$MODE" in
"""

WORKFLOW_UV = """name: check
on: [push, pull_request]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4
      - uses: astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86  # v5
      - run: uv sync --all-extras --dev
      - run: scripts/check.sh full
"""

WORKFLOW_GENERIC = """name: check
on: [push, pull_request]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4
      # add your toolchain setup here (see /devaccel-setup), then:
      - run: scripts/check.sh full
"""

WORKFLOW_PIP = """name: check
on: [push, pull_request]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5
        with:
          python-version: "3.12"
      - run: pip install ruff pyright pytest $( [ -f requirements.txt ] && echo "-r requirements.txt" )
      - run: scripts/check.sh full
"""

# .devaccel/ = scratch for PR notes / commit messages (writes under .claude/ always need approval)
GITIGNORE_LINES = ["# devaccel", ".claude/state/", ".claude/settings.local.json", ".claude/worktrees/", ".devaccel/",
                   "__pycache__/"]


# ---------- helpers ----------


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def kit_version() -> str:
    return (KIT / "VERSION").read_text().strip()


def kit_ref() -> str:
    try:
        r = subprocess.run(["git", "-C", str(KIT), "describe", "--tags", "--always", "--dirty"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def core_files() -> list[str]:
    return sorted(
        str(p.relative_to(CORE)) for p in CORE.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )


def seed_files() -> list[str]:
    return sorted(str(p.relative_to(SEED)) for p in SEED.rglob("*") if p.is_file())


def read_lock(root: Path) -> tuple[dict, dict]:
    meta, files = {}, {}
    p = root / LOCK
    if not p.exists():
        return meta, files
    for line in p.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        a, _, b = line.partition(" ")
        if a in ("version", "ref"):
            meta[a] = b.strip()
        else:
            files[b.strip()] = a
    return meta, files


def write_lock(root: Path, files: list[str]) -> None:
    _no_symlink(root, LOCK)
    lines = ["# devaccel lock — one line per core file (sorted). Do not edit by hand.",
             f"version {kit_version()}", f"ref {kit_ref()}"]
    lines += [f"{sha(root / f)}  {f}" for f in sorted(files)]
    (root / LOCK).write_text("\n".join(lines) + "\n")


def detect(root: Path) -> tuple[list[str], str]:
    """(presets, runner)"""
    py = any((root / f).exists() for f in ("pyproject.toml", "setup.py", "setup.cfg")) \
        or any(root.glob("requirements*.txt")) or any(root.glob("*.py")) or any(root.glob("src/**/*.py"))
    presets = ["python"] if py else []
    uv = (root / "uv.lock").exists() or (
        (root / "pyproject.toml").exists() and not any(root.glob("requirements*.txt")))
    return presets, ("uv run" if (py and uv) else "")


def render_check(presets: list[str], runner: str) -> str:
    pieces = [PIECES[n] for p in presets for n in PRESETS[p]]
    body = CHECK_HEAD.replace("__RUNNER__", runner)
    for mode in ("fast", "full"):
        body += f"  {mode})\n"
        stages = [s for pc in pieces for s in pc[mode]]
        body += "".join(f"    {s}\n" for s in stages) or '    echo "no checks configured: edit scripts/check.sh"\n'
        body += "    ;;\n"
    body += '  *) echo "usage: $0 fast|full" >&2; exit 2 ;;\nesac\n'
    return body


SANDBOX = {
    "enabled": True,
    "failIfUnavailable": True,          # fail closed: no silent unsandboxed fallback
    "allowUnsandboxedCommands": False,  # ignore dangerouslyDisableSandbox retries
    "autoAllowBashIfSandboxed": True,   # sandboxed commands need no prompt (parallel units can't answer)
    # secrets: OS-level read denial for shell commands (the Read tool uses permissions.deny).
    # "./" = project root in project settings. No "~/**" globs: the sandbox expands them on every Bash
    # call, scanning all of $HOME (measured 4-15 s per call, 0.8.1). Home secrets are named directly.
    # Not ~/.config/gh: the PR script and git push use it inside the sandbox (D12). Other checkouts'
    # .env under $HOME are not covered (accepted for speed; README).
    # denyWrite: the trusted root's verification machinery and gate state (Bash writes; Edit is ask-gated).
    # Paths only (no globs); /batch worktrees under .claude/worktrees/ stay writable.
    "filesystem": {"denyWrite": ["./.claude/hooks", "./.claude/skills", "./.claude/state", "./.claude/devaccel.lock",
                                 "./.claude/project.json", "./.claude/settings.json", "./.claude/settings.local.json",
                                 "./scripts/check.sh"],
                   "denyRead": ["./**/.env", "./**/.env.*", "~/.ssh", "~/.aws", "~/.gnupg", "~/.netrc", "~/.docker/config.json", "~/.kube", "~/.npmrc", "~/.pypirc"]},
}
NET_DOMAINS = {"python": ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org"]}
BASE_DOMAINS = ["github.com", "api.github.com"]  # git push + gh (PR script)
# tool caches outside the project that the toolchain must write to inside the sandbox
CACHE_WRITES = {"python": ["~/.cache/uv", "~/.cache/pip", "~/.cache/pyright-python", "~/.cache/ruff"]}


def sandbox_ready() -> bool:
    return shutil.which("bwrap") is not None and shutil.which("socat") is not None


def render_settings(presets: list[str]) -> dict:
    # Only narrow, known-safe git forms: git accepts abbreviated long options
    # (--out= == --output=), so "git diff *" cannot be made safe by deny rules.
    # Exact forms only (no trailing wildcard); anything else asks.
    allow = ["Bash(scripts/check.sh fast)", "Bash(scripts/check.sh full)",
             "Bash(git status)", "Bash(git status --short)", "Bash(git diff)",
             "Bash(git diff --stat)", "Bash(git diff --name-only)", "Bash(git log --oneline)",
             "Bash(git show --stat)", "Bash(uv sync)",
             # parallel-PR flow (guard enforces: work branch only, origin only, verified script)
             "Bash(git add *)", "Bash(git commit *)", "Bash(git push origin HEAD)",
             "Bash(python3 .claude/hooks/devaccel_pr.py *)", "Bash(python3 .claude/hooks/devaccel_ship.py *)",
             # fan-out: its nested `claude -p` units need the API, so it runs outside the sandbox (below); the
             # guard admits only the exact form, the lock pins the script, and every unit is itself sandboxed
             "Bash(python3 .claude/hooks/devaccel_batch.py *)"]
    for p in presets:
        for n in PRESETS[p]:
            allow += PIECES[n]["allow"]
    sandbox = json.loads(json.dumps(SANDBOX))
    sandbox["excludedCommands"] = ["python3 .claude/hooks/devaccel_batch.py *"]
    domains = sorted(set(BASE_DOMAINS) | {d for p in presets for d in NET_DOMAINS.get(p, [])})
    if domains:
        sandbox["network"] = {"allowedDomains": domains}
    writes = sorted({d for p in presets for d in CACHE_WRITES.get(p, [])})
    if writes:
        sandbox["filesystem"]["allowWrite"] = writes
    return {
        # parallel subagents (/batch units) multiply token use: cap concurrency (official default 20)
        # subagents (/batch units, Explore) default to sonnet: units start cold (no shared cache),
        # so per-unit price dominates. The planner/main session keeps your model.
        "env": {"CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "8", "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"},
        "sandbox": sandbox,
        "permissions": {
            "allow": allow,
            "ask": [
                "Edit(./scripts/check.sh)",
                "Edit(./.claude/hooks/**)",
                "Edit(./.claude/settings.json)",
                "Edit(./.claude/project.json)",
                "Edit(./.github/workflows/**)",
                "Edit(./.claude/state/**)", "Edit(./.claude/devaccel.lock)", "Edit(./.claude/skills/**)",
                "Edit(./.claude/settings.local.json)",
                # the same machinery inside /batch worktrees (.claude/worktrees/<unit>/...)
                "Edit(**/scripts/check.sh)", "Edit(**/.claude/hooks/**)", "Edit(**/.claude/settings.json)",
                "Edit(**/.claude/project.json)", "Edit(**/.github/workflows/**)",
            ],
            # "/path" = project-relative per the permissions docs; "./" kept for older behavior
            "deny": ["Read(**/.env)", "Read(**/.env.*)", "Edit(**/.env)", "Edit(**/.env.*)",
                     "Read(/.env)", "Read(/.env.*)", "Edit(/.env)", "Edit(/.env.*)",
                     "Read(./.env)", "Read(./.env.*)", "Edit(./.env)", "Edit(./.env.*)",
                     "Bash(git * --out*)", "Bash(git * --ext*)", "Bash(gh *)",
                     "Bash(git push --force*)", "Bash(git push -f *)", "Bash(git push * --force*)",
                     "Bash(git remote add *)", "Bash(git remote set-url *)"],
            # no "token hygiene" Read denies: with the sandbox they become filesystem denyRead, which broke
            # Edit in worktrees (0.6.4) and git/uv on uv.lock (0.7.2). Read denies are for secrets only.
        },
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": HOOK_CMDS["guard"], "timeout": 10}]}],
            "Stop": [{"hooks": [
                {"type": "command", "command": HOOK_CMDS["stop"], "timeout": 120}]}],
            # /batch units are subagents: their end is SubagentStop, not Stop
            "SubagentStop": [{"hooks": [
                {"type": "command", "command": HOOK_CMDS["stop"], "timeout": 120}]}],
        },
    }


def _no_symlink(root: Path, rel: str) -> None:
    """Refuse to write rel if it or any parent under root is a symlink (would write outside the project)."""
    p = root / rel
    if p.is_symlink():
        raise SystemExit(f"error: {p} is a symlink; refusing to write through it")
    for parent in p.relative_to(root).parents:
        if (root / parent).is_symlink():
            raise SystemExit(f"error: {root / parent} is a symlink; refusing to write {rel} through it")


def write_new(root: Path, rel: str, content: str | None = None, src: Path | None = None) -> bool:
    dst = root / rel
    if dst.exists() or dst.is_symlink():  # a dangling symlink would make us write outside the project
        return False
    for parent in dst.relative_to(root).parents:
        if (root / parent).is_symlink():
            raise SystemExit(f"error: {root / parent} is a symlink; refusing to write {rel} through it")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src is not None:
        shutil.copy2(src, dst)
    else:
        dst.write_text(content or "")
    return True


# ---------- commands ----------


def cmd_install(root: Path) -> int:
    if (root / LOCK).exists():
        print("devaccel is already installed here. Use update.sh.")
        return 1
    if not (root / ".git").exists():
        print("warning: not a git repository root. The Stop gate is inactive outside git.")
    presets, runner = detect(root)
    created, kept = [], []

    clash = [rel for rel in core_files() if (root / rel).exists() and sha(root / rel) != sha(CORE / rel)]
    if clash:  # check everything before writing anything: no half-installed core without a lock
        print("error: these already exist and differ. Move them away and retry:\n  " + "\n  ".join(clash))
        return 1
    for rel in core_files():
        dst = root / rel
        _no_symlink(root, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CORE / rel, dst)
        created.append(rel)

    for rel in seed_files():
        (created if write_new(root, rel, src=SEED / rel) else kept).append(rel)

    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["presets"] = presets
    gen = {
        ".claude/project.json": json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
        "scripts/check.sh": render_check(presets, runner),
        ".github/workflows/check.yml": WORKFLOW_UV if runner else WORKFLOW_PIP if presets else WORKFLOW_GENERIC,
    }
    for rel, content in gen.items():
        (created if write_new(root, rel, content) else kept).append(rel)
    if "scripts/check.sh" in created:
        os.chmod(root / "scripts/check.sh", 0o755)

    if write_new(root, ".claude/settings.json",
                 json.dumps(render_settings(presets), indent=2, ensure_ascii=False) + "\n"):
        created.append(".claude/settings.json")
    else:
        kept.append(".claude/settings.json")
        print("\n! .claude/settings.json already exists; devaccel does not merge it.")
        print("  Merge these keys yourself (hooks incl. SubagentStop, permissions, sandbox, env), then run doctor.sh:")
        print(json.dumps(render_settings(presets), indent=2, ensure_ascii=False))

    gi = root / ".gitignore"
    text = gi.read_text() if gi.exists() else ""
    missing = [ln for ln in GITIGNORE_LINES if ln not in text.splitlines()]
    if missing:
        _no_symlink(root, ".gitignore")
        gi.write_text(text + ("" if text.endswith("\n") or not text else "\n") + "\n".join(missing) + "\n")

    write_lock(root, core_files())
    if not sandbox_ready():
        print("\n! sandbox is enabled in settings.json but bubblewrap/socat are missing.")
        print("  Install once:  sudo apt-get install bubblewrap socat   (then restart Claude Code)")
    print(f"devaccel {kit_version()} installed. presets={presets or 'none'} runner={runner or 'PATH'}")
    print("created: " + ", ".join(created))
    if kept:
        print("kept existing (not touched): " + ", ".join(kept))
    print("\nnext: start `claude` here and run /devaccel-setup, then commit.")
    return 0


def cmd_update(root: Path) -> int:
    meta, locked = read_lock(root)
    bad = [f for f in locked if not _safe_core_path(root, f)]
    for f in bad:
        print(f"warning: ignoring lock entry outside .claude/: {f!r}")
        del locked[f]
    if not locked:
        print("no devaccel.lock here. Run install.sh first.")
        return 1
    edited = [f for f, h in locked.items() if (root / f).exists() and sha(root / f) != h]
    if edited:
        print("update stopped: core files were edited by hand (core is not meant to be edited):")
        for f in edited:
            new = CORE / f
            a = (root / f).read_text().splitlines(keepends=True)
            b = new.read_text().splitlines(keepends=True) if new.exists() else []
            sys.stdout.writelines(difflib.unified_diff(a, b, f"project/{f}", f"kit/{f}"))
        print("\nMove the customization to .claude/project.json (or a project-owned file), "
              "restore the file, then rerun. Old kit version: " + meta.get("ref", "?"))
        return 1

    new_files = core_files()
    clash = [r for r in new_files if r not in locked and (root / r).exists() and sha(root / r) != sha(CORE / r)]
    if clash:  # a path that becomes core in this version already holds a user's file
        print("update stopped: these paths become kit-owned in this version but hold your own files:\n  "
              + "\n  ".join(clash) + "\nMove them away (or into project.json / a project-owned file), then rerun.")
        return 1
    root_claude = root / ".claude"
    with tempfile.TemporaryDirectory(dir=root_claude, prefix=".devaccel-staging-") as tmp:
        staging = Path(tmp)
        for rel in new_files:  # stage everything first; nothing touched if this fails
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CORE / rel, dst)
        changed = [r for r in new_files if not (root / r).exists() or sha(root / r) != sha(staging / r)]
        for rel in new_files:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / rel, root / rel)
    removed = [f for f in locked if f not in new_files and _safe_core_path(root, f)
               and (root / f).is_file() and not (root / f).is_symlink()]
    for f in removed:
        (root / f).unlink()
    write_lock(root, new_files)

    print(f"devaccel {meta.get('version', '?')} -> {kit_version()} ({kit_ref()})")
    print("updated: " + (", ".join(changed) or "nothing"))
    if removed:
        print("removed: " + ", ".join(removed))
    if not hooks_wired(root / ".claude/settings.json"):
        print("! hooks are not wired in .claude/settings.json — run doctor.sh")
    drift = [r for r in seed_files() if (root / r).exists() and sha(root / r) != sha(SEED / r)]
    if drift:
        print("project-owned files differ from the current seed (expected; never overwritten). "
              "Check CHANGELOG for anything worth adopting: " + ", ".join(drift))
    return 0


def _safe_core_path(root: Path, rel: str) -> bool:
    """Lock entries come from the project repo: only ever delete inside .claude/."""
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or p.parts[:1] != (".claude",):
        return False
    try:
        (root / p).resolve().relative_to((root / ".claude").resolve())
    except ValueError:
        return False
    return True


def hooks_wired(settings: Path) -> bool:
    """guard on PreToolUse(Bash), stop_gate on Stop (SubagentStop is checked separately by doctor)."""
    try:
        hooks = json.loads(settings.read_text()).get("hooks", {})
    except (OSError, ValueError, AttributeError):
        return False

    def wired(event: str, script: str, matcher: str | None = None) -> bool:
        for entry in hooks.get(event, []) if isinstance(hooks.get(event), list) else []:
            if matcher and matcher not in str(entry.get("matcher", "")).split("|"):
                continue
            if any(script in str(h.get("command", "")) for h in entry.get("hooks", [])):
                return True
        return False
    return wired("PreToolUse", "hooks/guard.py", "Bash") and wired("Stop", "hooks/stop_gate.py")


def cfg_all(root: Path) -> dict:
    try:
        return json.loads((root / ".claude/project.json").read_text())
    except (OSError, ValueError):
        return {}


def _perms(root: Path) -> dict:
    try:
        return json.loads((root / ".claude/settings.json").read_text()).get("permissions", {})
    except (OSError, ValueError):
        return {}


def cmd_doctor(root: Path) -> int:
    problems, notes = [], []

    def ok(cond: bool, msg: str, hint: str = "") -> None:
        if not cond:
            problems.append(msg + (f"  → {hint}" if hint else ""))

    ok(sys.version_info >= (3, 10), f"python3 {sys.version.split()[0]} < 3.10")
    ok(shutil.which("git") is not None, "git not found")
    ok((root / ".git").exists(), "not a git repository root", "the Stop gate only works inside git")

    meta, locked = read_lock(root)
    ok(bool(locked), "devaccel.lock missing", "run install.sh")
    if locked:
        for f in [f for f in locked if not _safe_core_path(root, f)]:
            problems.append(f"lock entry outside .claude/: {f!r}")
            del locked[f]
        for f, h in locked.items():
            p = root / f
            ok(p.exists(), f"core file missing: {f}", "run update.sh")
            if p.exists():
                ok(sha(p) == h, f"core file edited by hand: {f}", "move changes to project.json")
        if meta.get("version") != kit_version():
            notes.append(f"kit has {kit_version()}, project has {meta.get('version')} → update.sh")

    try:
        sb = json.loads((root / ".claude/settings.json").read_text()).get("sandbox", {})
    except (OSError, ValueError):
        sb = {}
    ok(bool(sb.get("enabled")), "sandbox not enabled in .claude/settings.json",
       "secrets (.env) are protected only by the sandbox; see README 'サンドボックス'")
    if sb.get("enabled"):
        ok(sandbox_ready(), "sandbox enabled but bubblewrap/socat missing",
           "sudo apt-get install bubblewrap socat")
    try:
        perms = json.loads((root / ".claude/settings.json").read_text()).get("permissions", {})
    except (OSError, ValueError):
        perms = {}
    ok("Bash(git push*)" not in perms.get("ask", []), "settings ask rule Bash(git push*) blocks parallel PR units",
       "remove it; the guard enforces push policy (see CHANGELOG 0.4.0)")
    ok("api.github.com" in json.dumps(sb.get("network", {})), "sandbox network lacks api.github.com",
       "add github.com and api.github.com to sandbox.network.allowedDomains")
    try:
        trusted = json.loads((Path.home() / ".claude.json").read_text()).get("projects", {}) \
            .get(str(root), {}).get("hasTrustDialogAccepted")
    except (OSError, ValueError):
        trusted = None
    if not trusted:
        notes.append("workspace not trusted yet: run `claude` here once and accept the dialog "
                      "(permissions.allow is ignored until then; -p and /batch never ask)")
    origin = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                            capture_output=True, text=True).stdout.strip()
    if origin and shutil.which("gh"):
        if not origin.startswith("https://github.com/"):
            notes.append(f"origin is {origin}: PR flow expects https://github.com/... (SSH may fail in the sandbox)")
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        ok(auth.returncode == 0, "gh is not authenticated", "gh auth login")
        if auth.returncode == 0:
            st = protection_state(root)
            if st != "on":
                notes.append(f"branch protection on {base_branch(root)}: {st} — the guard is best-effort; "
                             "run ~/devaccel/protect.sh (public repo or Pro) so CI `check` is required server-side")
    ok(hooks_wired(root / ".claude/settings.json"), "hooks not wired in .claude/settings.json",
       "add the PreToolUse(Bash) guard and Stop gate entries (README)")
    try:
        wired = json.loads((root / ".claude/settings.json").read_text()).get("hooks", {})
    except (OSError, ValueError):
        wired = {}
    perms = _perms(root)
    need = ["Read(**/.env)", "Bash(gh *)", "Bash(git push --force*)"]
    lacking = [r for r in need if r not in perms.get("deny", [])]
    ok(not lacking, f"settings permissions.deny lacks {lacking}", "merge the deny list printed by install.sh")
    try:
        sb = json.loads((root / ".claude/settings.json").read_text()).get("sandbox", {})
    except (OSError, ValueError):
        sb = {}
    if "Bash(python3 .claude/hooks/devaccel_batch.py *)" not in perms.get("allow", []) or \
            "python3 .claude/hooks/devaccel_batch.py *" not in (sb.get("excludedCommands") or []):
        notes.append("fan-out is not automatic here (0.13): Claude can't start devaccel_batch.py by itself. To "
                     "allow it, add to .claude/settings.json: permissions.allow \"Bash(python3 .claude/hooks/"
                     "devaccel_batch.py *)\" and sandbox.excludedCommands [\"python3 .claude/hooks/devaccel_batch.py *\"]"
                     " (it then runs outside the sandbox without a prompt; units stay sandboxed)")
    if sb.get("enabled") and not sb.get("autoAllowBashIfSandboxed"):
        notes.append("sandbox.autoAllowBashIfSandboxed is off: /batch units will stop on permission prompts")
    try:  # parallel sizing for devaccel_batch (decided per machine at run time)
        sys.path.insert(0, str(CORE / ".claude" / "hooks"))
        import devaccel_batch as _b
        jobs, why = _b.plan_jobs(64, 0, cfg_all(root), _b.mem_available_mb(), os.cpu_count() or 1)
        notes.append(f"devaccel_batch would run up to {jobs} units at once here ({why})")
    except Exception:
        pass
    want_dw = render_settings([])["sandbox"]["filesystem"]["denyWrite"]
    if sb.get("enabled") and set(want_dw) - set(sb.get("filesystem", {}).get("denyWrite") or []):
        problems.append("sandbox.filesystem.denyWrite does not protect ./.claude/hooks etc.  → merge the "
                        "sandbox block printed by install.sh (CHANGELOG 0.10.0)")
    bad_denies = [r for r in ("Read(/uv.lock)", "Read(/.venv/**)", "Read(/.claude/worktrees/**)")
                  if r in json.dumps(_perms(root))]
    try:
        deny_read = json.loads((root / ".claude/settings.json").read_text()).get("sandbox", {}) \
            .get("filesystem", {}).get("denyRead", [])
    except (OSError, ValueError):
        deny_read = []
    slow = [p for p in deny_read if p.startswith("~/") and "**" in p]
    ok(not slow, f"sandbox denyRead {slow} scans all of $HOME on every Bash call (seconds each)",
       'replace with explicit paths (~/.ssh, ~/.aws, ~/.gnupg, ~/.netrc, ... see render_settings, CHANGELOG 0.8.2)')
    ok(not bad_denies, f"settings deny {bad_denies} breaks git/uv/worktrees under the sandbox",
       "remove them from .claude/settings.json (CHANGELOG 0.7.2)")
    dirty_core = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", ".claude/hooks",
                                 ".claude/skills", ".claude/devaccel.lock"], capture_output=True, text=True).stdout.strip()
    ok(not dirty_core, "devaccel core files are not committed: /batch worktrees start from HEAD, so their "
       "scripts would not match the lock and the PR step is refused", "commit .claude/ (e.g. after update.sh)")
    if "stop_gate.py" not in json.dumps(wired.get("SubagentStop", [])):
        problems.append("SubagentStop is not wired: the gate does not run inside /batch units. Add to hooks:\n"
                     + json.dumps({"SubagentStop": render_settings(["python"])["hooks"]["SubagentStop"]}))

    try:
        cfg = json.loads((root / ".claude/project.json").read_text())
        gate_cfg = cfg.get("gate", {})
        mode = gate_cfg.get("mode", "off")
        notes.append(f"gate: session={mode} unit={gate_cfg.get('unit_mode', 'enforce')}")
        if mode == "observe":
            notes.append("gate.mode=observe runs check.sh every turn without blocking: \"off\" is the default "
                         "since 0.8.0 (measured: no accuracy gain interactively; /batch units use unit_mode)")
    except (OSError, ValueError) as e:
        problems.append(f".claude/project.json unreadable: {e}")
        cfg = {}
    local = root / ".claude/settings.local.json"
    if local.exists() and "DEVACCEL_GATE_MODE" in local.read_text():
        notes.append("personal override DEVACCEL_GATE_MODE set in settings.local.json")

    check = root / "scripts/check.sh"
    ok(check.exists() and os.access(check, os.X_OK), "scripts/check.sh missing or not executable")
    if check.exists() and "no checks configured" in check.read_text():
        problems.append("scripts/check.sh has no checks: the gate passes everything  → run /devaccel-setup "
                        "(it proposes stages from package.json / Makefile / Cargo.toml / go.mod)")
    if "python" in cfg.get("presets", []):
        runner_uv = check.exists() and 'R="uv run"' in check.read_text()
        for tool in ("ruff", "pyright", "pytest"):
            found = (root / ".venv/bin" / tool).exists() or shutil.which(tool) is not None
            ok(found, f"{tool} not found", "uv add --dev " + tool if runner_uv else "pip install " + tool)

    gi = root / ".gitignore"
    ok(gi.exists() and ".claude/state/" in gi.read_text(), ".claude/state/ not gitignored")
    ok(gi.exists() and ".devaccel/" in gi.read_text(), ".devaccel/ not gitignored (PR notes scratch)",
       "add .devaccel/ to .gitignore")

    cm = root / "CLAUDE.md"
    if cm.exists():
        n = len(cm.read_text().splitlines())
        budget = cfg.get("budget", {}).get("claude_md_max_lines", 60)
        ok(n <= budget, f"CLAUDE.md is {n} lines (budget {budget})", "/devaccel-tune to prune")
    for f in ("CLAUDE.md", ".claude/skills/verify-app/SKILL.md"):
        p = root / f
        if p.exists() and re.search(r"<!-- devaccel:fill\b(?!ed)", p.read_text()):
            notes.append(f"{f} still has devaccel:fill placeholders → /devaccel-setup")

    rep = CORE / ".claude/hooks/devaccel_report.py"  # the kit's copy: never execute the project's files
    if rep.exists():
        r = subprocess.run([sys.executable, "-I", str(rep)], cwd=root, capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
        notes += [ln for ln in r.stdout.splitlines() if ln.startswith("gate runs")]

    for n in notes:
        print("· " + n)
    for p in problems:
        print("✗ " + p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


PROTECTION = {
    # solo-friendly: Claude uses the same account, so "require approval" would only lock you out.
    # What the server enforces: no direct/force push to the base, merges via PR with CI `check` green.
    # pinned to the GitHub Actions app (15368): a commit status posted with the user's token cannot satisfy it.
    # strict=False on purpose: devaccel_land re-verifies the combined tree before merging.
    "required_status_checks": {"strict": False, "checks": [{"context": "check", "app_id": 15368}]},
    "enforce_admins": True,
    "required_pull_request_reviews": {"required_approving_review_count": 0},
    "restrictions": None,
    "allow_force_pushes": False,
    "allow_deletions": False,
}


def origin_slug(root: Path) -> str:
    url = subprocess.run(["git", "-C", str(root), "config", "--get", "remote.origin.url"],
                         capture_output=True, text=True).stdout.strip()
    m = re.match(r"^(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else ""


def base_branch(root: Path) -> str:
    try:
        return json.loads((root / ".claude/project.json").read_text()).get("scale", {}).get("base_branch", "main")
    except (OSError, ValueError):
        return "main"


def protection_state(root: Path) -> str:
    """'on' / 'off' / 'unavailable' (private repo on a free plan) / 'unknown'."""
    slug = origin_slug(root)
    if not slug or not shutil.which("gh"):
        return "unknown"
    r = subprocess.run(["gh", "api", f"repos/{slug}/branches/{base_branch(root)}/protection"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return "on"
    err = r.stdout + r.stderr
    return "unavailable" if "Upgrade to GitHub Pro" in err else "off" if "not protected" in err.lower() else "unknown"


def cmd_protect(root: Path) -> int:
    """Human-run: protect the base branch on GitHub (the real boundary behind the guard)."""
    slug = origin_slug(root)
    if not slug:
        print("origin is not a github.com repository")
        return 2
    base = base_branch(root)
    print(f"{slug}:{base} に保護を設定: 直接 push・force push・削除の禁止(管理者も)、PR 経由のみ、CI `check` 必須")
    if input("続けるなら yes: ").strip() != "yes":
        return 1
    r = subprocess.run(["gh", "api", "-X", "PUT", f"repos/{slug}/branches/{base}/protection", "--input", "-"],
                       input=json.dumps(PROTECTION), capture_output=True, text=True)
    if r.returncode != 0:
        msg = (r.stdout + r.stderr).strip()
        print("failed: " + ("非公開リポジトリは無料プランでは保護できません(公開するか Pro に)" if "Upgrade" in msg else msg[:300]))
        return 1
    print("protected")
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "update", "doctor", "protect"):
        print(__doc__)
        return 2
    root = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path.cwd()
    return {"install": cmd_install, "update": cmd_update, "doctor": cmd_doctor,
            "protect": cmd_protect}[sys.argv[1]](root)


if __name__ == "__main__":
    sys.exit(main())
