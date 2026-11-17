#!/usr/bin/env python3
"""devaccel kit: install / update / doctor (python3 stdlib only).

Run from the root of the target project:
    ~/devaccel/install.sh      # first time
    ~/devaccel/update.sh       # replace core files (refuses if hand-edited)
    ~/devaccel/doctor.sh       # health check
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
cd "$(dirname "$0")/.."
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
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --all-extras --dev
      - run: scripts/check.sh full
"""

WORKFLOW_PIP = """name: check
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff pyright pytest $( [ -f requirements.txt ] && echo "-r requirements.txt" )
      - run: scripts/check.sh full
"""

GITIGNORE_LINES = ["# devaccel", ".claude/state/", ".claude/settings.local.json", "__pycache__/"]


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


def render_settings(presets: list[str]) -> dict:
    # Only narrow, known-safe git forms: git accepts abbreviated long options
    # (--out= == --output=), so "git diff *" cannot be made safe by deny rules.
    # Exact forms only (no trailing wildcard); anything else asks.
    allow = ["Bash(scripts/check.sh fast)", "Bash(scripts/check.sh full)",
             "Bash(git status)", "Bash(git status --short)", "Bash(git diff)",
             "Bash(git diff --stat)", "Bash(git diff --name-only)", "Bash(git log --oneline)",
             "Bash(git show --stat)", "Bash(uv sync)"]
    for p in presets:
        for n in PRESETS[p]:
            allow += PIECES[n]["allow"]
    return {
        "permissions": {
            "allow": allow,
            "ask": [
                "Edit(./scripts/check.sh)",
                "Edit(./.claude/hooks/**)",
                "Edit(./.claude/settings.json)",
                "Edit(./.claude/project.json)",
                "Edit(./.github/workflows/**)",
                "Bash(git push*)",
            ],
            "deny": ["Read(./.env)", "Read(./.env.*)", "Edit(./.env)", "Edit(./.env.*)",
                     "Bash(git * --out*)", "Bash(git * --ext*)"],
        },
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": HOOK_CMDS["guard"], "timeout": 10}]}],
            "Stop": [{"hooks": [
                {"type": "command", "command": HOOK_CMDS["stop"], "timeout": 120}]}],
        },
    }


def write_new(root: Path, rel: str, content: str | None = None, src: Path | None = None) -> bool:
    dst = root / rel
    if dst.exists():
        return False
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

    for rel in core_files():
        dst = root / rel
        if dst.exists() and sha(dst) != sha(CORE / rel):
            print(f"error: {rel} already exists and differs. Move it away and retry.")
            return 1
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
        ".github/workflows/check.yml": WORKFLOW_UV if runner else WORKFLOW_PIP,
    }
    for rel, content in gen.items():
        (created if write_new(root, rel, content) else kept).append(rel)
    os.chmod(root / "scripts/check.sh", 0o755)

    settings = root / ".claude/settings.json"
    if write_new(root, ".claude/settings.json",
                 json.dumps(render_settings(presets), indent=2, ensure_ascii=False) + "\n"):
        created.append(".claude/settings.json")
    else:
        kept.append(".claude/settings.json")
        if not hooks_wired(settings):
            print("\n! .claude/settings.json already exists; devaccel does not merge it.")
            print("  Add these entries yourself (see README 'settings.json'):")
            print(json.dumps({"hooks": render_settings(presets)["hooks"]}, indent=2))

    gi = root / ".gitignore"
    text = gi.read_text() if gi.exists() else ""
    missing = [ln for ln in GITIGNORE_LINES if ln not in text.splitlines()]
    if missing:
        gi.write_text(text + ("" if text.endswith("\n") or not text else "\n") + "\n".join(missing) + "\n")

    write_lock(root, core_files())
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
    try:
        text = settings.read_text()
    except OSError:
        return False
    return "hooks/guard.py" in text and "hooks/stop_gate.py" in text


def cmd_doctor(root: Path) -> int:
    problems, notes = [], []

    def ok(cond: bool, msg: str, hint: str = "") -> None:
        if not cond:
            problems.append(msg + (f"  → {hint}" if hint else ""))

    ok(sys.version_info >= (3, 8), f"python3 {sys.version.split()[0]} < 3.8")
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

    ok(hooks_wired(root / ".claude/settings.json"), "hooks not wired in .claude/settings.json",
       "add the PreToolUse(Bash) guard and Stop gate entries (README)")

    try:
        cfg = json.loads((root / ".claude/project.json").read_text())
        mode = cfg.get("gate", {}).get("mode", "observe")
        notes.append(f"gate.mode={mode}")
    except (OSError, ValueError) as e:
        problems.append(f".claude/project.json unreadable: {e}")
        cfg = {}
    local = root / ".claude/settings.local.json"
    if local.exists() and "DEVACCEL_GATE_MODE" in local.read_text():
        notes.append("personal override DEVACCEL_GATE_MODE set in settings.local.json")

    check = root / "scripts/check.sh"
    ok(check.exists() and os.access(check, os.X_OK), "scripts/check.sh missing or not executable")
    if "python" in cfg.get("presets", []):
        runner_uv = check.exists() and 'R="uv run"' in check.read_text()
        for tool in ("ruff", "pyright", "pytest"):
            found = (root / ".venv/bin" / tool).exists() or shutil.which(tool) is not None
            ok(found, f"{tool} not found", "uv add --dev " + tool if runner_uv else "pip install " + tool)

    gi = root / ".gitignore"
    ok(gi.exists() and ".claude/state/" in gi.read_text(), ".claude/state/ not gitignored")

    cm = root / "CLAUDE.md"
    if cm.exists():
        n = len(cm.read_text().splitlines())
        budget = cfg.get("budget", {}).get("claude_md_max_lines", 60)
        ok(n <= budget, f"CLAUDE.md is {n} lines (budget {budget})", "/devaccel-tune to prune")
    for f in ("CLAUDE.md", ".claude/skills/verify-app/SKILL.md"):
        p = root / f
        if p.exists() and re.search(r"<!-- devaccel:fill\b(?!ed)", p.read_text()):
            notes.append(f"{f} still has devaccel:fill placeholders → /devaccel-setup")

    rep = root / ".claude/hooks/devaccel_report.py"
    if rep.exists():
        r = subprocess.run([sys.executable, str(rep)], cwd=root, capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
        notes += [ln for ln in r.stdout.splitlines() if ln.startswith(("gate runs", "promotion"))]

    for n in notes:
        print("· " + n)
    for p in problems:
        print("✗ " + p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "update", "doctor"):
        print(__doc__)
        return 2
    root = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path.cwd()
    return {"install": cmd_install, "update": cmd_update, "doctor": cmd_doctor}[sys.argv[1]](root)


if __name__ == "__main__":
    sys.exit(main())
