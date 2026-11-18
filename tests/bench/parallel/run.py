"""Sequential vs parallel (/devaccel-batch) on the same 4 independent tasks (kit-side; ~$3-6 of quota).

A: one session implements the 4 tasks in order, then opens one evidence PR (devaccel-pr).
B: /devaccel-batch runs them as parallel units (one PR each), then devaccel_land.py verifies them together.
Measured: wall clock until "ready to merge", cost, held-out tests on the integrated result.

usage: python3 tests/bench/parallel/run.py --trial <trusted project with devaccel installed and a GitHub origin>
Leaves the PRs open (close them afterwards); never merges.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAIL = "確認は不要なので、そのまま最後まで進めて。"


def sh(cmd: list[str], cwd: Path, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def claude(prompt: str, cwd: Path, model: str) -> tuple[dict, float]:
    t0 = time.time()
    r = sh(["claude", "-p", prompt, "--output-format", "json", "--model", model, "--permission-mode", "acceptEdits"],
           cwd)
    wall = time.time() - t0
    try:
        return json.loads(r.stdout), wall
    except ValueError:
        return {"is_error": True, "result": (r.stdout + r.stderr)[-800:]}, wall


def open_prs(trial: Path) -> list[dict]:
    r = sh(["gh", "pr", "list", "--state", "open", "--json", "number,headRefName,labels,title"], trial)
    return json.loads(r.stdout or "[]")


def grade(trial: Path, branches: list[str]) -> dict:
    """Merge the given branches onto main in a scratch worktree and run the held-out tests there."""
    wt = Path(sh(["mktemp", "-d"], trial).stdout.strip()) / "g"
    sh(["git", "fetch", "-q", "origin"], trial)
    sh(["git", "worktree", "add", "-q", "--detach", str(wt), "origin/main"], trial)
    try:
        conflicts = []
        for b in branches:
            m = sh(["git", "-c", "user.name=g", "-c", "user.email=g@g", "merge", "--no-edit", f"origin/{b}"], wt)
            if m.returncode != 0:
                conflicts.append(b)
                sh(["git", "merge", "--abort"], wt)
        shutil.copy(HERE / "heldout" / "test_par_heldout.py", wt / "tests" / "test_par_heldout.py")
        sh(["uv", "sync", "-q"], wt)
        r = sh(["uv", "run", "pytest", "-q", "tests/test_par_heldout.py"], wt)
        last = (r.stdout.strip().splitlines() or [""])[-1]
        return {"heldout": last, "heldout_ok": r.returncode == 0, "merge_conflicts": conflicts}
    finally:
        sh(["git", "worktree", "remove", "--force", str(wt)], trial)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", type=Path, required=True)
    ap.add_argument("--model", default="claude-sonnet-5-5")
    a = ap.parse_args()
    trial = a.trial.expanduser().resolve()
    tasks = (HERE / "tasks.md").read_text(encoding="utf-8")
    out = HERE / "results.jsonl"
    sh(["git", "checkout", "-q", "main"], trial)
    sh(["git", "pull", "-q"], trial)
    before = {p["number"] for p in open_prs(trial)}

    # A: sequential in one session, one PR at the end
    sh(["git", "checkout", "-q", "-B", "seq/par-bench", "main"], trial)
    j, wall = claude(tasks + "\n上の 4 件を 1 つのセッションで順番に実装し(各件ごとにコミット)、"
                     "最後に devaccel-pr スキルで PR を 1 本作って。" + TAIL, trial, a.model)
    new = [p for p in open_prs(trial) if p["number"] not in before]
    rec_a = {"arm": "sequential", "wall_s": round(wall), "cost_usd": j.get("total_cost_usd"),
             "turns": j.get("num_turns"), "prs": [(p["number"], [x["name"] for x in p["labels"]]) for p in new],
             **grade(trial, [p["headRefName"] for p in new])}
    sh(["git", "checkout", "-q", "main"], trial)
    before |= {p["number"] for p in new}

    # B: parallel units via /devaccel-batch, then land (verify only) over all evidence-ok PRs
    j, wall = claude("/devaccel-batch " + tasks + "\n" + TAIL, trial, a.model)
    t0 = time.time()
    land = sh(["python3", ".claude/hooks/devaccel_land.py", "--dry-run"], trial)
    land_s = time.time() - t0
    new = [p for p in open_prs(trial) if p["number"] not in before]
    rec_b = {"arm": "parallel", "wall_s": round(wall + land_s), "batch_s": round(wall), "land_s": round(land_s),
             "cost_usd": j.get("total_cost_usd"), "turns": j.get("num_turns"),
             "prs": [(p["number"], [x["name"] for x in p["labels"]]) for p in new],
             "land": land.stdout.strip().splitlines()[-6:],
             **grade(trial, [p["headRefName"] for p in new])}
    sh(["git", "checkout", "-q", "main"], trial)
    with out.open("a", encoding="utf-8") as f:
        for rec in (rec_a, rec_b):
            rec["ts"] = dt.datetime.now().isoformat(timespec="seconds")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(json.dumps(rec, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
