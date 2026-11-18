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
_CFG = ["conftest.py", "pytest.ini", ".pytest.ini", "setup.cfg", "tox.ini", "pyrightconfig.json", "ruff.toml",
        ".ruff.toml", "pyproject.toml", ".gitattributes", "noxfile.py", ".coveragerc", "mypy.ini", ".mypy.ini"]
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


def run_base_check(root: Path, cfg: dict, base_ref: str, workdir: Path,
                   sandbox: bool = False) -> tuple[bool, list[str], str, float]:
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
            wrapped = confined(["bash", "-c", Path(f.name).read_text(encoding="utf-8"), "check.sh", "full"], workdir)
            if wrapped is None:
                return False, ["== failed: check.sh full (bwrap がないので隔離できない)"], "", 0.0
            cmd, env = wrapped
        env["DEVACCEL_ROOT"] = str(workdir)
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
        collected = _pytest_collected(base_check, workdir, sandbox, int(cfg["gate"]["timeout_sec"]))
        if collected is None or (collected > 0 and ran != collected):
            ok = False
            stages.append(f"== failed: tests (ran {ran} of {collected} collected)")
    return ok, stages, ("" if ok else "\n".join(out[-30:])), round(time.time() - t0, 1)


def export_head(root: Path, dest: Path) -> bool:
    """Write HEAD's tracked files into dest from git objects. Not `git archive`: that honours
    `export-ignore` in the branch's .gitattributes, which would drop a failing test from the check.
    Symlinks are written as plain files holding the target text (never followed)."""
    ls = subprocess.run(["git", "-C", str(root), "ls-tree", "-r", "-z", "--full-tree", "HEAD"],
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


def _pytest_collected(check_text: str, workdir: Path, sandbox: bool, timeout: int) -> int | None:
    m = re.search(r'^R="([^"]*)"', check_text, re.M)
    runner = m.group(1) if m else ""
    cmd = ["bash", "-c", f"{runner} pytest --collect-only -q -p no:cacheprovider"]
    env = {**os.environ}
    if sandbox:
        wrapped = confined(cmd, workdir)
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
    m2 = re.search(r"(\d+) tests? collected", text)
    if r.returncode != 0 or not m2:
        return None
    return int(m2.group(1))


def static_triage(root: Path, cfg: dict, base: str, ref: str) -> tuple[list[str], list[str], list[str]]:
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
    if len(files) > scale["large_if_files_over"]:
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


def collect(root: Path, cfg: dict, base_branch: str, notes: str) -> dict:
    head = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    git(root, "fetch", "-q", "origin", base_branch)  # best effort: judge against the latest base
    base = (git(root, "merge-base", "HEAD", f"origin/{base_branch}").strip()
            or git(root, "merge-base", "HEAD", base_branch).strip())
    files, static, risky = static_triage(root, cfg, base, "HEAD")
    stat = git(root, "diff", "--shortstat", f"{base}..HEAD").strip()
    designs = [f for f in files if f.startswith("docs/design/") and f.endswith(".md") and "TEMPLATE" not in f]
    acs: list[str] = []
    for d in designs:
        p = root / d
        if p.exists():
            acs += [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                    if re.match(r"\s*- \[[ xX]\] ", ln)]

    # judge the commit, not the working tree: untracked/ignored files (a stray conftest.py) must not count
    with tempfile.TemporaryDirectory(prefix="devaccel-pr-") as snap:
        if export_head(root, Path(snap)):
            check_ok, stages, tail, check_secs = run_base_check(root, cfg, base, Path(snap))
        else:  # never judge an empty or partial tree as passing
            check_ok, stages, tail, check_secs = False, ["== failed: snapshot (HEAD を取り出せない)"], "", 0.0
    base_sha = (git(root, "rev-parse", "-q", "--verify", f"origin/{base_branch}").strip()
                or git(root, "rev-parse", "-q", "--verify", base_branch).strip())
    # display only: behaviour changed but no docs touched (parallel units drift apart here)
    docs_untouched = any(not match_any(f, DOCS) for f in files) and not any(match_any(f, DOCS) for f in files)

    escalations = 0  # the gate logs in the main checkout (worktrees are deleted); count this branch only
    log = trusted_root({"cwd": str(root)}) / ".claude" / "state" / "gate-log.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            escalations += e.get("result") == "escalate" and e.get("branch", head) == head

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
        "head_sha": git(root, "rev-parse", "HEAD").strip(), "docs_untouched": docs_untouched,
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
    a = ap.parse_args()

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip() or Path.cwd())
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
    notes = read_notes(a.verify_notes, root)
    ev = collect(root, cfg, cfg["scale"]["base_branch"], notes)
    body = render(ev, notes)
    if SECRET.search(body):  # check output and acceptance criteria end up in the body too
        print("PR body looks like it contains a credential (check output / notes); refused", file=sys.stderr)
        return 2
    if a.dry_run:
        print(body)
        print(json.dumps({"label": ev["label"], "reasons": ev["reasons"]}, ensure_ascii=False))
        return 0

    repo = github_repo(root)
    if not repo:
        print("origin is not a github.com repository", file=sys.stderr)
        return 2
    remote_head = git(root, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{head}").strip()
    if remote_head != git(root, "rev-parse", "HEAD").strip():
        print("push first: git push origin HEAD", file=sys.stderr)
        return 2
    for name, (color, desc) in LABELS.items():
        run(["gh", "label", "create", name, "-R", repo, "--color", color, "--description", desc], root)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
    try:
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
            r = run(["gh", "pr", "create", "-R", repo, "--base", ev["base"], "--head", ev["head"], "--title", a.title,
                     "--body-file", f.name, "--label", ev["label"]], root)
            url = r.stdout.strip().splitlines()[-1] if r.returncode == 0 else ""
    finally:
        Path(f.name).unlink(missing_ok=True)
    if r.returncode != 0:
        print(r.stderr.strip() or r.stdout.strip(), file=sys.stderr)
        return 1
    print(f"{url}  [{ev['label']}]" + (f" reasons: {' / '.join(ev['reasons'])}" if ev["reasons"] else ""))
    if ev["label"] == "evidence-ok" and par.get("auto_merge"):
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
