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
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from devaccel_common import git, load_config, match_any  # noqa: E402
from stop_gate import SKIP_RE  # noqa: E402

# "Changes can't modify their own checks": touching the verification machinery always
# needs a human, whatever project.json says (project.json itself is in this list).
ALWAYS_HUMAN = ["scripts/check.sh", ".claude/**", ".github/**", "CLAUDE.md", "AGENTS.md",
                "**/conftest.py", "conftest.py", "pytest.ini", "setup.cfg", "tox.ini",
                "pyrightconfig.json", "ruff.toml", ".ruff.toml"]
TOOL_CFG = re.compile(r"^[+-].*(\[tool\.|ruff|pyright|pytest|addopts|exclude|ignore)", re.I)

SECRET = re.compile(r"gh[opsu]_[A-Za-z0-9]{36}|github_pat_\w+|-----BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}")
NOTES_MAX = 4096

LABELS = {
    "evidence-ok": ("0e8a16", "devaccel: checks pass, app verified, low risk"),
    "needs-human": ("d93f0b", "devaccel: a human must review (see reasons in the PR body)"),
}


def run(cmd: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


DOCS = ["*.md", "**/*.md", "docs/**"]


def run_base_check(root: Path, cfg: dict, base_ref: str, workdir: Path) -> tuple[bool, list[str], str, float]:
    """Run the *base branch's* check.sh full in workdir: a branch cannot weaken the check that judges it."""
    t0 = time.time()
    base_check = git(root, "show", f"{base_ref}:scripts/check.sh") if base_ref else ""
    if not base_check:
        return False, ["== missing: scripts/check.sh"], "", 0.0
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as f:
        f.write(base_check.replace('cd "$(dirname "$0")/.."', f'cd "{workdir}"'))
    try:
        r = run(["bash", f.name, "full"], workdir, timeout=int(cfg["gate"]["timeout_sec"]) * 10)
    finally:
        Path(f.name).unlink(missing_ok=True)
    out = (r.stdout + r.stderr).splitlines()
    ok = r.returncode == 0
    stages = [ln for ln in out if re.match(r"== (ok|failed|missing):", ln)]
    return ok, stages, ("" if ok else "\n".join(out[-30:])), round(time.time() - t0, 1)


def static_triage(root: Path, cfg: dict, base: str, ref: str) -> tuple[list[str], list[str], list[str]]:
    """Diff-only reasons (no execution). Shared with devaccel_land.py, which re-applies them."""
    rng = f"{base}..{ref}"
    files = [f for f in git(root, "diff", "--name-only", rng).splitlines() if f]
    diff = git(root, "diff", "-U0", rng)
    status = git(root, "diff", "--name-status", rng).splitlines()
    scale, tg = cfg["scale"], cfg["integrity"]["test_globs"]
    risky = [f for f in files if match_any(f, scale["risky_paths"])]
    tests_deleted = [ln.split("\t", 1)[1] for ln in status
                     if ln.startswith("D") and match_any(ln.split("\t", 1)[1], tg)]
    skips = [ln[1:].strip() for ln in diff.splitlines() if SKIP_RE.match(ln)]
    machinery = [f for f in files if match_any(f, ALWAYS_HUMAN)]
    if "pyproject.toml" in files and any(
            TOOL_CFG.match(ln) for ln in git(root, "diff", "-U0", rng, "--", "pyproject.toml").splitlines()
            if not ln.startswith(("+++", "---"))):
        machinery.append("pyproject.toml(ツール設定)")
    tests_shrunk = []  # existing tests that lost lines (pure additions of new tests are fine)
    for ln in status:
        st, _, path = ln.partition("\t")
        if st.startswith("M") and match_any(path, tg):
            d = git(root, "diff", "--numstat", rng, "--", path).split()
            if d and d[1].isdigit() and int(d[1]) > 0:
                tests_shrunk.append(path)
    reasons = []
    if len(files) > scale["large_if_files_over"]:
        reasons.append(f"L 規模({len(files)} ファイル)")
    if risky:
        reasons.append("リスクのあるパス: " + ", ".join(risky[:5]))
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

    check_ok, stages, tail, check_secs = run_base_check(root, cfg, base, root)
    base_sha = (git(root, "rev-parse", "-q", "--verify", f"origin/{base_branch}").strip()
                or git(root, "rev-parse", "-q", "--verify", base_branch).strip())
    # display only: behaviour changed but no docs touched (parallel units drift apart here)
    docs_untouched = any(not match_any(f, DOCS) for f in files) and not any(match_any(f, DOCS) for f in files)

    escalations = 0
    log = root / ".claude" / "state" / "gate-log.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                escalations += json.loads(line).get("result") == "escalate"
            except ValueError:
                pass

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
    cfg = load_config(root)
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
        m = run(["gh", "pr", "merge", url, "-R", repo, "--auto", "--squash"], root)
        print("auto-merge: " + ("enabled (merges when required checks pass)" if m.returncode == 0
                                else "not enabled — " + (m.stderr.strip() or m.stdout.strip())[:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
