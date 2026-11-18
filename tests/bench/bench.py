"""Vanilla Claude Code vs devaccel on the trial project (kit-side only; not distributed).

Same tasks, same model, same starting commit. Each run starts from a reset clone at a fixed
path per condition (fixed paths so workspace trust can be granted once). After the run the
held-out tests (never visible to the agent) and the trial's own check.sh full are applied.

usage: python3 tests/bench/bench.py --trial ~/programming/python/devaccel-trial \
         [--model claude-sonnet-5-5] [--reps 1] [--tasks t1_min,t2_month] [--conds vanilla,devaccel]
Results: tests/bench/results/<date>.jsonl (+ a markdown table on stdout).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path.home() / "programming" / "python" / "devaccel-bench"
# narrow on purpose: no interpreters/launchers (python3, cat, generic uv run). The agent runs as the user
# (subscription auth lives in ~/.claude), so the allowlist is the boundary; devaccel runs add its sandbox.
ALLOWED = ["Read", "Edit", "Write", "Glob", "Grep", "Bash(uv run pytest*)", "Bash(uv run kakeibo *)",
           "Bash(uv run ruff *)", "Bash(uv run pyright*)", "Bash(scripts/check.sh fast)", "Bash(scripts/check.sh full)",
           "Bash(git status*)", "Bash(git diff*)"]


def sh(cmd: list[str], cwd: Path, timeout: int = 900, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
                          stdin=subprocess.DEVNULL)


CONDS = ("vanilla", "devaccel", "devaccel-nosandbox", "devaccel-enforce")


def prepare(cond: str, trial: Path, ref: str) -> Path:
    # ablations reuse the trusted devaccel clone (workspace trust is per path)
    d = WORK / ("vanilla" if cond == "vanilla" else "devaccel")
    if not d.exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "clone", "-q", str(trial), str(d)], d.parent)
    sh(["git", "fetch", "-q", "origin"], d)
    sh(["git", "checkout", "-q", "--detach", ref], d)
    sh(["git", "reset", "-q", "--hard", ref], d)
    sh(["git", "clean", "-qfdx", "-e", ".venv"], d)
    if cond == "vanilla":  # the same project without the kit: no .claude/, CLAUDE.md = description + commands
        shutil.rmtree(d / ".claude", ignore_errors=True)
        (d / ".worktreeinclude").unlink(missing_ok=True)
        cm = (d / "CLAUDE.md").read_text(encoding="utf-8")
        (d / "CLAUDE.md").write_text(cm.split("\n## 進め方")[0].rstrip() + "\n", encoding="utf-8")
        sh(["git", "-c", "user.email=b@b", "-c", "user.name=bench", "commit", "-qam", "vanilla"], d)
    elif cond == "devaccel-nosandbox":  # isolate the sandbox's cost
        st = json.loads((d / ".claude/settings.json").read_text(encoding="utf-8"))
        st.get("sandbox", {})["enabled"] = False
        (d / ".claude/settings.json").write_text(json.dumps(st, indent=2), encoding="utf-8")
        sh(["git", "-c", "user.email=b@b", "-c", "user.name=bench", "commit", "-qam", cond], d)
    sh(["uv", "sync", "-q"], d)
    return d


def grade(d: Path, task: str, check_sh: str) -> dict:
    t = d / "tests"
    shutil.copy(HERE / "heldout" / "_common.py", t / "_heldout_common.py")
    shutil.copy(HERE / "heldout" / f"test_{task}.py", t / f"test_heldout_{task}.py")
    r = sh(["uv", "run", "pytest", "-q", "-p", "no:cacheprovider", f"tests/test_heldout_{task}.py"], d)
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    num = lambda k: int(m.group(1)) if (m := re.search(rf"(\d+) {k}", last)) else 0  # noqa: E731
    failed, passed = num("failed") + num("error"), num("passed")
    if r.returncode not in (0, 1):  # collection error etc.
        failed, passed = -1, 0
    (t / "_heldout_common.py").unlink()
    (t / f"test_heldout_{task}.py").unlink()
    cs = HERE / "results" / "_check.sh"
    cs.write_text(check_sh.replace('cd "$(dirname "$0")/.."', 'cd "$DEVACCEL_ROOT"'))
    c = sh(["bash", str(cs), "full"], d, env={**os.environ, "DEVACCEL_ROOT": str(d)})
    cs.unlink()
    stat = sh(["git", "diff", "--shortstat"], d).stdout.strip()
    untracked = [f for f in sh(["git", "ls-files", "-o", "--exclude-standard"], d).stdout.split() if f]
    return {"heldout_passed": passed, "heldout_failed": failed, "check_full": c.returncode == 0,
            "check_failed_stages": re.findall(r"== failed: (\w+)", c.stdout + c.stderr),
            "diff": stat, "new_files": untracked,
            "readme_changed": "README.md" in sh(["git", "diff", "--name-only"], d).stdout}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", type=Path, required=True)
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--tasks", default="t1_min,t2_month,t3_top")
    ap.add_argument("--conds", default=",".join(CONDS))
    ap.add_argument("--max-turns", type=int, default=60)
    a = ap.parse_args()
    trial = a.trial.expanduser().resolve()
    sh(["git", "fetch", "-q", "origin"], trial)
    ref = sh(["git", "rev-parse", a.ref], trial).stdout.strip()
    check_sh = sh(["git", "show", f"{ref}:scripts/check.sh"], trial).stdout
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    log = out / f"{dt.date.today()}.jsonl"
    runs = [(t, c, i) for t in a.tasks.split(",") for c in a.conds.split(",") for i in range(a.reps)]
    random.shuffle(runs)
    for task, cond, rep in runs:
        d = prepare(cond, trial, ref)
        prompt = (HERE / "tasks" / f"{task}.md").read_text(encoding="utf-8")
        t0 = time.time()
        keep = ("PATH", "HOME", "USER", "LANG", "TERM", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "UV_CACHE_DIR")
        env = {k: v for k, v in os.environ.items() if k in keep}  # no stray tokens from this shell
        if cond == "devaccel-enforce":  # the interactive gate forced on (pre-0.8 behaviour, for comparison)
            env["DEVACCEL_GATE_MODE"] = "enforce"
        r = sh(["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", a.model,
                "--max-turns", str(a.max_turns), "--permission-mode", "acceptEdits",
                "--allowedTools", *ALLOWED], d, timeout=3600, env=env)
        wall = round(time.time() - t0)
        j, tools = {"is_error": True, "result": (r.stdout + r.stderr)[-500:]}, {}
        for line in r.stdout.splitlines():  # stream-json: count tool calls (incl. Skill) for the breakdown
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "result":
                j = ev
            msg = ev.get("message") if isinstance(ev, dict) else None
            content = msg.get("content") if isinstance(msg, dict) else None
            for blk in content if isinstance(content, list) else []:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    key = blk["name"] + (f":{blk['input'].get('skill') or blk['input'].get('command', '')}"
                                         if blk["name"] == "Skill" else "")
                    tools[key] = tools.get(key, 0) + 1
        u = j.get("usage") or {}
        rec = {"task": task, "cond": cond, "rep": rep, "ref": ref[:8], "model": a.model, "wall_s": wall,
               "turns": j.get("num_turns"), "cost_usd": j.get("total_cost_usd"), "is_error": j.get("is_error"),
               "subtype": j.get("subtype"), "in": u.get("input_tokens"), "out": u.get("output_tokens"),
               "cache_read": u.get("cache_read_input_tokens"), "cache_write": u.get("cache_creation_input_tokens"),
               "tools": tools,
               **grade(d, task, check_sh)}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
