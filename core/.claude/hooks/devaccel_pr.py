# devaccel core — DO NOT EDIT. Tune via .claude/project.json "parallel".
"""Open a pull request whose body is the verification evidence, and triage it.

Humans review evidence, not every diff: PRs get `evidence-ok` (S/M, checks pass,
verified by running the app, nothing risky) or `needs-human` (with the reasons).
Optional auto-merge for `evidence-ok` when project.json parallel.auto_merge is true.

usage: python3 .claude/hooks/devaccel_pr.py --title T --verify-notes FILE [--dry-run]
The branch must be committed and pushed first (pushing stays under your permissions).
Re-running on a branch that already has an open PR updates its body and label.
The evidence is for the branch alone; devaccel_land.py re-verifies the merged result.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.append(str(Path(__file__).resolve().parent))  # (the script dir is already sys.path[0]; planted modules are refused by guard _pr_script_intact)
from devaccel_common import check_script_for, confined, git, load_config, match_any, trusted_root  # noqa: E402
from stop_gate import SKIP_RE  # noqa: E402

# "Changes can't modify their own checks": touching the verification machinery always
# needs a human, whatever project.json says (project.json itself is in this list).
# Any change to a tool/test configuration file needs a human (pyproject.toml always: [tool.*] edits can
# silently narrow what lint/types/tests check; keyword matching missed that).
_CFG = ["conftest.py", "pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", "setup.cfg", "tox.ini",
        "pyrightconfig.json", "ruff.toml", ".ruff.toml", ".flake8", "pyproject.toml", ".gitattributes", "noxfile.py",
        ".coveragerc", "mypy.ini", ".mypy.ini"]
ALWAYS_HUMAN = ["scripts/check.sh", ".claude/**", ".github/**", "CLAUDE.md", "AGENTS.md",
                *_CFG, *[f"**/{n}" for n in _CFG]]

SECRET = re.compile(r"gh[opsu]_[A-Za-z0-9]{36}|github_pat_\w+|-----BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}")
NOTES_MAX = 4096

LABELS = {
    "evidence-ok": ("0e8a16", "devaccel: checks pass, app verified, low risk"),
    "needs-human": ("d93f0b", "devaccel: a human must review (see reasons in the PR body)"),
}


def run(cmd: list[str], cwd: Path, timeout: int = 600, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout, env=env,
                          stdin=subprocess.DEVNULL)


# check.sh cds via ${DEVACCEL_ROOT:-...} (older ones: `cd "$(dirname "$0")/.."`); point it at the
# tree via an env var (never by pasting a path into shell text)


DOCS = ["*.md", "**/*.md", "docs/**"]


def in_agent_sandbox() -> bool:
    """Inside Claude Code's sandbox (bwrap cannot nest; processes left running die with the command). A positive
    signal only: an excluded (unsandboxed) command never gets it, and the guard admits no env prefix on the scripts."""
    return os.environ.get("SANDBOX_RUNTIME") == "1"


def need_confinement(cfg: dict) -> bool:
    """Branch code must not run with the user's full rights. Inside Claude Code's sandbox (an agent running
    ship/pr) a nested bwrap cannot start and the code is already confined, so it runs as is; anywhere else
    (devaccel_batch run by a human in a terminal) it is confined, and fails closed if bwrap can't run."""
    if not cfg["gate"].get("sandbox", True):
        return False
    # already confined only on a positive signal: ship/batch run outside the sandbox (excludedCommands), and there
    # a failed bwrap must fail closed (the confined run refuses), never fall back to running branch code as is
    return not in_agent_sandbox()


