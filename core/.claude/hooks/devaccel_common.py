# devaccel core — DO NOT EDIT. Tune behavior in .claude/project.json instead.
# update.sh refuses to run if this file was modified by hand.
"""Shared helpers for devaccel hooks (python3 stdlib only, 3.8+)."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULTS: dict = {
    "presets": [],
    "gate": {
        "mode": "observe",  # off | observe | enforce
        "timeout_sec": 60,
        "fast_budget_sec": 15,
        "max_rounds": 3,
        "skip_branches": ["spike/*"],
        "ignore": ["docs/**", "*.md", ".claude/state/**", "**/__pycache__/**", "*.pyc"],
        "promote": {"min_runs": 10, "max_false_positives": 0},
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
}

MODES = ("off", "observe", "enforce")


def project_root(data: dict | None = None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    if data and data.get("cwd"):
        return Path(data["cwd"])
    return Path.cwd()


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
            cfg = _merge(DEFAULTS, json.loads(path.read_text(encoding="utf-8")))
        except ValueError as e:
            print(f"[devaccel] .claude/project.json is invalid JSON: {e}", file=sys.stderr)
    # Personal override (put in .claude/settings.local.json "env"). Shown by doctor.
    override = os.environ.get("DEVACCEL_GATE_MODE")
    if override in MODES:
        cfg = _merge(cfg, {"gate": {"mode": override}})
    return cfg


def git(root: Path, *args: str, check: bool = False) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
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
