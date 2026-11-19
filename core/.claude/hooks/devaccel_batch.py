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
import uuid
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.append(str(Path(__file__).resolve().parent))
from devaccel_common import git, id_present, load_config, write_nofollow  # noqa: E402
from stop_gate import run_check  # noqa: E402

# "1. ", also as a markdown heading or bold ("## 1. ", "**1.** ") — how a session tends to rewrite a list
ITEM = re.compile(r"^[ \t]*(?:#{1,6}[ \t]+)?(?:\*\*)?(\d+)\.(?:\*\*)?[ \t]+", re.M)
# never auto-committed from a unit's tree, never inlined into a prompt (secrets, keys, devaccel/Claude state)
SKIP_NEW = re.compile(r"(^|/)(\.?env|[^/]*\.env|\.env\.[^/]*|[^/]*\.(pem|key|p12|pfx|jks|keystore)|id_(rsa|ed25519|ecdsa|dsa)"
                      r"(\.pub)?|\.netrc|\.npmrc|\.pypirc|credentials(\.[^/]*)?|secrets?(\.[^/]*)?|[^/]*\.tfstate)$"
                      r"|(^|/)\.(aws|ssh|gnupg|docker|kube)/|^\.claude/|^\.devaccel/|^CLAUDE\.md$|(^|/)__pycache__/"
                      r"|^scripts/check\.sh$|^\.github/",  # the verification machinery itself
                      re.I)
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


EXAMPLE_ID = re.compile(r"^\|\s*(E\d+-\d+)\s*\|", re.M)
TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$|(^|/)tests?/")


def example_ids(item: str) -> list[str]:
    """IDs of the example table rows in a design-doc item (`| E1-2 | input | output | rule |`)."""
    return list(dict.fromkeys(EXAMPLE_ID.findall(item)))


def clean(s: str) -> str:
    """A unit's free text, made safe for the terminal and a PR body: no control/escape or bidi characters,
    and no @mentions, issue links/closing keywords or HTML comments that would act on GitHub."""
    s = CTRL.sub("", s)
    return (s.replace("<", "&lt;").replace(">", "&gt;").replace("@", "@\u200b")
            .replace("#", "#\u200b"))


MORE_MARK, END_MARK = "<!-- more -->", "<!-- end -->"


def complete_items(text: str) -> list[str]:
    """--watch: the items that are finished — all once END_MARK is there, else those before the last MORE_MARK."""
    if END_MARK in text:
        return split_tasks(text.replace(END_MARK, ""))[1]
    cut = text.rfind(MORE_MARK)
    return split_tasks(text[:cut])[1] if cut >= 0 else []


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


def _read_nofollow(p: Path) -> bytes | None:
    """Contents of a regular file without following a link at the file (and not through linked dirs)."""
    import stat
    try:
        if any(x.is_symlink() for x in p.parents):
            return None
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return None
            return fh.read(5_000_000)
    except OSError:
        return None


def write_nofollow_deep(base: Path, rel: str, data: bytes) -> bool:
    """Write base/rel, walking every directory relative to its parent's fd with O_NOFOLLOW (no window in which a
    concurrently planted link could redirect the write)."""
    parts = Path(rel).parts
    try:
        fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o755, dir_fd=fd)
            except FileExistsError:
                pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        out = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644, dir_fd=fd)
        with os.fdopen(out, "wb") as fh:
            fh.write(data)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _digest(p: Path) -> str:
    """sha256 of a regular file (no link followed), '' if absent."""
    import hashlib
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as fh:
            return hashlib.sha256(fh.read(5_000_000)).hexdigest()
    except OSError:
        return ""