def run_base_check(root: Path, cfg: dict, base_ref: str, workdir: Path, sandbox: bool = False,
                   export_from: Path | None = None, rev: str = "HEAD",
                   mask: list[Path] | None = None) -> tuple[bool, list[str], str, float]:
    """Run the *base branch's* check.sh full in workdir: a branch cannot weaken the check that judges it."""
    t0 = time.time()
    base_check = git(root, "show", f"{base_ref}:scripts/check.sh") if base_ref else ""
    if not base_check:
        return False, ["== missing: scripts/check.sh"], "", 0.0
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as f:
        script = check_script_for(base_check)
        f.write(script or "echo '== failed: check.sh (unrecognised cd line)'; exit 1\n")
    try:
        cmd, env = ["bash", f.name, "full"], {**os.environ}
        if sandbox:  # land runs PR code on the human's machine: confine it (the PR script itself is sandboxed)
            wrapped = confined(["bash", "-c", Path(f.name).read_text(encoding="utf-8"), "check.sh", "full"], workdir,
                               mask_env_in=mask)
            if wrapped is None:
                return False, ["== failed: check.sh full (bwrap がないので隔離できない)"], "", 0.0
            cmd, env = wrapped
        env["DEVACCEL_ROOT"] = str(workdir)
        # the collection cross-check gets its OWN pristine copy of HEAD, so neither run can reshape the tree the
        # other judges (collecting runs branch code too); separate dirs also mean no clash creating .venv (a shared
        # dir made "collected: None" = a false failure in 5 of 12 PRs), so the two run side by side again
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=1)
        pending = None
        if "pytest" in base_check:
            def collect_own_copy() -> int | None:
                with tempfile.TemporaryDirectory(prefix="devaccel-collect-") as cdir:
                    # the same commit the check judges, from a checkout the caller names (never inferred from
                    # files inside the tree being judged): the branch HEAD for PRs, land's merge worktree for land
                    if not export_head(export_from or root, Path(cdir), rev):
                        return None
                    return _pytest_collected(base_check, Path(cdir), sandbox, int(cfg["gate"]["timeout_sec"]), mask)
            pending = pool.submit(collect_own_copy)
            if not sandbox:  # side by side only when both runs are confined: each then sees just its own tree
                pending.result()  # (bwrap gives every run a private /tmp). Unconfined: finish collecting first
        pool.shutdown(wait=False)
        r = run(cmd, workdir, timeout=int(cfg["gate"]["timeout_sec"]) * 10, env=env)
    except subprocess.TimeoutExpired:
        return False, ["== failed: check.sh full (timeout)"], "timeout", round(time.time() - t0, 1)
    finally:
        Path(f.name).unlink(missing_ok=True)
    out = (r.stdout + r.stderr).splitlines()
    ok = r.returncode == 0
    stages = [ln for ln in out if re.match(r"== (ok|failed|missing): [\w-]+ \(", ln)]  # no forged free text
    if ok and "pytest" in base_check and "== ok: tests (" in "\n".join(out):
        # cross-check with a separate collection: a test that prints a fake summary and os._exit(0)s,
        # or one that stops pytest early, leaves "ran" != "collected"
        ran = _pytest_ran("\n".join(out))
        collected = pending.result() if pending is not None else None
        if collected is None or (collected > 0 and ran != collected):
            ok = False
            stages.append(f"== failed: tests (ran {ran} of {collected} collected)")
    return ok, stages, ("" if ok else "\n".join(out[-30:])), round(time.time() - t0, 1)


def export_head(root: Path, dest: Path, rev: str = "HEAD") -> bool:
    """Write HEAD's tracked files into dest from git objects. Not `git archive`: that honours
    `export-ignore` in the branch's .gitattributes, which would drop a failing test from the check.
    Symlinks are written as plain files holding the target text (never followed)."""
    ls = subprocess.run(["git", "-C", str(root), "ls-tree", "-r", "-z", "--full-tree", rev],
                        capture_output=True)
    if ls.returncode != 0:
        return False
    entries = [e for e in ls.stdout.split(b"\0") if e]
    count = 0
    for e in entries:
        meta, _, path = e.partition(b"\t")
        mode, kind, sha = meta.split()
        if kind != b"blob":  # submodules are not part of the check
            continue
        blob = subprocess.run(["git", "-C", str(root), "cat-file", "blob", sha.decode()], capture_output=True)
        if blob.returncode != 0:
            return False
        rel = os.fsdecode(path)
        if any(part.lower() == ".git" for part in Path(rel).parts):  # never write git metadata into a snapshot
            return False
        target = (dest / rel).resolve()
        if dest.resolve() not in target.parents:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob.stdout)
        if mode == b"100755":
            target.chmod(0o755)
        count += 1
    return count > 0


_OUTCOMES = r"(\d+) (passed|failed|skipped|xfailed|xpassed|errors?|deselected)"


def _pytest_ran(output: str) -> int:
    """Total from pytest's final summary line ("3 passed, 1 skipped in 0.1s"); 0 if none."""
    lines = [ln for ln in output.splitlines() if re.search(_OUTCOMES + r".* in [\d.]+s", ln)]
    if not lines:
        return 0
    return sum(int(n) for n, kind in re.findall(_OUTCOMES, lines[-1]) if kind != "deselected")


