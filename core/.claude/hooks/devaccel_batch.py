# devaccel core — DO NOT EDIT.
"""Deterministic fan-out (no LLM parent): one lean `claude -p` per task (the devaccel-unit rules appended to
its system prompt), all at once, then `devaccel_ship.py --units` -> one evidence PR.

Runs from a terminal, or from Claude Code when the project's settings run this exact command outside the
sandbox (devaccel's settings do; inside the sandbox the nested `claude` cannot reach the API).

usage: python3 .claude/hooks/devaccel_batch.py TASKS.md --branch batch/NAME [--title T] [--jobs N]
              [--model M] [--effort E] [--strong K] [--hedge K] [--speculate] [--no-context]
              [--unit-timeout S] [--keep] [--dry-run]
  TASKS.md: optional common paragraph, then items starting with "1. ", "2. ", ... (one unit each).
Verification: each unit's session ends with the enforcing gate (check.sh fast, confined) for feedback;
then this script commits the unit's tree itself and re-runs the main checkout's check.sh fast on exactly
that commit, confined, and requires the tree to be unchanged afterwards. Only units that pass are
integrated; ship then runs the base branch's check.sh full on the integrated HEAD and triages the PR.
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
from stop_gate import run_check  # noqa: E402

ITEM = re.compile(r"^\s*(\d+)\.\s+", re.M)
# never auto-committed from a unit's tree, never inlined into a prompt (secrets, keys, devaccel/Claude state)
SKIP_NEW = re.compile(r"(^|/)(\.?env|[^/]*\.env|\.env\.[^/]*|[^/]*\.(pem|key|p12|pfx|jks|keystore)|id_(rsa|ed25519|ecdsa|dsa)"
                      r"(\.pub)?|\.netrc|\.npmrc|\.pypirc|credentials(\.[^/]*)?|secrets?(\.[^/]*)?|[^/]*\.tfstate)$"
                      r"|(^|/)\.(aws|ssh|gnupg|docker|kube)/|^\.claude/|^\.devaccel/|^CLAUDE\.md$|(^|/)__pycache__/",
                      re.I)
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def clean(s: str) -> str:
    """A unit's free text, made safe for the terminal and a PR body: no control/escape or bidi characters,
    and no @mentions, issue links/closing keywords or HTML comments that would act on GitHub."""
    s = CTRL.sub("", s)
    return (s.replace("<", "&lt;").replace(">", "&gt;").replace("@", "@\u200b")
            .replace("#", "#\u200b"))


def split_tasks(text: str) -> tuple[str, list[str]]:
    starts = [m.start() for m in ITEM.finditer(text)]
    if not starts:
        return "", [text.strip()] if text.strip() else []
    head = text[: starts[0]].strip()
    items = [text[a:b].strip() for a, b in zip(starts, starts[1:] + [len(text)])]
    return head, items


def task_warnings(item: str) -> list[str]:
    """Cheap checks for the things that make units iterate (see the devaccel-batch skill)."""
    w = []
    if not re.search(r"`[\w./-]+\.[A-Za-z]{1,5}`", item):
        w.append("編集するファイルが `path` の形で名指しされていない")
    if not re.search(r"test", item, re.I):
        w.append("テスト(ファイルか確かめ方)の指定がない")
    if len(item) < 80:
        w.append("短すぎる(型・境界の例・例外を書くと単位の往復が減る)")
    return w


def context_files(root: Path, text: str, max_files: int = 3, max_bytes: int = 8192) -> str:
    """Inline small existing files the task text names (`path/like.py`): the unit starts with the types and
    helpers it must use instead of spending turns reading them (and guessing wrong)."""
    out, seen = [], set()
    tracked = set(git(root, "ls-files", "-z").split("\0"))
    for m in re.finditer(r"`([\w./-]+\.[A-Za-z]{1,5})`", text):
        rel = m.group(1)
        p = (root / rel).resolve()
        if rel in seen or root.resolve() not in p.parents or not p.is_file() or p.stat().st_size > max_bytes:
            continue
        rel = p.relative_to(root.resolve()).as_posix()
        if rel not in tracked or SKIP_NEW.search(rel):  # only committed project files, never secrets
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


def in_sandbox() -> bool:
    """Inside Claude Code's sandbox a nested bwrap cannot start (and the nested claude has no API access)."""
    import shutil
    bw = shutil.which("bwrap")
    if not bw:
        return bool(os.environ.get("CLAUDECODE"))
    return subprocess.run([bw, "--unshare-pid", "--ro-bind", "/", "/", "true"], capture_output=True,
                          stdin=subprocess.DEVNULL).returncode != 0


