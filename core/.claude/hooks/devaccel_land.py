# devaccel core — DO NOT EDIT.
"""Land parallel PRs: re-verify `evidence-ok` PRs *together* on the latest base, in order.

Each PR's evidence was made against the base it branched from. After a sibling merges,
that evidence is stale ("green alone, red together", or a textual conflict). This is a
local merge queue: it merges the PRs one by one into a scratch worktree of the latest
base and runs the base branch's check.sh full after each. A PR that conflicts or turns
the combined tree red is downgraded to `needs-human` with the reason. It never upgrades.

usage: python3 .claude/hooks/devaccel_land.py            # verify only (downgrades on failure)
       python3 .claude/hooks/devaccel_land.py --merge    # humans: also squash-merge what passed
       python3 .claude/hooks/devaccel_land.py --dry-run  # report only, change nothing on GitHub

The merged tree equals the verified tree: a squash of the PR onto the same base gives the
same content as the merge verified here, and --merge refuses if the base moved meanwhile.
To fix a downgraded PR: in its branch, `git merge origin/<base>` (no rebase, no force),
resolve, commit, `git push origin HEAD`, re-run devaccel_pr.py (it updates the PR).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from devaccel_common import git, load_config, match_any  # noqa: E402
from devaccel_pr import DOCS, github_repo, run, run_base_check, static_triage  # noqa: E402

IDENT = ["-c", "user.name=devaccel-land", "-c", "user.email=devaccel-land@localhost"]


def files_of(root: Path, base: str, oid: str) -> list[str]:
    return [f for f in git(root, "diff", "--name-only", f"{base}...{oid}").splitlines() if f]


def order(prs: list[dict]) -> list[dict]:
    """Code PRs first (oldest first), docs-only PRs last so they land on the final behaviour."""
    return sorted(prs, key=lambda p: (bool(p["files"]) and all(match_any(f, DOCS) for f in p["files"]), p["number"]))


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--merge", action="store_true", help="squash-merge each PR that passes (humans only)")
    ap.add_argument("--dry-run", action="store_true", help="do not change labels or merge")
    a = ap.parse_args()
    if a.merge and not a.dry_run:
        # merging is a human decision: require a person at a terminal, not just a flag
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("--merge needs an interactive terminal (humans only)", file=sys.stderr)
            return 2
        if input("evidence-ok の PR を検証し、通ったものを squash merge します。続けるなら merge と入力: ").strip() != "merge":
            return 1

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or Path.cwd())
    cfg = load_config(root)
    base = cfg["scale"]["base_branch"]
    repo = github_repo(root)
    if not repo:
        print("origin is not a github.com repository", file=sys.stderr)
        return 2
    run(["git", "fetch", "-q", "origin"], root)
    base_sha = git(root, "rev-parse", "-q", "--verify", f"origin/{base}").strip()
    if not base_sha:
        print(f"origin/{base} not found", file=sys.stderr)
        return 2
    r = run(["gh", "pr", "list", "-R", repo, "--state", "open", "--base", base, "--label", "evidence-ok",
             "--json", "number,headRefName,headRefOid,title,body,isCrossRepository", "--limit", "100"], root)
    if r.returncode != 0:
        print(r.stderr.strip(), file=sys.stderr)
        return 1
    prs = []
    for p in json.loads(r.stdout or "[]"):
        if p.get("isCrossRepository"):  # forks are never landed automatically
            print(f"#{p['number']} skipped: from a fork (review by hand)")
        else:
            prs.append(p)
    for p in prs:
        if not git(root, "rev-parse", "-q", "--verify", f"{p['headRefOid']}^{{commit}}").strip():
            run(["git", "fetch", "-q", "origin", f"pull/{p['number']}/head"], root)
        p["files"] = files_of(root, base_sha, p["headRefOid"])
    prs = order(prs)
    if not prs:
        print("no open evidence-ok PRs")
        return 0

    seen: dict[str, int] = {}
    for p in prs:  # overlap is where parallel units collide: show it up front
        for f in p["files"]:
            if f in seen:
                print(f"! overlap: {f} — #{seen[f]} and #{p['number']}")
            seen.setdefault(f, p["number"])

    def downgrade(p: dict, reason: str) -> None:
        print(f"#{p['number']} needs-human: {reason}")
        if a.dry_run:
            return
        run(["gh", "pr", "edit", str(p["number"]), "-R", repo,
             "--remove-label", "evidence-ok", "--add-label", "needs-human"], root)
        run(["gh", "pr", "comment", str(p["number"]), "-R", repo, "--body",
             f"**devaccel land: `needs-human`** — {reason}(base `{base_sha[:8]}` + 先行 PR 上で検証)\n\n"
             f"直し方: このブランチで `git merge origin/{base}` → 解消・コミット → `git push origin HEAD` "
             f"→ `devaccel_pr.py` を再実行(PR が更新される)。"], root)

    wt = Path(tempfile.mkdtemp(prefix="devaccel-land-")) / "wt"
    if run(["git", "worktree", "add", "-q", "--detach", str(wt), base_sha], root).returncode != 0:
        print("could not create a scratch worktree", file=sys.stderr)
        return 1
    passed, expected = [], base_sha
    try:
        for p in prs:
            n, oid = p["number"], p["headRefOid"]
            # the label is only as good as the commit it was computed for
            mark = re.search(r"devaccel:evidence base=\w* head=(\w+)", p.get("body") or "")
            if not mark or mark.group(1) != oid:
                downgrade(p, "証拠と現在の head が一致しない(証拠の後に push された)。devaccel_pr.py を再実行")
                continue
            fork_point = git(root, "merge-base", base_sha, oid).strip()  # the PR's own changes only
            static = static_triage(root, cfg, fork_point, oid)[1]
            if static:
                downgrade(p, "base に対する差分で再判定: " + " / ".join(static))
                continue
            m = run(["git", *IDENT, "merge", "--no-ff", "--no-edit", "-m", f"land #{n}", oid], wt)
            if m.returncode != 0:
                bad = [f for f in git(wt, "diff", "--name-only", "--diff-filter=U").splitlines() if f]
                run(["git", "merge", "--abort"], wt)
                downgrade(p, "base(と先行 PR)と衝突: " + (", ".join(bad[:5]) or m.stderr.strip()[:200]))
                continue
            ok, stages, tail, secs = run_base_check(root, cfg, base_sha, wt)
            if not ok:
                run(["git", "reset", "-q", "--hard", "HEAD~1"], wt)
                downgrade(p, "統合後に `check.sh full` が失敗(単独では緑): "
                          + ", ".join(s[3:] for s in stages if s.startswith("== failed")))
                print("\n".join("    " + ln for ln in tail.splitlines()[-10:]))
                continue
            print(f"#{n} ok on base + {len(passed)} earlier PR(s) ({secs}s): {p['title']}")
            passed.append(n)
            if a.merge and not a.dry_run:
                run(["git", "fetch", "-q", "origin", base], root)
                if git(root, "rev-parse", f"origin/{base}").strip() != expected:
                    print(f"stopped: origin/{base} moved during landing; re-run", file=sys.stderr)
                    return 1
                mr = run(["gh", "pr", "merge", str(n), "-R", repo, "--squash", "--match-head-commit", oid], root)
                if mr.returncode != 0:
                    print(f"stopped: merge of #{n} failed: {(mr.stderr or mr.stdout).strip()[:200]}", file=sys.stderr)
                    return 1
                run(["git", "fetch", "-q", "origin", base], root)
                expected = git(root, "rev-parse", f"origin/{base}").strip()
                if git(root, "rev-parse", f"{expected}^{{tree}}").strip() != git(wt, "rev-parse", "HEAD^{tree}").strip():
                    print(f"stopped: merged #{n} differs from the verified tree; check origin/{base}", file=sys.stderr)
                    return 1
                print(f"#{n} merged")
    finally:
        run(["git", "worktree", "remove", "--force", str(wt)], root)
        shutil.rmtree(wt.parent, ignore_errors=True)
    print(f"landed {len(passed)}/{len(prs)}" + ("" if a.merge else " verified (not merged; humans run --merge)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