def _pytest_collected(check_text: str, workdir: Path, sandbox: bool, timeout: int,
                      mask: list[Path] | None = None) -> int | None:
    m = re.search(r'^R="([^"]*)"', check_text, re.M)
    runner = m.group(1) if m else ""
    cmd = ["bash", "-c", f"{runner} pytest --collect-only -q -p no:cacheprovider"]
    env = {**os.environ}
    if sandbox:
        wrapped = confined(cmd, workdir, mask_env_in=mask)
        if wrapped is None:
            return None
        cmd, env = wrapped
    try:
        r = run(cmd, workdir, timeout=timeout * 2, env=env)
    except subprocess.TimeoutExpired:
        return None
    text = r.stdout + r.stderr
    if r.returncode == 5 or "no tests collected" in text:
        return 0
    # "2653/33653 tests collected (31000 deselected)": the project's own -m/-k selection (addopts) counts
    m2 = re.search(r"(?:(\d+)/)?(\d+) tests? collected", text)
    if r.returncode != 0 or not m2:
        return None
    return int(m2.group(1) or m2.group(2))


def static_triage(root: Path, cfg: dict, base: str, ref: str,
                  units: int = 1) -> tuple[list[str], list[str], list[str]]:
    """Diff-only reasons (no execution). Shared with devaccel_land.py, which re-applies them."""
    rng = f"{base}..{ref}"
    files = [f for f in git(root, "diff", "--no-renames", "--name-only", rng).splitlines() if f]
    # --text/--no-textconv/--no-ext-diff: a branch's .gitattributes ("-diff") must not hide test edits
    diff = git(root, "diff", "--no-renames", "--text", "--no-textconv", "--no-ext-diff", "-U0", rng)
    status = git(root, "diff", "--no-renames", "--name-status", rng).splitlines()
    scale, tg = cfg["scale"], cfg["integrity"]["test_globs"]
    risky = [f for f in files if match_any(f, scale["risky_paths"])]
    tests_deleted = [ln.split("\t", 1)[1] for ln in status
                     if ln.startswith("D") and match_any(ln.split("\t", 1)[1], tg)]
    skips = [ln[1:].strip() for ln in diff.splitlines() if SKIP_RE.match(ln)]
    machinery = [f for f in files if match_any(f, ALWAYS_HUMAN)]
    odd = [ln.partition("\t")[2] for ln in status if ln[:1] not in ("A", "M", "D")]  # type changes etc.
    tests_shrunk = []  # existing tests that lost lines (pure additions of new tests are fine)
    for ln in status:
        st, _, path = ln.partition("\t")
        if st.startswith("M") and match_any(path, tg):
            d = git(root, "diff", "--no-renames", "--text", "--numstat", rng, "--", path).split()
            if not d or not d[1].isdigit() or int(d[1]) > 0:  # "-" (binary) counts as shrunk
                tests_shrunk.append(path)
    reasons = []
    # same threshold for integrated batches: more files = a human reads it (no relaxation per unit)
    if len(files) > int(scale["large_if_files_over"]):
        reasons.append(f"L 規模({len(files)} ファイル)")
    if risky:
        reasons.append("リスクのあるパス: " + ", ".join(risky[:5]))
    if odd:
        reasons.append("種類の変わったファイル(シンボリックリンク等): " + ", ".join(odd[:5]))
    if machinery:
        reasons.append("検証基盤の変更: " + ", ".join(machinery[:5]))
    if tests_shrunk:
        reasons.append("既存テストの行削除: " + ", ".join(tests_shrunk[:5]))
    if tests_deleted:
        reasons.append("テスト削除: " + ", ".join(tests_deleted[:5]))
    if skips:
        reasons.append(f"skip/xfail 追加 {len(skips)} 件")
    return files, reasons, risky


