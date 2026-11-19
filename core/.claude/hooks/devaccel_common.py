# devaccel core — DO NOT EDIT. Tune behavior in .claude/project.json instead.
# update.sh refuses to run if this file was modified by hand.
"""Shared helpers for devaccel hooks (python3 stdlib only, 3.10+)."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULTS: dict = {
    "presets": [],
    "gate": {
        # interactive sessions (a human is watching): off. /batch units (worktrees, unattended): enforce.
        # Measured: an interactive gate costs wall time with no accuracy gain (docs/design.md D14/D15).
        "mode": "off",  # off | observe | enforce
        "unit_mode": "enforce",
        "sandbox": True,  # run check.sh under bubblewrap (hooks are outside Claude Code's sandbox)
        "timeout_sec": 60,
        "fast_budget_sec": 15,
        "max_rounds": 3,
        "skip_branches": ["spike/*"],
        "ignore": ["docs/**", "*.md", ".claude/state/**", "**/__pycache__/**", "*.pyc"],
    },
    "scale": {
        "large_if_files_over": 3,
        "base_branch": "main",
        "risky_paths": [
            "**/auth/**",
            "**/migrations/**",
            "alembic/**",
            "**/*secret*",
            ".github/workflows/**",
        ],
    },
    "integrity": {"test_globs": ["tests/**", "**/test_*.py", "**/*_test.py"]},
    "budget": {"claude_md_max_lines": 60},
    "guard": {"deny_regex": [], "ask_regex": []},
    # Anthropic-style parallel work: /batch fans out, devaccel-pr turns each unit into an
    # evidence PR labeled evidence-ok / needs-human. auto_merge only for evidence-ok.
    # max_jobs 0 = decide per machine at run time (memory and CPUs); unit_mem_mb = per-unit estimate
    # (claude -p + its confined check; depends on the project's tools)
    "parallel": {"auto_merge": False, "max_jobs": 0, "unit_mem_mb": 300},
    # sessions: when Claude stops with uncommitted code changes, ask once to open the evidence PR (devaccel-pr)
    "pr": {"auto": True},
}

MODES = ("off", "observe", "enforce")


def _git_out(cwd: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null", "-C", str(cwd), *args],
                           capture_output=True, text=True, errors="replace", timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def trusted_root(data: dict | None = None) -> Path:
    """The main checkout: the trust anchor for the lock, project.json and check.sh. A worktree
    (a /batch unit) can edit its own copies of those, so they are never read from there."""
    # (no env-var override: a worktree's settings.json "env" could set it; the path itself is the anchor)
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        # a session started inside a devaccel worktree (<main>/.claude/worktrees/<x>) has project dir = the
        # worktree; the anchor is <main>, taken from the path itself (the worktree's .git file is
        # agent-writable, so git metadata could point anywhere)
        if "/.claude/worktrees/" in str(Path(env).resolve()) + "/":
            return Path(str(Path(env).resolve()).split("/.claude/worktrees/")[0])
        git_dir = _git_out(Path(env), "rev-parse", "--path-format=absolute", "--git-dir")
        common = _git_out(Path(env), "rev-parse", "--path-format=absolute", "--git-common-dir")
        if git_dir and common and git_dir != common:
            gd, cd, ev = Path(git_dir).resolve(), Path(common).resolve(), Path(env).resolve()
            if cd.name == ".git" and gd.parent == cd / "worktrees" and ev not in cd.parents and cd not in ev.parents:
                return cd.parent
        return Path(env)
    cwd = Path(data["cwd"]) if data and data.get("cwd") else Path.cwd()
    common = _git_out(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common).parent if common.endswith("/.git") else cwd


def worktree_link_ok(tree: Path, anchor: Path) -> bool:
    """A devaccel worktree's .git file must point at <anchor>/.git/worktrees/<x> (read as a plain file, no git:
    the file is agent-writable, and git would honour config in whatever git dir it names)."""
    try:
        line = (tree / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not line.startswith("gitdir: "):
        return False
    target = Path(line[len("gitdir: "):].strip())
    if not target.is_absolute():
        target = tree / target
    target = target.resolve()
    if target.parent != (anchor / ".git" / "worktrees").resolve() or target.name != tree.name:
        return False  # another unit's admin dir would make this tree's result count for that unit's branch
    try:  # and git's own back-link must name this tree
        back = (target / "gitdir").read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return Path(back).resolve() == (tree / ".git").resolve()


def project_root(data: dict | None = None) -> Path:
    """The tree being *checked* (not trusted). CLAUDE_PROJECT_DIR stays the main checkout even inside
    a worktree (/batch units), so prefer the hook's cwd when it is a worktree of the same repo."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    cwd = Path(data["cwd"]) if data and data.get("cwd") else None
    if cwd and cwd.is_dir():
        top = _git_out(cwd, "rev-parse", "--show-toplevel")
        if top and (not env or Path(_git_out(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir") or "x")
                    == Path(_git_out(Path(env), "rev-parse", "--path-format=absolute", "--git-common-dir") or "y")):
            return Path(top)
    if env:
        return Path(env)
    return cwd or Path.cwd()


def read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        return {}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(root: Path) -> dict:
    cfg = DEFAULTS
    path = root / ".claude" / "project.json"
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            cfg = _merge(DEFAULTS, loaded if isinstance(loaded, dict) else {})
        except ValueError as e:
            print(f"[devaccel] .claude/project.json is invalid JSON: {e}", file=sys.stderr)
    # Personal override (put in .claude/settings.local.json "env"). Shown by doctor.
    override = os.environ.get("DEVACCEL_GATE_MODE")
    if override in MODES:
        cfg = _merge(cfg, {"gate": {"mode": override}})  # personal: sessions only, never the unit gate
    return _sanitize(cfg)


def _sanitize(cfg: dict) -> dict:
    """Wrong types in project.json fall back to the defaults (a crashing gate would fail open)."""
    out: dict = {}
    for key, default in DEFAULTS.items():
        val = cfg.get(key, default)
        if isinstance(default, dict):
            val = val if isinstance(val, dict) else {}
            merged = {}
            for k, d in default.items():
                v = val.get(k, d)
                ok = (isinstance(v, bool) == isinstance(d, bool)) and isinstance(v, type(d)) if d is not None else True
                if isinstance(d, list):
                    ok = isinstance(v, list) and all(isinstance(x, str) for x in v)
                if isinstance(d, str) and k in ("mode", "unit_mode"):
                    ok = v in MODES
                merged[k] = v if ok else d
            merged.update({k: v for k, v in val.items() if k not in default})
            out[key] = merged
        else:
            out[key] = val if isinstance(val, type(default)) else default
    out.update({k: v for k, v in cfg.items() if k not in DEFAULTS})
    return out


def write_nofollow(path: Path, text: str | None) -> bool:
    """Write (or with None, remove) path without following a symlink at the file or its directory, checked by
    the kernel (O_NOFOLLOW): code running outside the sandbox must not be turned into a write elsewhere by a
    link the sandboxed session planted (e.g. under .devaccel/)."""
    try:
        path.parent.mkdir(exist_ok=True)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        if text is None:
            try:
                os.unlink(path.name, dir_fd=dfd)
            except FileNotFoundError:
                pass
            return True
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except OSError:
        return False
    finally:
        os.close(dfd)


def id_present(example_id: str, text: str) -> bool:
    """`E2-3` counts as present as E2-3, E2_3, e2-3 or a variant like E2-3a / E2-3_neg (all 9 example bounces in
    the measurements were such spellings, never missing tests); E2-30 is a different example."""
    m = re.fullmatch(r"E(\d+)-(\d+)", example_id)
    if not m:
        return example_id in text
    return re.search(rf"(?<![A-Za-z0-9])[Ee]{m[1]}[-_]{m[2]}(?![0-9])", text) is not None


def git(root: Path, *args: str, check: bool = False) -> str:
    try:
        r = subprocess.run(
            # literal UTF-8 paths (no "\\303..." quoting) and no rename pairing: triage must see every path
            # no fsmonitor/hooks: a worktree's .git file is agent-writable and could point at a git dir whose
            # config runs commands on `git status`
            ["git", "-c", "core.quotePath=false", "-c", "diff.renames=false", "-c", "core.fsmonitor=",
             "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
            capture_output=True,
            text=True, errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if check and r.returncode != 0:
        return ""
    return r.stdout if r.returncode == 0 else ""


def is_git_repo(root: Path) -> bool:
    return git(root, "rev-parse", "--is-inside-work-tree").strip() == "true"


def match_any(path: str, patterns: list[str]) -> bool:
    for p in patterns:
        if fnmatch.fnmatch(path, p) or fnmatch.fnmatch("/" + path, p):
            return True
    return False


CD_OLD = 'cd "$(dirname "$0")/.."'
CD_ENV = 'cd "${DEVACCEL_ROOT:-$(dirname "$0")/..}"'


def check_script_for(text: str) -> str | None:
    """check.sh text that cds into $DEVACCEL_ROOT, or None if its cd line is unrecognised
    (running it elsewhere would silently check the wrong directory)."""
    if "DEVACCEL_ROOT" in text:
        return text
    if CD_OLD in text:
        return text.replace(CD_OLD, CD_ENV)
    if re.search(r"^\s*cd\s", text, re.M):
        return None  # some other cd: it would leave the tree we were asked to check
    return text  # no cd at all: runs in the cwd we set


# ---------- confinement for code we did not write (tests in a unit's tree, PR code in land) ----------
HOME = Path.home()
# $HOME is replaced by an empty tmpfs; only these come back. Toolchains read-only, tool caches writable
# (the same caches Claude Code's sandbox lets the agent write), the tree writable except its .git.
HOME_RO = [".local/bin", ".local/lib", ".local/share/uv", ".cargo/bin", ".rustup/toolchains", ".pyenv/versions",
           ".pyenv/shims", ".nvm/versions", ".volta/bin", ".volta/tools", ".bun/bin", ".deno/bin", "go/bin"]
CACHE_RW = [".cache/uv", ".cache/pip", ".cache/pyright-python", ".cache/ruff"]
ENV_KEEP = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TZ", "UV_CACHE_DIR", "UV_PYTHON", "XDG_CACHE_HOME")


def confined(cmd: list[str], tree: Path, protect: list[Path] | None = None,
             mask_env_in: list[Path] | None = None) -> tuple[list[str], dict] | None:
    """Wrap cmd in bubblewrap. Hooks run outside Claude Code's sandbox, and check.sh runs tests the agent
    wrote, so it must not get the user's full rights: read-only filesystem, empty $HOME (allowlist above),
    only `tree` writable, its .git and `protect` read-only (a writable .git = git config/hooks executed by
    the next unsandboxed git call), .env files masked, minimal environment. None = bwrap unavailable."""
    import shutil
    bw = shutil.which("bwrap")
    if not bw:
        return None
    tree = tree.resolve()
    # --new-session: no TIOCSTI into the user's terminal; own pid/ipc/uts namespaces (network stays shared)
    args = [bw, "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--new-session", "--die-with-parent",
            "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", str(HOME)]
    for rel in HOME_RO:
        p = HOME / rel
        if p.exists():
            args += ["--ro-bind", str(p), str(p)]
    for rel in CACHE_RW:
        p = HOME / rel
        p.mkdir(parents=True, exist_ok=True)
        args += ["--bind", str(p), str(p)]
    args += ["--bind", str(tree), str(tree)]  # after the tmpfs mounts: trees under /tmp or $HOME stay visible
    for p in [tree / ".git", *(protect or [])]:
        if p.exists():
            args += ["--ro-bind", str(p), str(p)]
    for top in [tree, *(mask_env_in or [])]:  # every .env (nested too) in the tree and e.g. the main checkout
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = [d for d in dirnames if d not in (".git", ".venv", "node_modules", "__pycache__", "worktrees")]
            for f in filenames:
                if f == ".env" or f.startswith(".env."):
                    args += ["--ro-bind", "/dev/null", os.path.join(dirpath, f)]
    env = {k: v for k, v in os.environ.items() if k in ENV_KEEP}
    return args + ["--"] + cmd, env


def state_dir(root: Path) -> Path:
    d = root / ".claude" / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_event(root: Path, event: dict) -> None:
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    try:
        with open(state_dir(root) / "gate-log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def emit(obj: dict) -> None:
    if obj:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False))
