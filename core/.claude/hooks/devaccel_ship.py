# devaccel core — DO NOT EDIT.
"""Ship in one command: (integrate parallel units,) commit, push the work branch, open the evidence PR.

Replaces the 5-6 tool-turn devaccel-pr flow (write notes, add, write message, commit, push, PR) with one
guarded call. The evidence is still computed by devaccel_pr (base branch's check.sh on a HEAD snapshot,
triage); nothing here is self-reported.

usage: python3 .claude/hooks/devaccel_ship.py --file .devaccel/ship.md [--branch NAME] [--paths P ...]
                                              [--units B ...] [--dry-run]
  ship.md: line 1 = PR title / commit subject; the rest = what was run and observed (verify notes).
  --paths: new (untracked) files to add; tracked changes are always added (never `git add -A`).
  --units: local branches of parallel units to merge (--no-ff) onto the current work branch first;
           a unit that conflicts is skipped and reported. One PR for all of them.
Push policy (re-implemented here because the push no longer passes the guard as a shell command):
work branch only (never main/master/base/origin HEAD), remote origin only, no force.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.append(str(Path(__file__).resolve().parent))  # (planted modules are refused by guard _pr_script_intact)
from devaccel_common import git, load_config, trusted_root  # noqa: E402
from devaccel_pr import SECRET, open_pr, read_notes  # noqa: E402

IDENT = ["-c", "user.name=devaccel-ship", "-c", "user.email=devaccel-ship@localhost"]


def sh(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(root), *args], capture_output=True,
                          text=True, errors="replace", stdin=subprocess.DEVNULL)


def protected(root: Path, cfg: dict) -> set[str]:
    names = {"main", "master", cfg["scale"]["base_branch"]}
    head = git(root, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD").strip()
    if head:
        names.add(head.split("/", 1)[-1])
    return names


def integrate(root: Path, units: list[str], current: str) -> tuple[list[str], list[str]]:
    """Merge each unit branch. Only units that actually change the tree count (the count scales the
    L-size threshold, so duplicates, the current branch, or no-op branches must not inflate it)."""
    merged, skipped = [], []
    for b in dict.fromkeys(units):  # de-duplicated, order kept
        if b == current or not git(root, "rev-parse", "-q", "--verify", f"refs/heads/{b}").strip():
            skipped.append(f"{b} (not a separate local branch)")
            continue
        before = git(root, "rev-parse", "HEAD^{tree}").strip()
        m = sh(root, *IDENT, "merge", "--no-ff", "--no-edit", "-m", f"integrate {b}", b)
        if m.returncode != 0:
            sh(root, "merge", "--abort")
            skipped.append(f"{b} (conflict)")
        elif git(root, "rev-parse", "HEAD^{tree}").strip() == before:
            skipped.append(f"{b} (no changes)")
        else:
            merged.append(b)
    return merged, skipped


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--file", required=True, help="line 1: title; rest: verify notes")
    ap.add_argument("--paths", nargs="*", default=[])
    ap.add_argument("--units", nargs="*", default=[])
    ap.add_argument("--branch", default="", help="create this work branch from origin/<base> if on a protected branch")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or Path.cwd())
    cfg = load_config(trusted_root({"cwd": str(root)}))
    head = git(root, "symbolic-ref", "--short", "-q", "HEAD").strip()
    if a.branch and (not head or head in protected(root, cfg)):  # saves the parent its own git turns
        if a.branch in protected(root, cfg) or not re.fullmatch(r"[\w./-]+", a.branch) or ".." in a.branch:
            print(f"--branch {a.branch!r} is not a valid work branch name", file=sys.stderr)
            return 2
        base = cfg["scale"]["base_branch"]
        sh(root, "fetch", "-q", "origin", base)
        start = f"origin/{base}" if git(root, "rev-parse", "-q", "--verify", f"origin/{base}").strip() else base
        sw = sh(root, "switch", "-c", a.branch, start)
        if sw.returncode != 0:
            print("could not create the work branch: " + (sw.stderr.strip() or sw.stdout.strip())[:200], file=sys.stderr)
            return 2
        head = a.branch
    if not head or head in protected(root, cfg):
        print(f"refusing to ship from {head or 'detached HEAD'}: create a work branch first", file=sys.stderr)
        return 2
    text = read_notes(a.file, root)
    title, _, notes = text.partition("\n")
    title = "".join(ch for ch in title.strip() if ch.isprintable())[:120]
    if not title:
        print("--file: line 1 must be the PR title", file=sys.stderr)
        return 2

    merged, skipped = integrate(root, a.units, head) if a.units else ([], [])
    for p in a.paths:
        if Path(p).is_absolute() or ".." in Path(p).parts:
            print(f"--paths: {p} must be relative to the repo", file=sys.stderr)
            return 2
    if a.paths and sh(root, "add", "--", *a.paths).returncode != 0:
        print("git add failed for --paths", file=sys.stderr)
        return 2
    sh(root, "add", "-u")  # tracked changes only; new files must be named with --paths
    if sh(root, "diff", "--cached", "--quiet").returncode != 0:
        c = sh(root, "commit", "-q", "-m", title)
        if c.returncode != 0:
            print(c.stderr.strip() or c.stdout.strip(), file=sys.stderr)
            return 1
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        print("tracked changes remain uncommitted", file=sys.stderr)
        return 2
    if a.units:
        notes += f"\n\n統合した単位: {', '.join(merged) or 'なし'}" + (f" / 外した単位: {', '.join(skipped)}"
                                                                     if skipped else "")
    if SECRET.search(notes):
        print("notes look like they contain a credential; refused", file=sys.stderr)
        return 2

    if not a.dry_run:
        url = git(root, "config", "--get", "remote.origin.url").strip()
        if not url:
            print("no origin remote", file=sys.stderr)
            return 2
        p = subprocess.run(["git", "-C", str(root), "push", "origin", f"HEAD:refs/heads/{head}"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            print("push failed: " + (p.stderr.strip() or p.stdout.strip())[:300], file=sys.stderr)
            return 1
    return open_pr(root, title, notes, a.dry_run, units=max(1, len(merged)))


if __name__ == "__main__":
    sys.exit(main())