def collect(root: Path, cfg: dict, base_branch: str, notes: str, units: int = 1, fetched: bool = False,
            rev: str = "HEAD", branch: str = "", base_ref: str = "", state_root: Path | None = None) -> dict:
    """base_ref/state_root: finalize judges from a private repository fetched from GitHub (root), with the base
    at base_ref; the project's own files (gate log, .env to mask) are under state_root."""
    head = branch or git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    fetched = fetched or bool(base_ref)
    # best effort: judge against the latest base. The fetch overlaps the snapshot export (which needs only HEAD);
    # skipped when the caller fetched the base seconds ago (ship creating the work branch: ~1.3 s each)
    fetch = subprocess.Popen(["true"] if fetched else
                             ["git", "-C", str(root), "-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null",
                              "fetch", "-q", "origin", base_branch], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    snap_dir = tempfile.TemporaryDirectory(prefix="devaccel-pr-")
    exported = export_head(root, Path(snap_dir.name), rev)
    try:
        fetch.wait(timeout=60)
    except subprocess.TimeoutExpired:
        fetch.kill()
    base = (git(root, "merge-base", rev, base_ref).strip() if base_ref else
            git(root, "merge-base", rev, f"origin/{base_branch}").strip()
            or git(root, "merge-base", rev, base_branch).strip())
    files, static, risky = static_triage(root, cfg, base, rev, units)
    stat = git(root, "diff", "--shortstat", f"{base}..{rev}").strip()
    designs = [f for f in files if f.startswith("docs/design/") and f.endswith(".md") and "TEMPLATE" not in f]
    acs: list[str] = []
    for d in designs:
        text = git(root, "show", f"{rev}:{d}")  # the judged commit's copy, not the (still edited) working tree
        acs += [ln.strip() for ln in text.splitlines() if re.match(r"\s*- \[[ xX]\] ", ln)]

    # judge the commit, not the working tree: untracked/ignored files (a stray conftest.py) must not count
    with snap_dir as snap:
        if exported:
            check_ok, stages, tail, check_secs = run_base_check(
                root, cfg, base, Path(snap), sandbox=need_confinement(cfg), rev=rev,
                mask=[trusted_root({"cwd": str(state_root or root)})])
        else:  # never judge an empty or partial tree as passing
            check_ok, stages, tail, check_secs = False, ["== failed: snapshot (HEAD を取り出せない)"], "", 0.0
    base_sha = (git(root, "rev-parse", "-q", "--verify", base_ref).strip() if base_ref else
                git(root, "rev-parse", "-q", "--verify", f"origin/{base_branch}").strip()
                or git(root, "rev-parse", "-q", "--verify", base_branch).strip())
    # display only: behaviour changed but no docs touched (parallel units drift apart here)
    docs_untouched = any(not match_any(f, DOCS) for f in files) and not any(match_any(f, DOCS) for f in files)

    # the gate logs in the main checkout (worktrees are deleted): count this branch and the unit branches it
    # integrated (merge subjects "integrate <branch>"; a forged subject can only add reasons, never remove them).
    # Records without a branch (e.g. a broken unit worktree) belong to no PR.
    mine = {head} | set(re.findall(r"^integrate (\S+)$", git(root, "log", "--merges", "--format=%s",
                                                             f"{base}..{rev}") if base else "", re.M))
    escalations = 0
    log = trusted_root({"cwd": str(state_root or root)}) / ".claude" / "state" / "gate-log.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            escalations += e.get("result") == "escalate" and e.get("branch") in mine

    reasons = []
    if not check_ok:
        reasons.append("`check.sh full` が失敗")
    if not notes.strip():
        reasons.append("実動作確認(verify-app)の記録が無い")
    reasons += static
    if escalations:
        reasons.append(f"ゲートが人への判断依頼を {escalations} 回出した")
    if acs and any("[ ]" in a for a in acs):
        reasons.append("未チェックの受け入れ条件がある")
    return {
        "head": head, "base": base_branch, "files": files, "stat": stat, "risky": risky,
        "acs": acs, "designs": designs, "check_ok": check_ok, "stages": stages, "tail": tail,
        "check_secs": check_secs, "reasons": reasons, "base_sha": base_sha,
        "head_sha": git(root, "rev-parse", rev).strip(), "docs_untouched": docs_untouched,
        "label": "needs-human" if reasons else "evidence-ok",
    }


MARK = "devaccel:evidence"


def render(ev: dict, notes: str) -> str:
    ok = "✅" if ev["check_ok"] else "❌"
    notes = notes.replace(MARK, "devaccel-evidence")  # only the generated trailer may carry the marker
    lines = [
        f"**devaccel triage: `{ev['label']}`**" + ("" if not ev["reasons"] else " — " + " / ".join(ev["reasons"])),
        "",
        "## 証拠",
        f"- {ok} `scripts/check.sh full`({ev['check_secs']}s): " + ", ".join(s[3:] for s in ev["stages"]),
        f"- 変更: {ev['stat'] or 'なし'}",
    ]
    if ev.get("docs_untouched"):
        lines.append("- docs 更新なし(README 等の追随が要らないか確認)")
    if ev["designs"]:
        lines.append("- 設計書: " + ", ".join(f"`{d}`" for d in ev["designs"]))
    if ev["acs"]:
        lines += ["", "### 受け入れ条件", *(a.replace(MARK, "devaccel-evidence") for a in ev["acs"])]
    lines += ["", "### 実動作確認(verify-app)", notes.strip() or "_記録なし_"]
    if ev["tail"]:
        lines += ["", "<details><summary>check.sh full の失敗出力</summary>", "", "```", ev["tail"], "```", "</details>"]
    lines += ["", "---", "_Generated by devaccel. Review the evidence; read the diff when labeled `needs-human`. "
              "Merge with `devaccel_land.py --merge` so the combined result is re-verified._",
              f"<!-- {MARK} base={ev.get('base_sha', '')} head={ev.get('head_sha', '')} -->"]
    return "\n".join(lines) + "\n"


def read_notes(path: str, root: Path) -> str:
    """Notes go into a public-ish PR body: only small files from the repo or temp dir, no secrets."""
    if not path:
        return ""
    p = Path(path).resolve()
    allowed = [root.resolve(), Path(tempfile.gettempdir()).resolve()]
    if not any(p == a or a in p.parents for a in allowed):
        raise SystemExit(f"--verify-notes must be inside the repo or {tempfile.gettempdir()}")
    if not p.is_file():
        raise SystemExit(f"--verify-notes: {path} not found (write it first)")
    if p.name.startswith(".env") or p.stat().st_size > NOTES_MAX:
        raise SystemExit(f"--verify-notes: refused ({p.name}, max {NOTES_MAX} bytes)")
    text = p.read_text(encoding="utf-8")
    if SECRET.search(text):
        raise SystemExit("--verify-notes looks like it contains a credential; refused")
    return text


def github_repo(root: Path) -> str:
    url = git(root, "config", "--get", "remote.origin.url").strip()  # as configured (gh -R slug)
    m = re.match(r"^(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--verify-notes", default="", help="file with what was run and observed")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--finalize", metavar="SHA", default="", help="(ship) judge this pushed commit and ready the draft")
    ap.add_argument("--branch", default="", help="(with --finalize) the work branch the commit was pushed to")
    a = ap.parse_args()
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or Path.cwd())
    if a.finalize:
        if not re.fullmatch(r"[0-9a-f]{40}", a.finalize) or not re.fullmatch(r"\w[\w./-]*", a.branch) or ".." in a.branch:
            print("--finalize needs a full commit sha and --branch <work branch>", file=sys.stderr)
            return 2
        notes = read_notes(a.verify_notes, root)
        if a.verify_notes and Path(a.verify_notes).resolve().parent == Path(tempfile.gettempdir()).resolve():
            Path(a.verify_notes).unlink(missing_ok=True)  # ship's private copy
        return finalize(root, a.title, notes, a.finalize, a.branch)
    return open_pr(root, a.title, read_notes(a.verify_notes, root), a.dry_run)


