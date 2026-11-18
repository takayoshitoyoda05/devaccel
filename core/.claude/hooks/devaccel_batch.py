# devaccel core — DO NOT EDIT.
"""Deterministic fan-out (no LLM parent): one `claude -p --agent devaccel-unit` per task, all at once,
then `devaccel_ship.py --units` -> one evidence PR.

Run it yourself from a terminal (or `! python3 ...` in Claude Code). Inside Claude Code's sandboxed Bash
the nested `claude` cannot reach the API.

usage: python3 .claude/hooks/devaccel_batch.py TASKS.md --branch batch/NAME [--title T] [--jobs N]
                                              [--model M] [--hedge K] [--keep] [--dry-run]
  --hedge K: run each task K times in separate worktrees; the first copy that passes the gate is used and
             the slower copies are stopped (cuts tail latency; each copy is gated the same way).
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
# never auto-committed from a unit's tree (secrets, keys, devaccel/Claude state)
SKIP_NEW = re.compile(r"(^|/)(\.env(\..*)?|.*\.(pem|key|p12|pfx)|id_(rsa|ed25519|ecdsa)(\.pub)?|\.netrc)$"
                      r"|^\.claude/|^\.devaccel/|(^|/)__pycache__/")


def split_tasks(text: str) -> tuple[str, list[str]]:
    starts = [m.start() for m in ITEM.finditer(text)]
    if not starts:
        return "", [text.strip()] if text.strip() else []
    head = text[: starts[0]].strip()
    items = [text[a:b].strip() for a, b in zip(starts, starts[1:] + [len(text)])]
    return head, items


def context_files(root: Path, text: str, max_files: int = 3, max_bytes: int = 8192) -> str:
    """Inline small existing files the task text names (`path/like.py`): the unit starts with the types and
    helpers it must use instead of spending turns reading them (and guessing wrong)."""
    out, seen = [], set()
    for m in re.finditer(r"`([\w./-]+\.[A-Za-z]{1,5})`", text):
        rel = m.group(1)
        p = (root / rel).resolve()
        if rel in seen or root.resolve() not in p.parents or not p.is_file() or p.stat().st_size > max_bytes:
            continue
        seen.add(rel)
        out.append(f"--- {rel}(参考: 現在の内容)\n" + p.read_text(encoding="utf-8", errors="replace"))
        if len(out) >= max_files:
            break
    return ("\n\n" + "\n\n".join(out)) if out else ""


def mem_available_mb() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def plan_jobs(n_units: int, cli: int, cfg: dict, mem_mb: int, cpus: int) -> tuple[int, str]:
    """How many units run at once: --jobs > project.json parallel.max_jobs > this machine right now."""
    if cli > 0:
        return min(cli, n_units), f"--jobs {cli}"
    par = cfg.get("parallel", {})
    cap = int(par.get("max_jobs") or 0)
    per = max(50, int(par.get("unit_mem_mb") or 300))
    by_mem = max(1, int(mem_mb * 0.8) // per) if mem_mb else 4
    by_cpu = max(1, cpus * 2)
    jobs = min(n_units, by_mem, by_cpu, cap or n_units)
    why = (f"available memory {mem_mb} MB x0.8 / {per} MB per unit = {by_mem}, CPUs {cpus} x2 = {by_cpu}"
           + (f", project max_jobs {cap}" if cap else ""))
    return max(1, jobs), why


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
    ap.add_argument("--jobs", type=int, default=0,
                    help="max concurrent units (0 = project.json parallel.max_jobs, else decided from this machine)")
    ap.add_argument("--model", default="", help="unit model (default: the devaccel-unit agent's model)")
    ap.add_argument("--effort", default="", help="unit effort (default: the devaccel-unit agent's)")
    ap.add_argument("--strong", type=int, default=0,
                    help="run the K longest tasks (by text length, a proxy for size) on sonnet; the slowest unit "
                         "sets the wall clock")
    ap.add_argument("--no-context", action="store_true", help="do not inline the files the tasks name")
    ap.add_argument("--hedge", type=int, default=1, help="run each task N times; the first copy to pass wins")
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
    effort = a.effort or (re.search(r"^effort:\s*(\S+)", front, re.M) or [None, "low"])[1]
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
    copies = max(1, a.hedge)
    strong = set(sorted(range(1, len(items) + 1), key=lambda n: -len(items[n - 1]))[: max(0, a.strong)])
    for i, it in enumerate(items, 1):
        ctx = "" if a.no_context else context_files(root, head + "\n" + it)
        prompt = (head + "\n\n" if head else "") + it + ctx + (
            "\n\nこの 1 件だけを実装し、追加したテストを `uv run pytest -q <テストファイル>` で確かめて終了する。"
            "`scripts/check.sh` は自分で回さない(終了時にゲートが整形込みで必ず回し、落ちていれば差し戻す)。"
            "コミットはしない(ゲートを通った作業ツリーを devaccel_batch がコミットする)。")
        cmd = ["claude", "-p", prompt, "--model", "sonnet" if i in strong else model, "--effort", effort,
               "--append-system-prompt", rules.strip(),
               "--output-format", "json", "--permission-mode", "acceptEdits"]
        for k in range(1, copies + 1):  # --hedge: the same task in k worktrees; the first to pass the gate wins
            tag = f"{slug}-{i}" + (f"h{k}" if copies > 1 else "")
            br, wt = f"unit/{tag}", root / ".claude" / "worktrees" / tag
            r = subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-B", br, str(wt), start],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"worktree for unit {i} failed: {r.stderr.strip()[:200]}", file=sys.stderr)
                return 1
            units.append({"i": i, "k": k, "branch": br, "wt": wt, "cmd": cmd})

    def settle(u: dict) -> str:
        """Commit the tree the gate verified (our own git dir; hooks/fsmonitor off; no secrets/state files),
        then: ok only if there is a commit AND the gate logged a pass for this branch."""
        wt = u["wt"]
        gd = ["--git-dir", str(root / ".git" / "worktrees" / wt.name), "--work-tree", str(wt)]
        safe = ["git", "-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null", *gd]
        subprocess.run([*safe, "add", "-u"], capture_output=True)
        new = subprocess.run([*safe, "ls-files", "--others", "--exclude-standard", "-z"],
                             capture_output=True, text=True).stdout.split("\0")
        keep = [f for f in new if f and not SKIP_NEW.search(f)]
        if keep:
            subprocess.run([*safe, "add", "--", *keep], capture_output=True)
        subprocess.run([*safe, "-c", "user.name=devaccel-batch", "-c", "user.email=devaccel-batch@localhost",
                        "commit", "-q", "--no-verify", "-m",
                        f"unit {u['i']}: " + " ".join(items[u["i"] - 1].split())[3:70]], capture_output=True)
        commits = git(root, "rev-list", "--count", f"{start}..{u['branch']}").strip()
        if commits in ("", "0"):
            return "no commit"
        return "ok" if gate_passed(root, u["branch"], u["t"]) else "gate not passed"

    running, done, won = [], [], {}
    pending = list(units)
    limit, why = plan_jobs(len(units), a.jobs, cfg, mem_available_mb(), os.cpu_count() or 1)
    print(f"running {len(units)} unit(s), {limit} at a time ({why})", flush=True)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}  # anchor: <root>/.claude/worktrees path
    while pending or running:
        while pending and len(running) < limit:
            u = pending.pop(0)
            if u["i"] in won:
                continue
            u["t"] = time.time()
            u["p"] = subprocess.Popen(u["cmd"], cwd=u["wt"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.DEVNULL, text=True, env=env, start_new_session=True)
            running.append(u)
        time.sleep(0.5)
        for u in list(running):
            if u["p"].poll() is None:
                continue
            out, err = u["p"].communicate()
            u["secs"] = round(time.time() - u["t"])
            try:
                u["json"] = json.loads(out)
            except ValueError:
                u["json"] = {"is_error": True, "result": (out + err)[-300:]}
            running.remove(u)
            u["status"] = settle(u) if u["i"] not in won else "superseded"
            done.append(u)
            if u["status"] == "ok" and u["i"] not in won:
                won[u["i"]] = u
                for v in list(running):  # stop the slower copies of the same task
                    if v["i"] == u["i"]:
                        try:
                            os.killpg(v["p"].pid, 15)
                        except OSError:
                            pass

    ok, lines, cost = [], [], 0.0
    log = root / ".devaccel" / f"batch-{slug}.log"
    log.parent.mkdir(exist_ok=True)
    full = []
    for u in sorted(done, key=lambda x: (x["i"], x["k"])):
        j = u["json"]
        cost += float(j.get("total_cost_usd") or 0)  # (stopped copies report no cost: an underestimate)
        full.append(f"=== unit {u['i']}/{u['k']} ({u['branch']}, {u['secs']}s, {u['status']})\n{j.get('result', '')}\n")
        if copies > 1 and won.get(u["i"]) is not u:
            continue
        summary = " ".join((j.get("result") or "").split())[:160]
        lines.append(f"- unit {u['i']} ({u['branch']}, {u['secs']}s): {u['status']} — {summary}")
    for i in range(1, len(items) + 1):
        if i in won:
            ok.append(won[i]["branch"])
        elif copies > 1:
            lines.append(f"- unit {i}: no copy passed the gate")
    log.write_text("\n".join(full), encoding="utf-8")
    print("\n".join(lines))
    print(f"(full unit reports: {log.relative_to(root)})")
    print(f"units: {len(ok)}/{len(items)} ok, {round(time.time() - t0)}s, ${cost:.3f}")

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
    print(f"[timing] units phase {round(time.time() - t0)}s", flush=True)
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("devaccel_ship.py")), "--file",
                        str(notes.relative_to(root)), "--branch", a.branch, "--units", *ok], cwd=root)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