def protected_names(root: Path, base: str) -> set[str]:
    names = {"main", "master", base}
    h = git(root, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD").strip()
    return names | ({h.split("/", 1)[-1]} if h else set())


def preflight(root: Path, base: str, branch: str) -> list[str]:
    """Everything that would otherwise fail only after all units ran."""
    import shutil
    errs = []
    if not re.fullmatch(r"[\w./-]+", branch) or ".." in branch or branch in protected_names(root, base):
        errs.append(f"--branch {branch!r} is not a valid work branch name")
    cur = git(root, "symbolic-ref", "--short", "-q", "HEAD").strip()
    if cur and cur != branch and cur not in protected_names(root, base):
        errs.append(f"on branch {cur}: run from {base} (a new {branch} is created from origin/{base})")
    if cur != branch and git(root, "rev-parse", "-q", "--verify", f"refs/heads/{branch}").strip():
        errs.append(f"branch {branch} already exists; pick another --branch")
    for tool in ("claude", "gh", "bwrap"):
        if not shutil.which(tool):
            errs.append(f"`{tool}` is not on PATH")
    if not git(root, "config", "--get", "remote.origin.url").strip():
        errs.append("no origin remote")
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        errs.append("the main checkout has uncommitted changes; commit or stash first")
    if git(root, "status", "--porcelain", "--untracked-files=no", "--", ".claude").strip() or \
            git(root, "ls-files", "--others", "--exclude-standard", "--", ".claude/hooks", ".claude/agents").strip():
        errs.append(".claude is not committed (units start from origin and would miss it)")
    return errs


def cleanup(root: Path, units: list[dict], keep: bool, branches: bool = False) -> None:
    """Stop what still runs; remove unit worktrees (even broken ones) and, after shipping, unit branches."""
    import shutil
    for u in units:
        p = u.get("p")
        if p is not None and p.poll() is None:
            try:
                os.killpg(p.pid, 9)
            except OSError:
                pass
    if keep:
        return
    for u in units:
        r = subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(u["wt"])],
                           capture_output=True)
        if r.returncode != 0 and u["wt"].exists():
            shutil.rmtree(u["wt"], ignore_errors=True)
    subprocess.run(["git", "-C", str(root), "worktree", "prune"], capture_output=True)
    if branches:
        subprocess.run(["git", "-C", str(root), "branch", "-q", "-D", *[u["branch"] for u in units]],
                       capture_output=True)


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
    ap.add_argument("--speculate", action="store_true",
                    help="start a backup copy of a straggling unit once half the units have passed (measured: the "
                         "original usually finishes first, so off by default)")
    ap.add_argument("--hedge", type=int, default=1, help="run each task N times; the first copy to pass wins")
    ap.add_argument("--unit-timeout", type=int, default=900, help="seconds before a unit is stopped")
    ap.add_argument("--max-turns", type=int, default=40, help="turn limit per unit")
    ap.add_argument("--keep", action="store_true", help="keep unit worktrees and branches afterwards")
    ap.add_argument("--dry-run", action="store_true", help="check everything and show the plan; run nothing")
    a = ap.parse_args()

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or Path.cwd())
    if os.environ.get("CLAUDECODE"):  # started by the model, outside the sandbox: the guard's grammar, re-checked
        tf = Path(os.path.realpath(a.tasks))
        extra = [k for k, v in vars(a).items() if k not in ("tasks", "branch", "dry_run") and v != ap.get_default(k)]
        if (tf.parent != (root / ".devaccel").resolve() or tf.suffix != ".md" or tf.is_symlink()
                or Path(a.tasks).is_symlink() or not re.fullmatch(r"batch/[\w-]+", a.branch) or extra):
            print("from Claude Code only `.devaccel/<name>.md --branch batch/<name> [--dry-run]` is allowed "
                  "(other options: run it from a terminal)", file=sys.stderr)
            return 2
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
    errs = preflight(root, base, a.branch)
    if in_sandbox():
        errs.append("inside Claude Code's sandbox the nested `claude` cannot reach the API: run it from a "
                    "terminal, or let devaccel's settings run it outside the sandbox (/devaccel-setup)")
    for n, it in enumerate(items, 1):
        for msg in task_warnings(it):
            print(f"warning: task {n}: {msg}", flush=True)
    if a.dry_run:
        for i, it in enumerate(items, 1):
            print(f"--- unit {i}\n{clean(it[:200])}")
        jobs, why = plan_jobs(len(items) * max(1, a.hedge), a.jobs, cfg, mem_available_mb(), os.cpu_count() or 1)
        print(f"would run {len(items)} unit(s), {jobs} at a time ({why})")
    for e in errs:
        print(f"error: {e}", file=sys.stderr)
    if errs or a.dry_run:
        return 2 if errs else 0

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
        # lean session: no MCP servers, only the tools a unit uses, no skill/command listing. That context is
        # resent every turn (measured ~31K -> ~12K tokens); hooks, sandbox and CLAUDE.md still apply
        cmd = ["claude", "-p", prompt, "--model", "sonnet" if i in strong else model, "--effort", effort,
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--tools", "Read", "Edit", "Write", "Bash", "Grep", "Glob", "--disable-slash-commands",
               "--append-system-prompt", rules.strip(),
               "--max-turns", str(a.max_turns), "--output-format", "json", "--permission-mode", "acceptEdits"]
        for k in range(1, copies + 1):  # --hedge: the same task in k worktrees; the first to pass the gate wins
            tag = f"{slug}-{i}" + (f"h{k}" if copies > 1 else "")
            br, wt = f"unit/{tag}", root / ".claude" / "worktrees" / tag
            r = subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-B", br, str(wt), start],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"worktree for unit {i} failed: {r.stderr.strip()[:200]}", file=sys.stderr)
                cleanup(root, units, a.keep)
                return 1
            units.append({"i": i, "k": k, "branch": br, "wt": wt, "cmd": cmd})

    def settle(u: dict) -> str:
        """Commit the unit's tree (our own git dir; hooks/fsmonitor off; no secrets/state files), then check
        exactly that commit ourselves: the main checkout's check.sh fast, confined, and the tree must be
        unchanged afterwards. The unit's own gate log is not trusted (the unit could write or race it)."""
        wt = u["wt"]
        gd = ["--git-dir", str(root / ".git" / "worktrees" / wt.name), "--work-tree", str(wt)]
        safe = ["git", "-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null", "-c", "core.quotePath=false",
                *gd]
        try:
            os.killpg(u["p"].pid, 9)  # leftovers of the unit's session must not touch the tree being checked
        except OSError:
            pass
        subprocess.run([*safe, "add", "-u"], capture_output=True)
        staged = subprocess.run([*safe, "diff", "--cached", "--name-only", "-z"], capture_output=True,
                                text=True).stdout.split("\0")
        bad = [f for f in staged if f and SKIP_NEW.search(f)]
        if bad:  # tracked devaccel/Claude config or secrets edited by a unit: never auto-committed
            subprocess.run([*safe, "reset", "-q", "--", *bad], capture_output=True)
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
        changed = git(root, "diff", "--name-only", "-z", start, u["branch"]).split("\0")
        touched = [f for f in changed if f and SKIP_NEW.search(f)]
        if touched:  # e.g. the unit committed by itself: secrets or devaccel/Claude config are never integrated
            return "touches protected files: " + ", ".join(touched[:3])
        subprocess.run([*safe, "checkout", "-q", "--", "."], capture_output=True)  # tree == commit
        subprocess.run([*safe, "clean", "-q", "-f", "-d"], capture_output=True)  # (ignored files stay: .venv)
        sha = git(root, "rev-parse", u["branch"]).strip()
        result, _, out, _ = run_check(wt, int(cfg["gate"]["timeout_sec"]), anchor=root,
                                      sandbox=bool(cfg["gate"].get("sandbox", True)))
        u["check_tail"] = out[-1500:]
        after = subprocess.run([*safe, "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                               text=True).stdout.strip()
        if result != "pass":
            return f"check {result}"
        if after or git(root, "rev-parse", u["branch"]).strip() != sha:
            return "tree changed during the check"
        return "ok"

    def backup(u: dict) -> dict | None:
        """A second copy of a straggler's task in a fresh worktree (speculative execution)."""
        tag = f"{slug}-{u['i']}s"
        br, wt = f"unit/{tag}", root / ".claude" / "worktrees" / tag
        r = subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-B", br, str(wt), start],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None
        v = {"i": u["i"], "k": 9, "branch": br, "wt": wt, "cmd": u["cmd"], "backup": True}
        units.append(v)
        return v

    running, done, won, speculated = [], [], {}, set()
    pending = list(units)
    limit, why = plan_jobs(len(units), a.jobs, cfg, mem_available_mb(), os.cpu_count() or 1)
    print(f"running {len(units)} unit(s), {limit} at a time ({why})", flush=True)
    # a fresh session per unit: drop the parent session's markers (the anchor comes from the worktree path)
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "CLAUDE_PROJECT_DIR", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")}
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=max(1, limit))  # settling (commit + own check) overlaps the units
    settling: dict = {}

    def launch(u: dict) -> None:
        u["t"] = time.time()
        u["p"] = subprocess.Popen(u["cmd"], cwd=u["wt"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  stdin=subprocess.DEVNULL, text=True, env=env, start_new_session=True)
        running.append(u)

    try:
        while pending or running or settling:
            while pending and len(running) + len(settling) < limit:
                u = pending.pop(0)
                if u["i"] not in won:
                    launch(u)
            time.sleep(0.5)
            passed = sorted(x["secs"] for x in done if x.get("status") == "ok")
            if a.speculate and len(passed) * 2 >= len(items) and len(running) < limit:
                med = passed[len(passed) // 2]
                for u in list(running):  # a straggler gets one backup copy; the first copy to pass wins
                    late = time.time() - u["t"] > max(1.4 * med, med + 15)
                    if late and u["i"] not in won and u["i"] not in speculated and len(running) < limit:
                        v = backup(u)
                        if v is not None:
                            speculated.add(u["i"])
                            launch(v)
                            print(f"unit {u['i']} is straggling ({round(time.time() - u['t'])}s vs median "
                                  f"{med}s): started a backup copy", flush=True)
            for u in list(running):
                if u["p"].poll() is None:
                    if time.time() - u["t"] > a.unit_timeout:
                        try:
                            os.killpg(u["p"].pid, 9)
                        except OSError:
                            pass
                        u["timed_out"] = True
                    continue
                out, err = u["p"].communicate()
                u["secs"] = round(time.time() - u["t"])
                try:
                    u["json"] = json.loads(out)
                    if not isinstance(u["json"], dict):
                        raise ValueError
                except ValueError:
                    u["json"] = {"is_error": True, "result": (out + err)[-300:]}
                running.remove(u)
                if u.get("timed_out"):
                    u["status"] = f"timeout ({a.unit_timeout}s)"
                    done.append(u)
                elif u["i"] in won:
                    u["status"] = "superseded"
                    done.append(u)
                else:
                    settling[id(u)] = (u, pool.submit(settle, u))
            for key, (u, fut) in list(settling.items()):
                if not fut.done():
                    continue
                del settling[key]
                try:
                    u["status"] = fut.result()
                except Exception as e:  # noqa: BLE001 - a failed settle is a failed unit, never a pass
                    u["status"] = f"settle error: {type(e).__name__}"
                if u["status"] == "ok" and u["i"] in won:
                    u["status"] = "superseded"
                done.append(u)
                if u["status"] == "ok":
                    won[u["i"]] = u
                    for v in list(running):  # stop the slower copies of the same task
                        if v["i"] == u["i"]:
                            try:
                                os.killpg(v["p"].pid, 15)
                            except OSError:
                                pass
    except BaseException:
        cleanup(root, units, a.keep, branches=True)
        raise
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    ok, lines, cost = [], [], 0.0
    log = root / ".devaccel" / f"batch-{slug}.log"
    log.parent.mkdir(exist_ok=True)
    full = []
    for u in sorted(done, key=lambda x: (x["i"], x["k"])):
        j = u["json"]
        cost += float(j.get("total_cost_usd") or 0)  # (stopped copies report no cost: an underestimate)
        full.append(f"=== unit {u['i']}/{u['k']} ({u['branch']}, {u['secs']}s, {u['status']})\n"
                    f"{clean(str(j.get('result', '')))}\n" + (f"--- check\n{clean(u['check_tail'])}\n"
                                                             if u.get("check_tail") and u["status"] != "ok" else ""))
        if copies > 1 and won.get(u["i"]) is not u:
            continue
        # in a code span: no markdown links/images, HTML, mentions or closing keywords render in the PR body
        summary = "`" + clean(" ".join(str(j.get("result") or "").split())[:160]).replace("`", "'") + "`"
        lines.append(f"- unit {u['i']} ({u['branch']}, {u['secs']}s): {u['status']} — {summary}")
    for i in range(1, len(items) + 1):
        if i in won:
            ok.append(won[i]["branch"])
        elif copies > 1:
            lines.append(f"- unit {i}: no copy passed the gate")
    log.write_text("\n".join(full), encoding="utf-8")
    # compact on stdout (a Claude session reading this pays for every line); the reports go to the log and PR
    for u in sorted(done, key=lambda x: (x["i"], x["k"])):
        if u["status"] != "ok" and u["status"] != "superseded":
            print(f"- unit {u['i']} ({u['branch']}): {clean(u['status'])}")
    print(f"(unit reports: {log.relative_to(root)})")
    print(f"units: {len(ok)}/{len(items)} ok, {round(time.time() - t0)}s, ${cost:.3f}")
    (root / ".devaccel" / "batch-last.json").write_text(json.dumps(  # machine-readable (cost of the units)
        {"branch": a.branch, "units": len(items), "ok": len(ok), "secs": round(time.time() - t0),
         "cost_usd": round(cost, 4), "ts": time.time()}), encoding="utf-8")

    cleanup(root, units, a.keep)
    if not ok:
        print("no unit to integrate", file=sys.stderr)
        cleanup(root, units, a.keep, branches=True)
        return 1
    notes = root / ".devaccel" / "ship.md"
    notes.parent.mkdir(exist_ok=True)
    title = a.title or f"batch: {len(ok)} units ({slug})"
    notes.write_text(title + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    if os.environ.get("DEVACCEL_TIMING"):
        print(f"[timing] units phase {round(time.time() - t0)}s", flush=True)
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("devaccel_ship.py")), "--file",
                        str(notes.relative_to(root)), "--branch", a.branch, "--units", *ok], cwd=root)
    cleanup(root, units, a.keep, branches=r.returncode == 0)  # integrated: the unit branches are no longer needed
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