PENDING = ("**devaccel: 証拠を作成中** — base の `check.sh full` をこの commit の取り出しで実行しています。"
           "終わるとこの本文とラベルが置き換わり、下書きが解除されます(下書きのあいだはマージできません)。\n")


def open_draft(root: Path, title: str, head: str, sha: str) -> str:
    """ship's fast path: the PR exists (as a draft, unmergeable) before its evidence; finalize fills it in.
    An open PR for the branch goes back to draft with the pending body. Returns the URL ("" on failure)."""
    repo = github_repo(root)
    if not repo:
        return ""
    cur = run(["gh", "pr", "view", head, "-R", repo, "--json", "url,state,isCrossRepository,baseRefName"], root)
    existing = json.loads(cur.stdout) if cur.returncode == 0 and cur.stdout.strip() else {}
    base = load_config(trusted_root({"cwd": str(root)}))["scale"]["base_branch"]
    if existing.get("state") == "OPEN":
        if existing.get("isCrossRepository") or existing.get("baseRefName") != base:
            return ""
        url = existing["url"]
        # back to draft before anything else: if that fails (no drafts on this plan), the synchronous path runs
        if run(["gh", "pr", "ready", url, "-R", repo, "--undo"], root).returncode != 0:
            return ""
        r = run(["gh", "pr", "edit", url, "-R", repo, "--remove-label", "evidence-ok",
                 "--body", PENDING + f"\n<!-- pending head={sha} -->\n"], root)
        return url if r.returncode == 0 else ""
    r = run(["gh", "pr", "create", "-R", repo, "--draft", "--base", base, "--head", head, "--title", title,
             "--body", PENDING + f"\n<!-- pending head={sha} -->\n"], root)
    return r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ""


