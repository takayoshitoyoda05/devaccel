"""Sequential vs parallel on the same independent tasks (kit-side; costs quota).

Arms (choose with --arms):
  seq_old   one session, implements in order, then the old 5-6 turn PR flow (notes, add, commit, push, PR script)
  seq_ship  one session, implements in order, then devaccel-pr (one-command devaccel_ship.py)
  par       /devaccel-batch as a user would call it (the skill may choose sequential for small work)
  par_force /devaccel-batch, told to always run devaccel-unit (haiku) units in parallel, then ship --units
  <arm>_haiku  the same arm with the session itself on haiku (e.g. seq_ship_haiku, par_force_haiku)
Measured per arm: wall clock until the PR exists, cost (+ per-model breakdown), turns, PR labels,
held-out tests on the integrated result. Each arm's PRs/branches/worktrees are cleaned up afterwards.

usage: python3 tests/bench/parallel/run.py --trial <trusted project, devaccel installed, GitHub origin>
           [--tasks tasks.md] [--heldout heldout/test_par_heldout.py] [--arms seq_ship,par] [--reps 1]
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
OLD_PR = ("最後に次の手順で PR を 1 本作って: 確認メモを `.devaccel/pr-notes.md` に Write → `git add <変更したパス>` → "
          "コミットメッセージを `.devaccel/commit-msg.txt` に Write → `git commit -F .devaccel/commit-msg.txt` → "
          "`git push origin HEAD` → `python3 .claude/hooks/devaccel_pr.py --title \"<要約>\" --verify-notes "
          ".devaccel/pr-notes.md`。各コマンドは単独で実行する。")


def sh(cmd: list[str], cwd: Path, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


CAP: int | None = None  # --cap: CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS for this run (command-line settings win)


def claude(prompt: str, cwd: Path, model: str) -> tuple[dict, float]:
    t0 = time.time()
    extra = ["--settings", json.dumps({"env": {"CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": str(CAP)}})] if CAP else []
    r = sh(["claude", "-p", prompt, "--output-format", "json", "--model", model, "--permission-mode", "acceptEdits",
            *extra], cwd)
    wall = time.time() - t0
    try:
        return json.loads(r.stdout), wall
    except ValueError:
        return {"is_error": True, "result": (r.stdout + r.stderr)[-800:]}, wall


def open_prs(trial: Path) -> list[dict]:
    r = sh(["gh", "pr", "list", "--state", "open", "--json", "number,headRefName,labels,title"], trial)
    return json.loads(r.stdout or "[]")


def grade(trial: Path, branches: list[str], heldout: Path, patch: Path | None = None) -> dict:
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
        if patch is not None:  # the integrated diff, for the blind quality review
            patch.write_text(sh(["git", "diff", "origin/main", "HEAD"], wt).stdout, encoding="utf-8")
        shutil.copy(heldout, wt / "tests" / heldout.name)
        sh(["uv", "sync", "-q"], wt)
        r = sh(["uv", "run", "pytest", "-q", f"tests/{heldout.name}"], wt)
        last = (r.stdout.strip().splitlines() or [""])[-1]
        return {"heldout": last, "heldout_ok": r.returncode == 0, "merge_conflicts": conflicts}
    finally:
        sh(["git", "worktree", "remove", "--force", str(wt)], trial)


def cleanup(trial: Path, prs: list[dict]) -> None:
    for p in prs:
        sh(["gh", "pr", "close", str(p["number"]), "-c", "bench run; closed automatically"], trial)
        sh(["git", "push", "-q", "origin", "--delete", p["headRefName"]], trial)
    for line in sh(["git", "worktree", "list", "--porcelain"], trial).stdout.splitlines():
        if line.startswith("worktree ") and "/.claude/worktrees/" in line:
            sh(["git", "worktree", "remove", "--force", line.split(" ", 1)[1]], trial)
    sh(["git", "checkout", "-q", "main"], trial)
    for b in sh(["git", "branch", "--format=%(refname:short)"], trial).stdout.split():
        if b != "main":
            sh(["git", "branch", "-D", b], trial)
    for b in sh(["git", "ls-remote", "--heads", "origin"], trial).stdout.split():
        if b.startswith("refs/heads/") and b != "refs/heads/main" and any(k in b for k in ("worktree-agent", "bench",
                                                                                               "unit/", "batch/")):
            sh(["git", "push", "-q", "origin", "--delete", b[len("refs/heads/"):]], trial)
    sh(["git", "fetch", "-q", "--prune"], trial)


def usage(j: dict) -> dict:
    return {m: {"cost": round(u.get("costUSD", 0), 3), "out": u.get("outputTokens"),
                "cache_read": u.get("cacheReadInputTokens"), "cache_write": u.get("cacheCreationInputTokens")}
            for m, u in (j.get("modelUsage") or {}).items()}


TASKS_PATH: Path | None = None


def run_fanout(trial: Path, extra: list[str] | None = None) -> tuple[dict, float]:
    """devaccel_batch.py: deterministic fan-out, no LLM parent (run as a human would, outside Claude Code)."""
    import os
    import re
    import sys
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["DEVACCEL_TIMING"] = "1"
    t0 = time.time()
    r = subprocess.run([sys.executable, ".claude/hooks/devaccel_batch.py", str(TASKS_PATH), "--branch",
                        "batch/fanout-bench", *(extra or [])], cwd=trial, capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=3600)
    wall = time.time() - t0
    m = re.search(r"units: (\d+)/(\d+) ok, \d+s, \$([\d.]+)", r.stdout)
    return {"total_cost_usd": float(m.group(3)) if m else None, "num_turns": 0,
            "result": (r.stdout + r.stderr)[-2500:]}, wall


def run_arm(arm: str, trial: Path, tasks: str, heldout: Path, model: str) -> dict:
    sh(["git", "checkout", "-q", "main"], trial)
    sh(["git", "pull", "-q"], trial)
    before = {p["number"] for p in open_prs(trial)}
    if arm.startswith("fanout"):
        extra = {"fanout_hedge": ["--hedge", "2"], "fanout_sonnet": ["--model", "sonnet"],
                 "fanout_med": ["--effort", "medium"], "fanout_high": ["--effort", "high"]}.get(arm)
        j, wall = run_fanout(trial, extra)
        new = [p for p in open_prs(trial) if p["number"] not in before]
        rec = {"arm": arm, "wall_s": round(wall), "cost_usd": j.get("total_cost_usd"), "turns": 0, "models": {},
               "prs": [(p["number"], [x["name"] for x in p["labels"]]) for p in new], "result_tail": j["result"]}
        patch = HERE / "patches" / f"{dt.datetime.now():%m%d-%H%M%S}-{arm}.patch"
        patch.parent.mkdir(exist_ok=True)
        rec.update(grade(trial, [p["headRefName"] for p in new], heldout, patch))
        rec["patch"] = patch.name
        cleanup(trial, new)
        return rec
    if arm.endswith("_haiku"):  # the whole session (parent) on haiku; units are haiku anyway
        model = "claude-haiku-5-5"
        arm_base = arm[: -len("_haiku")]
    else:
        arm_base = arm
    if arm_base in ("par", "par_force"):
        force = ("\n計測のため、使う条件(件数・規模)にかかわらず、必ず devaccel-unit を単位の数だけ並列に起動して実装し、"
                 "ship --units で統合して。" if arm_base == "par_force" else "")
        prompt = "/devaccel-batch " + tasks + force + "\n" + TAIL
    else:
        sh(["git", "checkout", "-q", "-B", f"bench/{arm}", "main"], trial)
        how = OLD_PR if arm_base == "seq_old" else "最後に devaccel-pr スキルで PR を 1 本作って。"
        prompt = tasks + "\n上の各件を 1 つのセッションで順番に実装し、" + how + TAIL
    j, wall = claude(prompt, trial, model)
    new = [p for p in open_prs(trial) if p["number"] not in before]
    rec = {"arm": arm, "wall_s": round(wall), "cost_usd": j.get("total_cost_usd"), "turns": j.get("num_turns"),
           "models": usage(j), "prs": [(p["number"], [x["name"] for x in p["labels"]]) for p in new],
           "result_tail": (j.get("result") or "")[-300:]}
    patch = HERE / "patches" / f"{dt.datetime.now():%m%d-%H%M%S}-{arm}.patch"
    patch.parent.mkdir(exist_ok=True)
    rec.update(grade(trial, [p["headRefName"] for p in new], heldout, patch))
    rec["patch"] = patch.name
    cleanup(trial, new)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, default=HERE / "tasks.md")
    ap.add_argument("--heldout", type=Path, default=HERE / "heldout" / "test_par_heldout.py")
    ap.add_argument("--arms", default="seq_old,seq_ship,par")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--cap", type=int, default=None, help="max concurrent subagents for this run")
    a = ap.parse_args()
    global CAP
    CAP = a.cap
    trial = a.trial.expanduser().resolve()
    tasks = a.tasks.read_text(encoding="utf-8")
    global TASKS_PATH
    TASKS_PATH = a.tasks.resolve()
    out = HERE / "results.jsonl"
    for rep in range(a.reps):
        for arm in a.arms.split(","):
            rec = run_arm(arm, trial, tasks, a.heldout.resolve(), a.model)
            rec.update({"rep": rep, "tasks": a.tasks.name, "cap": a.cap,
                        "ts": dt.datetime.now().isoformat(timespec="seconds")})
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(json.dumps(rec, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