def cleanup(root: Path, units: list[dict], keep: bool, branches: bool = False) -> None:
    """Stop what still runs; remove unit worktrees (even broken ones) and, after shipping, unit branches."""
    import shutil
    for u in units:
        for p in (u.get("p"), (u.get("tester") or {}).get("p")):
            if p is not None and p.poll() is None:
                try:
                    os.killpg(p.pid, 9)
                except OSError:
                    pass
        p = None
        if p is not None and p.poll() is None:
            try:
                os.killpg(p.pid, 9)
            except OSError:
                pass
    if keep:
        return
    for u in units:
        for wt in (u["wt"], (u.get("tester") or {}).get("wt")):
            if wt is None:
                continue
            r = subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(wt)],
                               capture_output=True)
            if r.returncode != 0 and wt.exists():
                shutil.rmtree(wt, ignore_errors=True)
    subprocess.run(["git", "-C", str(root), "worktree", "prune"], capture_output=True)
    if branches:
        subprocess.run(["git", "-C", str(root), "branch", "-q", "-D", *[u["branch"] for u in units],
                        *[u["tester"]["branch"] for u in units if u.get("tester")]], capture_output=True)


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
    ap.add_argument("--watch", action="store_true",
                    help="the file is still being written: start each item's unit as soon as it is complete (items "
                         "before a `<!-- more -->` line, all items once `<!-- end -->` is there)")
    ap.add_argument("--dry-run", action="store_true", help="check everything and show the plan; run nothing")
    a = ap.parse_args()

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or Path.cwd())
    if os.environ.get("CLAUDECODE"):  # started by the model, outside the sandbox: the guard's grammar, re-checked
        tf = Path(os.path.realpath(a.tasks))
        extra = [k for k, v in vars(a).items() if k not in ("tasks", "branch", "dry_run", "watch") and v != ap.get_default(k)]
        allowed = [d for d in (root / ".devaccel", root / "docs" / "design")  # real directories inside the repo:
                   if not any(p.is_symlink() for p in (d, d.parent))]  # a linked dir could point at ~/.ssh
        if (tf.parent not in [d.resolve() for d in allowed] or not tf.is_relative_to(root.resolve())
                or tf.suffix != ".md" or tf.is_symlink()
                or Path(a.tasks).is_symlink() or not re.fullmatch(r"batch/[\w-]+", a.branch) or extra):
            print("from Claude Code only `.devaccel/<name>.md` (or docs/design/<name>.md) `--branch batch/<name> "
                  "[--dry-run]` is allowed "
                  "(other options: run it from a terminal)", file=sys.stderr)
            return 2
    cfg = load_config(root)
    base = cfg["scale"]["base_branch"]
    head, items = split_tasks(a.tasks.read_text(encoding="utf-8"))
    watching = a.watch and not a.dry_run and END_MARK not in a.tasks.read_text(encoding="utf-8")
    if watching:
        items = complete_items(a.tasks.read_text(encoding="utf-8"))
    if a.tasks.name == "prompt.md" and not a.dry_run:  # written by the guard for this run only: never reused
        write_nofollow(root / ".devaccel" / "prompt.md", None)
    if not watching and (not items or (os.environ.get("CLAUDECODE") and len(items) < 2)):
        print(f"{len(items)} task(s) found: a fan-out needs items starting with '1. ', '2. ', ... (one per line "
              "start); for a single task just implement it", file=sys.stderr)
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
    # dual track (tester || implementer per item): project setting parallel.dual_track or DEVACCEL_DUAL=1
    dual = bool(cfg["parallel"].get("dual_track")) or os.environ.get("DEVACCEL_DUAL") == "1"
    strong = set(sorted(range(1, len(items) + 1), key=lambda n: -len(items[n - 1]))[: max(0, a.strong)])
    def add_item(i: int, it: str) -> bool:
        """Worktree(s) and command for item i; False if a worktree could not be made."""
        ctx = "" if a.no_context else context_files(root, head + "\n" + it)
        if example_ids(it):
            ctx += ("\n\n例の表の全行を、ID をテストの中に書いて(parametrize の ids など)テストに写してから実装する。"
                    "端のケースは表に列挙済みなので考え直さない。ID が 1 つでもテストに無ければ統合されない。")
        tester = None
        if dual:  # dual track: a tester writes the spec tests while this unit implements, in the same worktree
            tfiles = sorted(set(re.findall(r"`((?:[\w./-]*/)?tests?/[\w./-]+\.py|(?:[\w./-]*/)?test_[\w.-]+\.py)`", it)))
            tester = {"sid": str(uuid.uuid4()), "files": tfiles}
            tprompt = ((head + "\n\n" if head else "") + it + ctx + "\n\nあなたはテスト係。この件の仕様(規則・例・判断)から、"
                       f"テストファイル {' '.join('`' + f + '`' for f in tfiles) or '(仕様が名指しするテストファイル)'} "
                       "だけを書く。実装(src)は書かない・読まない(別の単位が同時に書いている)。関数・クラスは仕様の名前と型の"
                       "とおりに import する。例の表の全行を ID 付きで、加えて各規則(R#)の端を 1 つ以上テストにする。期待値は"
                       "仕様から決め、仕様に無い振る舞いはテストしない。テストは実行しない(実装がまだ無い)。最後に "
                       "`uv run ruff check --fix <テストファイル>` を 1 回だけ回して終える。")
            tester["cmd"] = ["claude", "-p", tprompt, "--model", model, "--effort", effort, "--session-id", tester["sid"],
                             "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                             "--tools", "Read", "Edit", "Write", "Bash", "Grep", "Glob", "--disable-slash-commands",
                             "--max-turns", "20", "--output-format", "json", "--permission-mode", "acceptEdits"]
            ctx += ("\n\nテストは別の単位(テスト係)がこの作業ツリーで同時に "
                    f"{' '.join('`' + f + '`' for f in tester['files']) or '仕様のテストファイル'} に書いている。そのファイルは"
                    "作らない・変えない(変えるとこの件は統合されない)。実装だけを書き、簡単に動かして確かめたら終える。終了時に"
                    "ゲートがテスト係のテストを走らせ、落ちていれば差し戻す。落ちたテストが仕様と矛盾すると思うときは、テストは"
                    "変えずに、どの規則(R#)と矛盾するかを最後の報告に書く。")
        prompt = (head + "\n\n" if head else "") + it + ctx + (
            "\n\nこの 1 件だけを実装し、追加したテストを `uv run pytest -q <テストファイル>` で確かめて終了する。"
            if not dual else "\n\nこの 1 件だけを実装する。"
            + ("テストが通ったら `uv run ruff check --fix <作った・変えたファイル>` を 1 回回し、残った指摘を直してから終える"
               "(lint の差し戻しは 1 往復 10 秒以上かかる)。" if "python" in cfg.get("presets", []) else "")
            + "`scripts/check.sh` は自分で回さない(終了時にゲートが整形込みで必ず回し、落ちていれば差し戻す)。"
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
                return False
            if example_ids(it):  # the unit's own gate checks these at Stop (feedback); settle re-checks (authority)
                write_nofollow(wt / ".devaccel" / "expected-ids", "\n".join(example_ids(it)) + "\n")
            u = {"i": i, "k": k, "branch": br, "wt": wt, "cmd": cmd}
            if tester:
                # the tester works in its OWN worktree (the implementer can't touch its files); its tests are copied
                # into the implementer's tree when it exits, and fingerprinted at that moment
                twt = root / ".claude" / "worktrees" / (tag + "t")
                r = subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-B", f"unit/{tag}t", str(twt),
                                    start], capture_output=True, text=True)
                if r.returncode != 0:
                    print(f"tester worktree for unit {i} failed: {r.stderr.strip()[:200]}", file=sys.stderr)
                    return False
                write_nofollow(twt / ".devaccel" / "tester-session", tester["sid"] + "\n")  # its gate lets it stop
                write_nofollow(wt / ".devaccel" / "tester-pending", "1\n")  # the implementer's gate waits for this
                u["tester"] = {**tester, "wt": twt, "branch": f"unit/{tag}t"}
            units.append(u)
        return True

    for i, it in enumerate(items, 1):
        if not add_item(i, it):
            cleanup(root, units, a.keep)
            return 1

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
        t = u.get("tester")
        if t and t.get("failed"):
            return "the tester failed (no spec tests)"
        if t and any(not h or _digest(wt / f) != h for f, h in t.get("hash", {}).items()):
            return "spec tests changed by the implementer"
        if t and not any(t.get("hash", {}).values()):
            return "the tester wrote no spec tests"
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
        ids = example_ids(items[u["i"] - 1])
        if ids:  # the spec's example table is the acceptance test: every ID must be in the unit's tests
            tests = "".join(git(root, "show", f"{u['branch']}:{f}") for f in git(
                root, "diff", "--name-only", start, u["branch"]).splitlines() if TEST_FILE.search(f))
            missing = [x for x in ids if not id_present(x, tests)]
            if missing:
                return "examples not in tests: " + ", ".join(missing[:5])
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
    watch_until = time.time() + 600

    def poll_watch() -> bool:
        """Start units for items finished since the last look; False once the file is complete (or timed out)."""
        # re-validated on every read (the file is rewritten while we watch; an editor may replace it): the path
        # itself, no link on the way (O_NOFOLLOW + link checks), and what was opened is a regular file that
        # really sits in the allowed directory inside the repo
        import stat
        allowed = {(root / ".devaccel").resolve(), (root / "docs" / "design").resolve()}
        try:
            if any(p.is_symlink() for p in (a.tasks.parent, a.tasks.parent.parent)):
                return False
            fd = os.open(a.tasks, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, encoding="utf-8") as fh:
                real = Path(os.readlink(f"/proc/self/fd/{fh.fileno()}"))
                if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode) or real.parent not in allowed:
                    return False
                text = fh.read(1_000_000)
        except OSError:
            return time.time() < watch_until
        done_writing = END_MARK in text or time.time() >= watch_until
        ready = complete_items(text) if not done_writing else split_tasks(text.replace(END_MARK, ""))[1]
        for n in range(len(items), len(ready)):
            items.append(ready[n])
            before = len(units)
            if add_item(n + 1, ready[n]):
                pending.extend(units[before:])
                print(f"unit {n + 1} started (the design doc is still being written)" if not done_writing
                      else f"unit {n + 1} started", flush=True)
        return not done_writing
    limit, why = plan_jobs(len(units) if not watching else 64, a.jobs, cfg, mem_available_mb(), os.cpu_count() or 1)
    if dual:  # every item runs two sessions
        limit, why = max(1, limit // 2), why + " / 2 (tester + implementer per item)"
    print(f"running {len(units)} unit(s), {limit} at a time ({why})", flush=True)
    # a fresh session per unit: drop the parent session's markers (the anchor comes from the worktree path)
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "CLAUDE_PROJECT_DIR", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")}
    think = os.environ.get("DEVACCEL_UNIT_THINK") or str(cfg["parallel"].get("unit_think_tokens") or "")
    if think.isdigit():  # cap the units' thinking (the slowest unit spent 40-50 s thinking before its first write)
        env["MAX_THINKING_TOKENS"] = think
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=max(1, limit))  # settling (commit + own check) overlaps the units
    settling: dict = {}

    def launch(u: dict) -> None:
        u["t"] = time.time()
        u["p"] = subprocess.Popen(u["cmd"], cwd=u["wt"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  stdin=subprocess.DEVNULL, text=True, env=env, start_new_session=True)
        if u.get("tester"):
            u["tester"]["p"] = subprocess.Popen(u["tester"]["cmd"], cwd=u["tester"]["wt"], stdout=subprocess.PIPE,
                                                stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, env=env,
                                                start_new_session=True)
        running.append(u)

    def tester_done(u: dict, wait: float = 0) -> None:
        """Once the tester has exited: release the implementer's gate and fingerprint the spec tests (the
        implementer must not change them). An implementer that finishes first waits up to `wait` seconds."""
        t = u.get("tester")
        if not t or t.get("finished"):
            return
        end = time.time() + wait
        while t["p"].poll() is None and time.time() < end:
            time.sleep(0.5)
        if t["p"].poll() is None:
            if wait == 0:
                return
            try:
                os.killpg(t["p"].pid, 9)
            except OSError:
                pass
        out, _ = t["p"].communicate()
        try:
            t["cost"] = float((json.loads(out) or {}).get("total_cost_usd") or 0)
        except (ValueError, AttributeError):
            t["cost"] = 0.0
        t["finished"] = True
        t["failed"] = t["p"].returncode != 0  # killed or crashed: no trustworthy spec tests
        t["hash"] = {}
        import hashlib
        for f in t["files"]:  # copy the tester's tests over whatever is at that path in the implementer's tree
            src = _read_nofollow(t["wt"] / f)
            ok = (src is not None and bool(Path(f).parts) and ".." not in Path(f).parts and not Path(f).is_absolute()
                  and write_nofollow_deep(u["wt"], f, src))
            if not ok:  # fail closed: a spec test that could not be copied is a failed tester
                t["failed"] = True
                t["hash"][f] = ""
                continue
            t["hash"][f] = hashlib.sha256(src).hexdigest()  # what was copied, not a re-read of the tree
        write_nofollow(u["wt"] / ".devaccel" / "tester-pending", None)

    try:
        while pending or running or settling or watching:
            if watching:
                watching = poll_watch()
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
                tester_done(u)
                if u["p"].poll() is None:
                    if time.time() - u["t"] > a.unit_timeout:
                        try:
                            os.killpg(u["p"].pid, 9)
                        except OSError:
                            pass
                        u["timed_out"] = True
                    continue
                tester_done(u, wait=180)  # the spec tests must exist before the unit is settled
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
    full = []
    for u in sorted(done, key=lambda x: (x["i"], x["k"])):
        j = u["json"]
        cost += float(j.get("total_cost_usd") or 0) + float((u.get("tester") or {}).get("cost") or 0)
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
    write_nofollow(log, "\n".join(full))
    # compact on stdout (a Claude session reading this pays for every line); the reports go to the log and PR
    for u in sorted(done, key=lambda x: (x["i"], x["k"])):
        if u["status"] != "ok" and u["status"] != "superseded":
            print(f"- unit {u['i']} ({u['branch']}): {clean(u['status'])}")
    print(f"(unit reports: {log.relative_to(root)})")
    print(f"units: {len(ok)}/{len(items)} ok, {round(time.time() - t0)}s, ${cost:.3f}")
    write_nofollow(root / ".devaccel" / "batch-last.json", json.dumps(  # machine-readable (cost of the units)
        {"branch": a.branch, "units": len(items), "ok": len(ok), "secs": round(time.time() - t0),
         "cost_usd": round(cost, 4), "ts": time.time()}))

    cleanup(root, units, a.keep)
    if not ok:
        print("no unit to integrate", file=sys.stderr)
        cleanup(root, units, a.keep, branches=True)
        return 1
    notes = root / ".devaccel" / f"batch-{slug}-pr.md"  # its own file (never the session's ship.md); ship removes it
    title = a.title or f"batch: {len(ok)} units ({slug})"
    if not write_nofollow(notes, title + "\n" + "\n".join(lines) + "\n"):
        print(f"could not write {notes.relative_to(root)} (symlink?)", file=sys.stderr)
        cleanup(root, units, a.keep, branches=True)
        return 1
    if os.environ.get("DEVACCEL_TIMING"):
        print(f"[timing] units phase {round(time.time() - t0)}s", flush=True)
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("devaccel_ship.py")), "--file",
                        str(notes.relative_to(root)), "--branch", a.branch, "--units", *ok,
                        # the design doc the units worked from goes into the PR (reviewers read it, not the diff)
                        *(["--paths", str(Path(os.path.realpath(a.tasks)).relative_to(root.resolve()))]
                          if Path(os.path.realpath(a.tasks)).parent == (root / "docs" / "design").resolve() else [])],
                       cwd=root)
    cleanup(root, units, a.keep, branches=r.returncode == 0)  # integrated: the unit branches are no longer needed
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