def finalize(root: Path, title: str, notes: str, sha: str, branch: str) -> int:
    """Background step after ship's draft PR (started by the finalize hook, outside the sandbox). The evidence is
    built from a private repository fetched from GitHub, not from the project's .git (writable from the sandbox:
    `git replace`, swapped objects or a forged origin/<base> would make a failing commit look green). Only the
    draft ship opened for exactly this commit is filled in; it is readied only while its head is still `sha`."""
    import shutil
    project = trusted_root({"cwd": str(root)})
    cfg = load_config(project)
    base_branch = cfg["scale"]["base_branch"]
    repo = github_repo(project)
    if not repo or branch in {"main", "master", base_branch}:
        print("finalize: no GitHub origin or a protected branch", file=sys.stderr)
        return 2
    fields = "url,state,isDraft,headRefOid,baseRefName,isCrossRepository,labels,body"

    def view() -> dict:
        v = run(["gh", "pr", "view", branch, "-R", repo, "--json", fields], project)
        return json.loads(v.stdout) if v.returncode == 0 and v.stdout.strip() else {}

    pr = view()
    if not (pr.get("state") == "OPEN" and pr.get("isDraft") and pr.get("headRefOid") == sha
            and pr.get("baseRefName") == base_branch and not pr.get("isCrossRepository")
            and f"<!-- pending head={sha} -->" in (pr.get("body") or "")):
        print("finalize: no draft PR pending for this commit (a newer ship owns it, or none)", file=sys.stderr)
        return 2
    url = pr["url"]
    state = project / ".claude" / "state"  # not writable from the sandbox
    if state.is_symlink():
        return 2
    (state / "judge").mkdir(parents=True, exist_ok=True)
    judge = Path(tempfile.mkdtemp(prefix="j-", dir=state / "judge"))
    try:
        jgit = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=", "-C", str(judge)]
        run([*jgit[:-2], "init", "-q", "--bare", str(judge)], project)
        f = run([*jgit, "-c", "transfer.fsckObjects=true", "fetch", "-q", "--no-tags", f"https://github.com/{repo}.git",
                 f"+refs/heads/{branch}:refs/judge/head", f"+refs/heads/{base_branch}:refs/judge/base"], project,
                timeout=600)
        if f.returncode != 0 or git(judge, "rev-parse", "-q", "--verify", "refs/judge/head").strip() != sha:
            print("finalize: could not fetch exactly this commit from GitHub (a newer push?): "
                  + (f.stderr.strip()[-200:]), file=sys.stderr)
            return 2
        ev = collect(judge, cfg, base_branch, notes, 1, True, rev=sha, branch=branch, base_ref="refs/judge/base",
                     state_root=project)
        body = render(ev, notes)
        if SECRET.search(body):
            print("PR body looks like it contains a credential (check output / notes); refused", file=sys.stderr)
            return 2
        labels = {x.get("name") for x in pr.get("labels") or []}
        up_to_date = bool(ev["base_sha"]) and git(judge, "merge-base", sha, ev["base_sha"]).strip() == ev["base_sha"]
        if ev["label"] == "evidence-ok" and "needs-human" in labels and not up_to_date:
            ev["label"], ev["reasons"] = "needs-human", ev["reasons"] + [
                f"base より遅れている(`git merge origin/{ev['base']}` してから再実行)"]
            body = render(ev, notes)
    finally:
        shutil.rmtree(judge, ignore_errors=True)
    for name, (color, desc) in LABELS.items():
        run(["gh", "label", "create", name, "-R", repo, "--color", color, "--description", desc], project)

    def still_ours() -> bool:
        now = view()
        return now.get("state") == "OPEN" and now.get("headRefOid") == sha

    def disown(why: str) -> int:  # this evidence is not about the head: unmergeable, or at least not "ok"
        for _ in range(3):
            if run(["gh", "pr", "ready", url, "-R", repo, "--undo"], project).returncode == 0:
                break
        run(["gh", "pr", "edit", url, "-R", repo, "--remove-label", "evidence-ok", "--add-label", "needs-human"],
            project)
        print(why, file=sys.stderr)
        return 1
    if not still_ours():  # a newer ship took the PR over meanwhile: its own finalize writes the body
        print("finalize: the PR head moved; leaving it to the newer ship", file=sys.stderr)
        return 1
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as bf:
        bf.write(body)
    try:
        other = "needs-human" if ev["label"] == "evidence-ok" else "evidence-ok"
        r = run(["gh", "pr", "edit", url, "-R", repo, "--body-file", bf.name, "--add-label", ev["label"],
                 "--remove-label", other], project)
    finally:
        Path(bf.name).unlink(missing_ok=True)
    if r.returncode != 0:
        print(r.stderr.strip() or r.stdout.strip(), file=sys.stderr)
        return 1
    # gh has no head-match for ready: check right before and right after it
    if not still_ours():
        return disown("the PR head moved during finalize: left as a draft (the newer ship judges it)")
    rd = run(["gh", "pr", "ready", url, "-R", repo], project)
    if rd.returncode != 0:
        print("could not mark the PR ready: " + (rd.stderr.strip() or rd.stdout.strip())[:200], file=sys.stderr)
        return 1
    if not still_ours():
        return disown("the PR head moved while readying: back to draft (the newer ship judges it)")
    print(f"{url}  [{ev['label']}]" + (f" reasons: {' / '.join(ev['reasons'])}" if ev["reasons"] else ""))
    return 0


