"""Release smoke test against real Claude Code (kit-side; ~$0.3 of quota). Run before tagging.

Catches what unit tests cannot (every 0.6-0.8 regression was of this kind):
  1. Bash latency in a sandboxed session (0.8.1: a $HOME-wide denyRead glob made each call 4-15 s).
  2. A /batch-style worktree unit can edit, write notes outside .claude/, commit and build a PR body
     without any permission denial (0.6.4 / 0.6.5 / 0.7.1 / 0.7.2).

usage: python3 tests/smoke/release_smoke.py --trial <trusted project with devaccel installed>
Exit 0 = pass. Leaves no branches or worktrees behind.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import subprocess
import sys
from pathlib import Path


def sh(cmd: list[str], cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def claude(prompt: str, cwd: Path) -> dict:
    r = sh(["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits"], cwd)
    return json.loads(r.stdout)


def transcript_dir(cwd: Path) -> Path:
    return Path.home() / ".claude" / "projects" / ("-" + str(cwd).strip("/").replace("/", "-").replace("_", "-"))


def events(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        msg = e.get("message") if isinstance(e, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list) and "timestamp" in e:
            yield e, content


def bash_latencies(path: Path) -> list[float]:
    ts = lambda x: dt.datetime.fromisoformat(x.replace("Z", "+00:00"))  # noqa: E731
    start, out = {}, []
    for e, content in events(path):
        for b in content:
            if b.get("type") == "tool_use" and b.get("name") == "Bash":
                start[b["id"]] = ts(e["timestamp"])
            if b.get("type") == "tool_result" and b.get("tool_use_id") in start:
                out.append((ts(e["timestamp"]) - start[b["tool_use_id"]]).total_seconds())
    return out


def denials(folder: Path) -> list[str]:
    found = []
    for f in folder.rglob("*.jsonl"):
        for _e, content in events(f):
            for b in content:
                if b.get("type") == "tool_result" and "Permission to use" in json.dumps(b.get("content")):
                    found.append(f"{f.name}: {json.dumps(b.get('content'))[:120]}")
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", type=Path, required=True, help="a trusted project with devaccel installed")
    ap.add_argument("--max-bash-median", type=float, default=2.0)  # PERF-04
    a = ap.parse_args()
    trial = a.trial.expanduser().resolve()
    tdir = transcript_dir(trial)
    ok = True

    j = claude("Bash を次の順に別々の呼び出しで実行して、報告は done だけ: 1) `ls` 2) `git status --short` "
               "3) `uv run python -c pass`", trial)
    lat = bash_latencies(tdir / f"{j['session_id']}.jsonl")
    med = statistics.median(lat) if lat else 99.0
    print(f"[1] bash latency: {[round(x, 1) for x in lat]} median {med:.1f}s (limit {a.max_bash_median}s)")
    ok &= bool(lat) and med <= a.max_bash_median

    before = set(sh(["git", "worktree", "list", "--porcelain"], trial).stdout.split("\n"))
    j = claude(
        'Agent ツールで isolation: "worktree" の general-purpose サブエージェントを 1 つ起動して。指示:「README.md の末尾に '
        '`<!-- smoke -->` を 1 行足す。devaccel-pr スキルの手順 1〜2 に従い、`.devaccel/pr-notes.md` に確認メモを Write し、'
        '`git add README.md` と `.devaccel/commit-msg.txt` を使ったコミットまで行う。push はしない。最後に '
        '`python3 .claude/hooks/devaccel_pr.py --title smoke --verify-notes .devaccel/pr-notes.md --dry-run` を実行し、'
        "最終行の JSON をそのまま返す」。結果の JSON だけを報告して。", trial)
    sub = tdir / j["session_id"]
    bad = denials(sub) if sub.exists() else ["no subagent transcript"]
    labeled = '"label"' in j.get("result", "")
    print(f"[2] worktree unit: denials={len(bad)} dry-run label={'yes' if labeled else 'no'}")
    for d in bad[:5]:
        print("    " + d)
    ok &= not bad and labeled

    # cleanup: worktrees and branches created by this run
    for line in sh(["git", "worktree", "list", "--porcelain"], trial).stdout.split("\n"):
        if line.startswith("worktree ") and line not in before and "/.claude/worktrees/" in line:
            wt = line.split(" ", 1)[1]
            br = sh(["git", "-C", wt, "rev-parse", "--abbrev-ref", "HEAD"], trial).stdout.strip()
            sh(["git", "worktree", "remove", "--force", wt], trial)
            if br and br not in ("main", "HEAD"):
                sh(["git", "branch", "-D", br], trial)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
