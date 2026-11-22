# devaccel core — DO NOT EDIT.
"""Ship in one command: (integrate parallel units,) commit, push the work branch, open the evidence PR.

Replaces the 5-6 tool-turn devaccel-pr flow (write notes, add, write message, commit, push, PR) with one
guarded call. The evidence is still computed by devaccel_pr (base branch's check.sh on a HEAD snapshot,
triage); nothing here is self-reported.

usage: python3 .claude/hooks/devaccel_ship.py --file .devaccel/ship.md [--branch NAME] [--paths P ...]
                                              [--units B ...] [--dry-run] [--check]
  ship.md: line 1 = PR title / commit subject; the rest = what was run and observed (verify notes).
  --paths: new (untracked) files to add; tracked changes are always added (never `git add -A`).
  --check: run `scripts/check.sh fast` (may auto-format) on the working tree first, exactly like the Stop gate;
           on failure nothing is committed or pushed and only the failed stage's tail is printed. Saves the
           agent its own check turn; the PR evidence (check.sh full on a pristine export) is unchanged.
  --units: local branches of parallel units to merge (--no-ff) onto the current work branch first;
           a unit that conflicts is skipped and reported. One PR for all of them.
Push policy (re-implemented here because the push no longer passes the guard as a shell command):
work branch only (never main/master/base/origin HEAD), remote origin only, no force.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.append(str(Path(__file__).resolve().parent))  # (planted modules are refused by guard _pr_script_intact)
from devaccel_common import git, load_config, trusted_root  # noqa: E402
from devaccel_common import write_nofollow  # noqa: E402
from devaccel_pr import SECRET, in_agent_sandbox, need_confinement, open_draft, open_pr, read_notes, stamp  # noqa: E402,E501

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
    ap.add_argument("--check", action="store_true",
                    help="run check.sh fast on the working tree first; stop (no commit/push) if it fails")
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
    fetched = False  # the base was fetched just now (the evidence then skips its own fetch)
    if a.branch and (not head or head in protected(root, cfg)):  # saves the parent its own git turns
        if a.branch in protected(root, cfg) or not re.fullmatch(r"\w[\w./-]*", a.branch) or ".." in a.branch:
            print(f"--branch {a.branch!r} is not a valid work branch name", file=sys.stderr)
            return 2
        base = cfg["scale"]["base_branch"]
        fetched = sh(root, "fetch", "-q", "origin", base).returncode == 0
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
    from stop_gate import failed_section, run_check

    def fast_check() -> tuple[str, str, float]:
        res, _rc, out, secs = run_check(root, int(cfg["gate"].get("timeout_sec", 60)), trusted_root({"cwd": str(root)}),
                                        sandbox=need_confinement(cfg))
        return res, out, secs

    def fast_failed(res: str, out: str, secs: float, kept: str = "") -> int:
        stage, tail = failed_section(out) if res == "fail" else (res, out[-1500:])
        print(f"check.sh fast: {res} ({stage}, {secs:.0f}s) — "
              f"{kept or 'your changes are not committed and nothing was pushed'}"
              f"{' (the units are merged)' if merged else ''}; fix and re-run\n{tail}",
              file=sys.stderr)
        return 1
    if a.check and a.no_push:  # local only: nothing to overlap with
        res, out, secs = fast_check()
        t = stamp("check.sh fast", t)
        if res != "pass":
            return fast_failed(res, out, secs)
    pre = git(root, "rev-parse", "-q", "--verify", "HEAD").strip()
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
    if a.check and not a.units and async_ready(root, cfg) and re.fullmatch(r"\w[\w./-]*", head) and ".." not in head:
        rc = ship_async(root, a, title, notes, head, pre, fast_check, fast_failed, t)
        if rc is not None:
            if rc == 0:
                cleanup_notes(root, a)
            return rc
    # check.sh fast (working tree) and the evidence (check.sh full on a snapshot of HEAD) run side by side;
    # the push waits for fast to pass, so a failure still leaves nothing committed and nothing pushed
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(1)
    fast = pool.submit(fast_check) if a.check else None
    redo: list[bool] = []

    def wait_push() -> int:
        if fast is not None:
            res, out, secs = fast.result()
            stamp("waited for check.sh fast", t)
            if res != "pass":
                if git(root, "rev-parse", "HEAD").strip() != pre:
                    sh(root, "reset", "-q", pre) if pre else sh(root, "update-ref", "-d", "HEAD")
                return fast_failed(res, out, secs)
            if git(root, "status", "--porcelain", "--untracked-files=no").strip():  # fast auto-fixed formatting
                redo.append(True)
                return 3
        p = subprocess.run(["git", "-C", str(root), "push", "origin", f"HEAD:refs/heads/{head}"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            print("push failed: " + (p.stderr.strip() or p.stdout.strip())[:300], file=sys.stderr)
            return 1
        return 0
    rc = open_pr(root, title, notes, False, units=max(1, len(merged)), before_publish=wait_push, fetched=fetched)
    pool.shutdown()
    if redo:  # the evidence judged the commit before the fix: commit the fix, then judge that commit
        sh(root, "add", "-u")
        if pre and git(root, "rev-parse", "HEAD").strip() != pre:
            sh(root, "commit", "-q", "--amend", "--no-edit")
        else:
            sh(root, "commit", "-q", "-m", title)
        fast, redo = None, []
        rc = open_pr(root, title, notes, False, units=max(1, len(merged)), before_publish=wait_push, fetched=fetched)
    if rc == 0:  # used: a later ship must never reuse these notes (a failed Write would ship stale ones)
        cleanup_notes(root, a)
        for b in dict.fromkeys(x for x in a.units if x.startswith("unit/")):  # shipped parts: no longer needed
            if sh(root, "merge-base", "--is-ancestor", f"refs/heads/{b}", "HEAD").returncode == 0:
                sh(root, "branch", "-q", "-D", b)
    return rc


def early_fix(root: Path, title: str, head: str, pre: str, sha: str) -> tuple[str, bool]:
    """check.sh fast reformats first and its later stages only read, so edits seen while it still runs are the
    formatter's: fold them into the commit and push that before the draft names a sha (the end of ship checks
    the tree again, so anything later still gets the slow path)."""
    sh(root, "add", "-u")
    sh(root, "commit", "-q", "--amend", "--no-edit") if pre and sha != pre else sh(root, "commit", "-q", "-m", title)
    new = git(root, "rev-parse", "HEAD").strip()
    q = subprocess.run(["git", "-C", str(root), "push", "-q", f"--force-with-lease=refs/heads/{head}:{sha}", "origin",
                        f"HEAD:refs/heads/{head}"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return new, q.returncode == 0


def cleanup_notes(root: Path, a) -> None:
    nf = Path(a.file) if Path(a.file).is_absolute() else Path.cwd() / a.file
    if root.resolve() in nf.resolve().parents:
        write_nofollow(nf, None)


def async_ready(root: Path, cfg: dict) -> bool:
    """The evidence can finish after ship returns only when Claude Code will run the finalize hook (it starts the
    detached step outside the sandbox). Elsewhere (a terminal, no sandbox, an older settings.json) ship stays
    synchronous."""
    if not cfg.get("pr", {}).get("async_evidence", True) or not in_agent_sandbox():
        return False
    try:
        hooks = json.loads((trusted_root({"cwd": str(root)}) / ".claude/settings.json").read_text()).get("hooks", {})
    except (OSError, ValueError):
        return False
    return "devaccel_finalize.py" in json.dumps(hooks.get("PostToolUse", []))


def ship_async(root: Path, a, title: str, notes: str, head: str, pre: str, fast_check, fast_failed,
               t: float) -> int | None:
    """check.sh fast beside push + draft PR -> request for the finalize hook -> return. The hook (outside the
    sandbox) starts devaccel_pr.py --finalize, which judges the pushed commit with the base check.sh, fills in
    the body and label and readies the PR. None: no draft, so the caller takes the synchronous path.

    The push and the draft (~6 s on GitHub) overlap check.sh fast. That is safe because nothing is judged yet:
    a draft cannot be merged and only a passing fast writes the finalize request. If fast fails, the branch on
    GitHub is put back (or removed, if this push created it) and the local commit is undone, as before."""
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(1)
    fast = pool.submit(fast_check)
    sha = git(root, "rev-parse", "HEAD").strip()
    p = subprocess.run(["git", "-C", str(root), "push", "--porcelain", "origin", f"HEAD:refs/heads/{head}"],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    pushed = p.returncode == 0
    old = None  # what the branch on GitHub was before this push ("" = this push created it; None = unknown)
    m = re.search(r"^([ +*])\t[^\t]*\t(\S+)", p.stdout, re.M) if pushed else None  # flag, from:to, summary
    if m and m.group(2).startswith("[new"):
        old = ""
    elif m and ".." in m.group(2):  # "abc1234..def5678" (abbreviated): resolve locally, or leave it alone
        old = git(root, "rev-parse", "-q", "--verify", m.group(2).split("..")[0] + "^{commit}").strip() or None
    t = stamp("push", t)
    failed_early = fast.done() and fast.result()[0] != "pass"  # no draft for a commit that is going back
    if pushed and not failed_early and git(root, "status", "--porcelain", "--untracked-files=no").strip():
        new, ok = early_fix(root, title, head, pre, sha)  # fast's formatter already ran: amend before the draft
        if not ok:  # GitHub still has the first push: a PR on this branch must not stay ready with it
            open_draft(root, title, head, sha)
            fast.result()
            pool.shutdown()
            print("push failed after the formatter's fix (the PR is a draft); re-run ship", file=sys.stderr)
            return 1
        sha = new
    url = open_draft(root, title, head, sha) if pushed and not failed_early else ""
    t = stamp("draft PR", t)
    res, out, secs = fast.result()
    pool.shutdown()
    t = stamp("waited for check.sh fast", t)

    def put_back() -> bool:
        if old is None:
            return False
        lease = f"--force-with-lease=refs/heads/{head}:{sha}"
        spec = f"{old}:refs/heads/{head}" if old else f":refs/heads/{head}"
        return subprocess.run(["git", "-C", str(root), "push", "-q", lease, "origin", spec], capture_output=True,
                              stdin=subprocess.DEVNULL).returncode == 0
    if res != "pass":
        if pushed and put_back():
            print("(the branch on GitHub was put back; a PR it already had stays a draft until the next ship)",
                  file=sys.stderr)
        elif pushed:
            if not url:  # this push may have moved a PR that was ready: it must not stay ready with it
                open_draft(root, title, head, sha)
            # keep the local commit too, so the next push is a fast-forward
            return fast_failed(res, out, secs, kept=f"this commit stays (locally and on GitHub's {head}, as a draft "
                               "that cannot be merged); the next ship adds the fix on top")
        if git(root, "rev-parse", "HEAD").strip() != pre:
            sh(root, "reset", "-q", pre) if pre else sh(root, "update-ref", "-d", "HEAD")
        return fast_failed(res, out, secs)
    if not pushed:
        print("push failed: " + (p.stderr.strip() or p.stdout.strip())[:300], file=sys.stderr)
        return 1
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():  # fast auto-fixed formatting
        sh(root, "add", "-u")
        sh(root, "commit", "-q", "--amend", "--no-edit") if pre and sha != pre \
            else sh(root, "commit", "-q", "-m", title)
        new = git(root, "rev-parse", "HEAD").strip()
        q = subprocess.run(["git", "-C", str(root), "push", f"--force-with-lease=refs/heads/{head}:{sha}", "origin",
                            f"HEAD:refs/heads/{head}"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if q.returncode != 0:
            print("push failed: " + (q.stderr.strip() or q.stdout.strip())[:300] + " (the PR stays a draft; re-run"
                  " ship)", file=sys.stderr)
            return 1
        sha = new
        url = open_draft(root, title, head, sha) if url else ""
        t = stamp("amend + push + draft", t)
    if not url:
        return None
    write_nofollow(root / ".devaccel" / "finalize.json",
                   json.dumps({"sha": sha, "branch": head, "title": title, "notes": notes}, ensure_ascii=False))
    print(f"{url}  [証拠を作成中: base の check.sh full がこの commit で終わるとラベルが付き、下書きが解除される]")
    return 0

if __name__ == "__main__":
    sys.exit(main())
