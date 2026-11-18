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
import time
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.append(str(Path(__file__).resolve().parent))  # (planted modules are refused by guard _pr_script_intact)
from devaccel_common import git, load_config, trusted_root  # noqa: E402
from devaccel_common import write_nofollow  # noqa: E402
from devaccel_pr import SECRET, open_pr, read_notes, stamp  # noqa: E402

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
    ap.add_argument("--dry-run", action="store_true", help="change nothing; show the plan and the evidence for HEAD")
    ap.add_argument("--no-push", action="store_true",
                    help="create the branch, integrate and commit locally, show the evidence; no push, no PR")
    a = ap.parse_args()

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or Path.cwd())
    cfg = load_config(trusted_root({"cwd": str(root)}))
    head = git(root, "symbolic-ref", "--short", "-q", "HEAD").strip()
    text = read_notes(a.file, root)
    title, _, notes = text.partition("\n")
    title = "".join(ch for ch in title.strip() if ch.isprintable())[:120]
    if not title:
        print("--file: line 1 must be the PR title", file=sys.stderr)
        return 2
    for p in a.paths:
        if Path(p).is_absolute() or ".." in Path(p).parts or not Path(p).parts or (root / p).resolve() == root.resolve():
            print(f"--paths: {p!r} must name files or directories inside the repo (not the repo itself)",
                  file=sys.stderr)
            return 2
    if a.dry_run:  # nothing is created, merged, committed or pushed
        print(f"dry run: would ship from {head or 'detached HEAD'}"
              + (f" via new branch {a.branch}" if a.branch and (not head or head in protected(root, cfg)) else "")
              + (f", integrating {len(a.units)} unit(s)" if a.units else "")
              + (f", adding {' '.join(a.paths)}" if a.paths else ""))
        if git(root, "status", "--porcelain", "--untracked-files=no").strip() or a.units:
            print("(evidence is computed after the commit/integration; use --no-push to see it locally)")
            return 0
        return open_pr(root, title, notes, True)
    if a.branch and (not head or head in protected(root, cfg)):  # saves the parent its own git turns
        if a.branch in protected(root, cfg) or not re.fullmatch(r"[\w./-]+", a.branch) or ".." in a.branch:
            print(f"--branch {a.branch!r} is not a valid work branch name", file=sys.stderr)
            return 2
        base = cfg["scale"]["base_branch"]
        sh(root, "fetch", "-q", "origin", base)
        start = f"origin/{base}" if git(root, "rev-parse", "-q", "--verify", f"origin/{base}").strip() else base
        sw = sh(root, "switch", "--no-track", "-c", a.branch, start)  # no upstream: .git/config is not writable in the sandbox
        if sw.returncode != 0:
            print("could not create the work branch: " + (sw.stderr.strip() or sw.stdout.strip())[:200], file=sys.stderr)
            return 2
        head = a.branch
    if not head or head in protected(root, cfg):
        print(f"refusing to ship from {head or 'detached HEAD'}: create a work branch first", file=sys.stderr)
        return 2

    t = time.time()
    merged, skipped = integrate(root, a.units, head) if a.units else ([], [])
    t = stamp("integrate units", t)
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

    t = stamp("add + commit", t)
    if a.no_push:
        return open_pr(root, title, notes, True, units=max(1, len(merged)))
    if not git(root, "config", "--get", "remote.origin.url").strip():
        print("no origin remote", file=sys.stderr)
        return 2
    # push runs while the evidence is computed (they don't depend on each other); the PR waits for it
    push = subprocess.Popen(["git", "-C", str(root), "push", "origin", f"HEAD:refs/heads/{head}"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)

    def wait_push() -> int:
        out, err = push.communicate()
        if push.returncode != 0:
            print("push failed: " + (err.strip() or out.strip())[:300], file=sys.stderr)
            return 1
        return 0
    rc = open_pr(root, title, notes, False, units=max(1, len(merged)), before_publish=wait_push)
    if rc == 0:  # used: a later ship must never reuse these notes (a failed Write would ship stale ones)
        nf = Path(a.file) if Path(a.file).is_absolute() else Path.cwd() / a.file
        if root.resolve() in nf.resolve().parents:
            write_nofollow(nf, None)
    return rc


if __name__ == "__main__":
    sys.exit(main())
