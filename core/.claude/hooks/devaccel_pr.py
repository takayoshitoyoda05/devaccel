# devaccel core — DO NOT EDIT. Tune via .claude/project.json "parallel".
"""Open a pull request whose body is the verification evidence, and triage it.

Humans review evidence, not every diff: PRs get `evidence-ok` (S/M, checks pass,
verified by running the app, nothing risky) or `needs-human` (with the reasons).
Optional auto-merge for `evidence-ok` when project.json parallel.auto_merge is true.

usage: python3 .claude/hooks/devaccel_pr.py --title T --verify-notes FILE [--dry-run]
The branch must be committed and pushed first (pushing stays under your permissions).
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

LABELS = {
    "evidence-ok": ("0e8a16", "devaccel: checks pass, app verified, low risk"),
    "needs-human": ("d93f0b", "devaccel: a human must review (see reasons in the PR body)"),
}


def run(cmd: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def collect(root: Path, cfg: dict, base_branch: str, notes: str) -> dict:
    head = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    base = (git(root, "merge-base", "HEAD", f"origin/{base_branch}").strip()
            or git(root, "merge-base", "HEAD", base_branch).strip())
    files = [f for f in git(root, "diff", "--name-only", f"{base}..HEAD").splitlines() if f]
    stat = git(root, "diff", "--shortstat", f"{base}..HEAD").strip()
    diff = git(root, "diff", "-U0", f"{base}..HEAD")
    status = git(root, "diff", "--name-status", f"{base}..HEAD").splitlines()

    scale = cfg["scale"]
    risky = [f for f in files if match_any(f, scale["risky_paths"])]
    large = len(files) > scale["large_if_files_over"]
    tests_deleted = [ln.split("\t", 1)[1] for ln in status
                     if ln.startswith("D") and match_any(ln.split("\t", 1)[1], cfg["integrity"]["test_globs"])]
    skips = [ln[1:].strip() for ln in diff.splitlines() if SKIP_RE.match(ln)]
    machinery = [f for f in files if match_any(f, ALWAYS_HUMAN)]
    if "pyproject.toml" in files and any(
            TOOL_CFG.match(ln) for ln in git(root, "diff", "-U0", f"{base}..HEAD", "--", "pyproject.toml").splitlines()
            if not ln.startswith(("+++", "---"))):
        machinery.append("pyproject.toml(ツール設定)")
    # existing tests that lost lines (pure additions of new tests are fine)
    tests_shrunk = []
    for ln in status:
        st, _, path = ln.partition("\t")
        if st.startswith("M") and match_any(path, cfg["integrity"]["test_globs"]):
            d = git(root, "diff", "--numstat", f"{base}..HEAD", "--", path).split()
            if d and d[1].isdigit() and int(d[1]) > 0:
                tests_shrunk.append(path)
    designs = [f for f in files if f.startswith("docs/design/") and f.endswith(".md") and "TEMPLATE" not in f]
    acs: list[str] = []
    for d in designs:
        p = root / d
        if p.exists():
            acs += [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                    if re.match(r"\s*- \[[ xX]\] ", ln)]

    t0 = time.time()
    # run the *base branch's* check.sh: a branch cannot weaken the check that judges it
    base_check = git(root, "show", f"{base}:scripts/check.sh") if base else ""
    if base_check:
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as f:
            f.write(base_check.replace('cd "$(dirname "$0")/.."', f'cd "{root}"'))
        r = run(["bash", f.name, "full"], root, timeout=int(cfg["gate"]["timeout_sec"]) * 10)
        Path(f.name).unlink(missing_ok=True)
        check_ok = r.returncode == 0
        stages = [ln for ln in (r.stdout + r.stderr).splitlines() if re.match(r"== (ok|failed|missing):", ln)]
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-30:]) if not check_ok else ""
    else:
        check_ok, stages, tail = False, ["== missing: scripts/check.sh"], ""
    check_secs = round(time.time() - t0, 1)

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
    if large:
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
    if escalations:
        reasons.append(f"ゲートが人への判断依頼を {escalations} 回出した")
    if acs and any("[ ]" in a for a in acs):
        reasons.append("未チェックの受け入れ条件がある")
    return {
        "head": head, "base": base_branch, "files": files, "stat": stat, "risky": risky,
        "acs": acs, "designs": designs, "check_ok": check_ok, "stages": stages, "tail": tail,
        "check_secs": check_secs, "reasons": reasons,
        "label": "needs-human" if reasons else "evidence-ok",
    }


def render(ev: dict, notes: str) -> str:
    ok = "✅" if ev["check_ok"] else "❌"
    lines = [
        f"**devaccel triage: `{ev['label']}`**" + ("" if not ev["reasons"] else " — " + " / ".join(ev["reasons"])),
        "",
        "## 証拠",
        f"- {ok} `scripts/check.sh full`({ev['check_secs']}s): " + ", ".join(s[3:] for s in ev["stages"]),
        f"- 変更: {ev['stat'] or 'なし'}",
    ]
    if ev["designs"]:
        lines.append("- 設計書: " + ", ".join(f"`{d}`" for d in ev["designs"]))
    if ev["acs"]:
        lines += ["", "### 受け入れ条件", *ev["acs"]]
    lines += ["", "### 実動作確認(verify-app)", notes.strip() or "_記録なし_"]
    if ev["tail"]:
        lines += ["", "<details><summary>check.sh full の失敗出力</summary>", "", "```", ev["tail"], "```", "</details>"]
    lines += ["", "---", "_Generated by devaccel. Review the evidence; read the diff when labeled `needs-human`._"]
    return "\n".join(lines) + "\n"


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
    notes = Path(a.verify_notes).read_text(encoding="utf-8") if a.verify_notes else ""
    ev = collect(root, cfg, cfg["scale"]["base_branch"], notes)
    body = render(ev, notes)
    if a.dry_run:
        print(body)
        print(json.dumps({"label": ev["label"], "reasons": ev["reasons"]}, ensure_ascii=False))
        return 0

    for name, (color, desc) in LABELS.items():
        run(["gh", "label", "create", name, "--color", color, "--description", desc], root)  # exists -> ignored
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
    r = run(["gh", "pr", "create", "--base", ev["base"], "--head", ev["head"], "--title", a.title,
             "--body-file", f.name, "--label", ev["label"]], root)
    Path(f.name).unlink(missing_ok=True)
    if r.returncode != 0:
        print(r.stderr.strip() or r.stdout.strip(), file=sys.stderr)
        return 1
    url = r.stdout.strip().splitlines()[-1]
    print(f"{url}  [{ev['label']}]" + (f" reasons: {' / '.join(ev['reasons'])}" if ev["reasons"] else ""))
    if ev["label"] == "evidence-ok" and par.get("auto_merge"):
        # auto-merge only behind branch protection with a required status check (CI = check.sh full)
        prot = run(["gh", "api", f"repos/{{owner}}/{{repo}}/branches/{ev['base']}/protection/required_status_checks"], root)
        if prot.returncode != 0 or '"contexts":[]' in prot.stdout.replace(" ", ""):
            print("auto-merge: skipped — base branch has no required status checks (set branch protection first)")
            return 0
        m = run(["gh", "pr", "merge", url, "--auto", "--squash"], root)
        print("auto-merge: " + ("enabled (merges when required checks pass)" if m.returncode == 0
                                else "not enabled — " + (m.stderr.strip() or m.stdout.strip())[:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