def stamp(label: str, t0: float) -> float:
    """Phase timing to stderr when DEVACCEL_TIMING is set (benchmarks)."""
    now = time.time()
    if os.environ.get("DEVACCEL_TIMING"):
        print(f"[timing] {label} {now - t0:.1f}s", file=sys.stderr, flush=True)
    return now


def open_pr(root: Path, title: str, notes: str, dry_run: bool, units: int = 1, before_publish=None,
            fetched: bool = False) -> int:
    """Build the evidence for HEAD, triage it, and create/update the PR (shared with devaccel_ship.py)."""
    cfg = load_config(trusted_root({"cwd": str(root)}))  # never the unit's own project.json
    par = cfg.get("parallel", {})
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        print("uncommitted changes: commit first", file=sys.stderr)
        return 2
    head = git(root, "symbolic-ref", "--short", "-q", "HEAD").strip()
    protected = {"main", "master", cfg["scale"]["base_branch"]}
    if not head or head in protected:
        print(f"refusing to open a PR from {head or 'detached HEAD'}: use a work branch", file=sys.stderr)
        return 2
    t = time.time()
    # GitHub lookups that don't depend on the evidence run while it is computed (they were ~5 s in series)
    early: dict = {}
    head0 = git(root, "symbolic-ref", "--short", "-q", "HEAD").strip()
    repo0 = github_repo(root) if not dry_run else ""
    if repo0 and head0:
        bg = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL, cwd=root)
        early["labels"] = [subprocess.Popen(["gh", "label", "create", n, "-R", repo0, "--color", c, "--description",
                                             d], **bg) for n, (c, d) in LABELS.items()]
        early["view"] = subprocess.Popen(["gh", "pr", "view", head0, "-R", repo0, "--json",
                                          "url,state,headRefOid,baseRefName,isCrossRepository,labels"], **bg)
    ev = collect(root, cfg, cfg["scale"]["base_branch"], notes, units, fetched)
    t = stamp("evidence (snapshot + base check + triage)", t)
    body = render(ev, notes)
    if SECRET.search(body):  # check output and acceptance criteria end up in the body too
        print("PR body looks like it contains a credential (check output / notes); refused", file=sys.stderr)
        return 2
    if dry_run:
        print(body)
        print(json.dumps({"label": ev["label"], "reasons": ev["reasons"]}, ensure_ascii=False))
        return 0

    if before_publish is not None:  # e.g. ship's push, run in parallel with the evidence
        rc = before_publish()
        t = stamp("waited for push", t)
        if rc != 0:
            return rc
    repo = github_repo(root)
    if not repo:
        print("origin is not a github.com repository", file=sys.stderr)
        return 2
    remote_head = git(root, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{head}").strip()
    if remote_head != git(root, "rev-parse", "HEAD").strip():
        print("push first: git push origin HEAD", file=sys.stderr)
        return 2
    if early and repo == repo0 and ev["head"] == head0:
        for lp in early["labels"]:
            lp.communicate()
        vout, _ = early["view"].communicate()
        cur_rc = early["view"].returncode
    else:
        for name, (color, desc) in LABELS.items():
            run(["gh", "label", "create", name, "-R", repo, "--color", color, "--description", desc], root)
        cur = run(["gh", "pr", "view", ev["head"], "-R", repo, "--json",
                   "url,state,headRefOid,baseRefName,isCrossRepository,labels"], root)
        vout, cur_rc = cur.stdout, cur.returncode
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
    try:
        existing = json.loads(vout) if cur_rc == 0 and vout.strip() else {}
        if early and existing.get("state") == "OPEN" and existing.get("headRefOid") != ev["head_sha"]:
            # looked up before our push finished: ask again now that it has
            cur = run(["gh", "pr", "view", ev["head"], "-R", repo, "--json",
                       "url,state,headRefOid,baseRefName,isCrossRepository,labels"], root)
            existing = json.loads(cur.stdout) if cur.returncode == 0 and cur.stdout.strip() else {}
        if existing.get("state") == "OPEN":  # re-run after fixing / merging base: refresh evidence and label
            if (existing.get("isCrossRepository") or existing.get("baseRefName") != ev["base"]
                    or existing.get("headRefOid") != ev["head_sha"]):
                print(f"open PR {existing.get('url')} does not match this branch (head/base/repo); not updating",
                      file=sys.stderr)
                return 2
            labels = {x.get("name") for x in existing.get("labels") or []}
            up_to_date = bool(ev["base_sha"]) and git(root, "merge-base", "HEAD", ev["base_sha"]).strip() == ev["base_sha"]
            if ev["label"] == "evidence-ok" and "needs-human" in labels and not up_to_date:
                # a downgrade (e.g. by land) is lifted only after the branch has merged the latest base
                ev["label"], ev["reasons"] = "needs-human", ev["reasons"] + [
                    f"base より遅れている(`git merge origin/{ev['base']}` してから再実行)"]
                body = render(ev, notes)
                Path(f.name).write_text(body, encoding="utf-8")
            other = "needs-human" if ev["label"] == "evidence-ok" else "evidence-ok"
            r = run(["gh", "pr", "edit", existing["url"], "-R", repo, "--body-file", f.name,
                     "--add-label", ev["label"], "--remove-label", other], root)
            url = existing["url"]
        else:
            r = run(["gh", "pr", "create", "-R", repo, "--base", ev["base"], "--head", ev["head"], "--title", title,
                     "--body-file", f.name, "--label", ev["label"]], root)
            url = r.stdout.strip().splitlines()[-1] if r.returncode == 0 else ""
    finally:
        Path(f.name).unlink(missing_ok=True)
    stamp("labels + PR create/update", t)
    if r.returncode != 0:
        print(r.stderr.strip() or r.stdout.strip(), file=sys.stderr)
        return 1
    print(f"{url}  [{ev['label']}]" + (f" reasons: {' / '.join(ev['reasons'])}" if ev["reasons"] else ""))
    if ev["label"] == "evidence-ok" and par.get("auto_merge") and units <= 1:  # integrated batches: human merges
        # auto-merge only behind branch protection with a required status check (CI = check.sh full)
        prot = run(["gh", "api", f"repos/{repo}/branches/{ev['base']}/protection/required_status_checks"], root)
        if prot.returncode != 0 or '"contexts":[]' in prot.stdout.replace(" ", ""):
            print("auto-merge: skipped — base branch has no required status checks (set branch protection first)")
            return 0
        m = run(["gh", "pr", "merge", url, "-R", repo, "--auto", "--squash", "--match-head-commit", ev["head_sha"]], root)
        print("auto-merge: " + ("enabled (merges when required checks pass)" if m.returncode == 0
                                else "not enabled — " + (m.stderr.strip() or m.stdout.strip())[:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
