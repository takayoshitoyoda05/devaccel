# devaccel core — DO NOT EDIT.
"""Deterministic fan-out (no LLM parent): one `claude -p --agent devaccel-unit` per task, all at once,
then `devaccel_ship.py --units` -> one evidence PR.

Run it yourself from a terminal (or `! python3 ...` in Claude Code). Inside Claude Code's sandboxed Bash
the nested `claude` cannot reach the API.

usage: python3 .claude/hooks/devaccel_batch.py TASKS.md --branch batch/NAME [--title T] [--jobs N]
                                              [--model M] [--keep] [--dry-run]
  TASKS.md: optional common paragraph, then items starting with "1. ", "2. ", ... (one unit each).
Verification is unchanged: each unit's session ends with the enforcing gate (check.sh fast, confined);
a unit is integrated only if it committed work AND the gate log shows a pass for its branch; ship then
runs the base branch's check.sh full on the integrated HEAD and triages the single PR.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.append(str(Path(__file__).resolve().parent))
from devaccel_common import git, load_config  # noqa: E402

ITEM = re.compile(r"^\s*(\d+)\.\s+", re.M)


def split_tasks(text: str) -> tuple[str, list[str]]:
    starts = [m.start() for m in ITEM.finditer(text)]
    if not starts:
        return "", [text.strip()] if text.strip() else []
    head = text[: starts[0]].strip()
    items = [text[a:b].strip() for a, b in zip(starts, starts[1:] + [len(text)])]
    return head, items


def gate_passed(root: Path, branch: str, since: float) -> bool:
    log = root / ".claude" / "state" / "gate-log.jsonl"
    if not log.exists():
        return False
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("branch") == branch and e.get("result") == "pass" and e.get("scope") == "unit":
            ts = e.get("ts", "")
            if ts and time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S")) >= since - 2:
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("tasks", type=Path)
    ap.add_argument("--branch", required=True, help="work branch for the integrated PR (batch/...)")
    ap.add_argument("--title", default="")
    ap.add_argument("--jobs", type=int, default=0, help="max concurrent units (0 = all)")
    ap.add_argument("--model", default="", help="unit model (default: the devaccel-unit agent's model)")
    ap.add_argument("--keep", action="store_true", help="keep unit worktrees afterwards")
    ap.add_argument("--dry-run", action="store_true", help="split and show the units only")
    a = ap.parse_args()
    if os.environ.get("CLAUDECODE"):
        print("run this from your terminal (or `! python3 ...`): inside Claude Code's sandbox the nested "
              "`claude` cannot reach the API", file=sys.stderr)
        return 2

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or Path.cwd())
    cfg = load_config(root)
    base = cfg["scale"]["base_branch"]
    head, items = split_tasks(a.tasks.read_text(encoding="utf-8"))
    if not items:
        print("no tasks found (items must start with '1. ', '2. ', ...)", file=sys.stderr)
        return 2
    slug = re.sub(r"[^\w-]", "-", a.branch.split("/")[-1])[:40] or "batch"
    # the unit's rules and model come from the devaccel-unit agent definition (the main checkout's copy);
    # passed as an appended system prompt, not --agent: its `isolation: worktree` is for subagent use
    agent = (root / ".claude" / "agents" / "devaccel-unit.md").read_text(encoding="utf-8")
    front, _, rules = agent.partition("\n---\n")
    model = a.model or (re.search(r"^model:\s*(\S+)", front, re.M) or [None, "haiku"])[1]
    effort = (re.search(r"^effort:\s*(\S+)", front, re.M) or [None, "low"])[1]
    if a.dry_run:
        for i, it in enumerate(items, 1):
            print(f"--- unit {i}\n{it[:200]}")
        return 0
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        print("the main checkout has uncommitted changes; commit or stash first", file=sys.stderr)
        return 2

    subprocess.run(["git", "-C", str(root), "fetch", "-q", "origin", base], capture_output=True)
    start = f"origin/{base}" if git(root, "rev-parse", "-q", "--verify", f"origin/{base}").strip() else base
    units = []
    t0 = time.time()
    for i, it in enumerate(items, 1):
        br = f"unit/{slug}-{i}"
        wt = root / ".claude" / "worktrees" / f"{slug}-{i}"
        r = subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-B", br, str(wt), start],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"worktree for unit {i} failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            return 1
        prompt = (head + "\n\n" if head else "") + it + ("\n\nこの 1 件だけを実装し、`scripts/check.sh fast` を通して終了する。"
                                                         "コミットはしない(検査済みの作業ツリーを devaccel_batch がコミットする)。")
        cmd = ["claude", "-p", prompt, "--model", model, "--effort", effort, "--append-system-prompt", rules.strip(),
               "--output-format", "json", "--permission-mode", "acceptEdits"]
        units.append({"i": i, "branch": br, "wt": wt, "cmd": cmd})

    running, done = [], []
    pending = list(units)
    limit = a.jobs or len(units)
    while pending or running:
        while pending and len(running) < limit:
            u = pending.pop(0)
            u["t"] = time.time()
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}  # anchor: <root>/.claude/worktrees path
            u["p"] = subprocess.Popen(u["cmd"], cwd=u["wt"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.DEVNULL, text=True, env=env)
            running.append(u)
        time.sleep(0.5)
        for u in list(running):
            if u["p"].poll() is not None:
                out, err = u["p"].communicate()
                u["secs"] = round(time.time() - u["t"])
                try:
                    u["json"] = json.loads(out)
                except ValueError:
                    u["json"] = {"is_error": True, "result": (out + err)[-300:]}
                running.remove(u)
                done.append(u)

    ok, lines, cost = [], [], 0.0
    log = root / ".devaccel" / f"batch-{slug}.log"
    log.parent.mkdir(exist_ok=True)
    full = []
    for u in sorted(done, key=lambda x: x["i"]):
        j = u["json"]
        cost += float(j.get("total_cost_usd") or 0)
        full.append(f"=== unit {u['i']} ({u['branch']}, {u['secs']}s)\n{j.get('result', '')}\n")
        # commit exactly the tree the gate verified (the gate checks uncommitted and committed work alike)
        wt = u["wt"]
        if git(wt, "status", "--porcelain").strip():
            subprocess.run(["git", "-C", str(wt), "add", "-A"], capture_output=True)
            subprocess.run(["git", "-C", str(wt), "-c", "user.name=devaccel-batch", "-c",
                            "user.email=devaccel-batch@localhost", "commit", "-q", "-m",
                            f"unit {u['i']}: " + " ".join(items[u["i"] - 1].split())[3:70]], capture_output=True)
        commits = git(root, "rev-list", "--count", f"{start}..{u['branch']}").strip()
        gated = gate_passed(root, u["branch"], u["t"])
        status = "ok" if commits not in ("", "0") and gated else (
            "no commit" if commits in ("", "0") else "gate not passed")
        summary = " ".join((j.get("result") or "").split())[:160]
        lines.append(f"- unit {u['i']} ({u['branch']}, {u['secs']}s): {status} — {summary}")
        if status == "ok":
            ok.append(u["branch"])
    log.write_text("\n".join(full), encoding="utf-8")
    print("\n".join(lines))
    print(f"(full unit reports: {log.relative_to(root)})")
    print(f"units: {len(ok)}/{len(units)} ok, {round(time.time() - t0)}s, ${cost:.3f}")

    if not a.keep:
        for u in units:
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(u["wt"])],
                           capture_output=True)
    if not ok:
        print("no unit to integrate", file=sys.stderr)
        return 1
    notes = root / ".devaccel" / "ship.md"
    notes.parent.mkdir(exist_ok=True)
    title = a.title or f"batch: {len(ok)} units ({slug})"
    notes.write_text(title + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("devaccel_ship.py")), "--file",
                        str(notes.relative_to(root)), "--branch", a.branch, "--units", *ok], cwd=root)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
