# devaccel core — DO NOT EDIT. Tune behavior in .claude/project.json instead.
"""Stop hook: L1 mechanical gate.

Runs `scripts/check.sh fast` once per changed working tree, returns only the
failed stage to Claude, escalates to the human after N failed rounds, and
shows (never blocks on) scale / test-weakening notices.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from devaccel_common import (  # noqa: E402
    emit,
    git,
    is_git_repo,
    load_config,
    log_event,
    match_any,
    project_root,
    trusted_root,
    read_stdin_json,
    state_dir,
)

MAX_SIG_FILES = 3000
TAIL_LINES = 40
SKIP_RE = re.compile(
    r"^\+.*(pytest\.mark\.(skip|xfail)|pytest\.skip\(|@unittest\.skip|unittest\.expectedFailure)"
)


# ---------- working tree ----------


def changed_paths(root: Path) -> list[tuple[str, str]]:
    """(status, path) for every uncommitted change incl. untracked files."""
    out = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    items: list[tuple[str, str]] = []
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if status[0] in "RC":  # rename/copy: next field is the source path
            i += 1
        items.append((status, path))
    return items


def signature(root: Path, items: list[tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for status, path in sorted(items)[:MAX_SIG_FILES]:
        h.update(f"{status}\0{path}\0".encode())
        p = root / path
        try:
            if p.is_file():
                h.update(hashlib.sha256(p.read_bytes()).digest())
        except OSError:
            pass
    return h.hexdigest()


def base_ref(root: Path, base_branch: str) -> str:
    head = git(root, "rev-parse", "HEAD").strip()
    if not head:
        return ""
    mb = git(root, "merge-base", "HEAD", base_branch).strip()
    return mb or head


def branch_files(root: Path, base: str) -> set[str]:
    if not base:
        return set()
    return {p for p in git(root, "diff", "--name-only", base, "HEAD").splitlines() if p}


# ---------- check.sh ----------


def run_check(root: Path, timeout: int, anchor: Path | None = None) -> tuple[str, int, str, float]:
    """Returns (result, returncode, output, seconds). result: pass|fail|timeout|missing.
    Runs the anchor's (main checkout's) check.sh against root, so a worktree cannot weaken its gate."""
    script = (anchor or root) / "scripts" / "check.sh"
    if not script.exists():
        return "missing", 0, "", 0.0
    t0 = time.time()
    text = script.read_text(encoding="utf-8").replace('cd "$(dirname "$0")/.."', f'cd "{root}"')
    try:
        r = subprocess.run(
            ["bash", "-c", text, "check.sh", "fast"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "timeout", -1, "", time.time() - t0
    out = (r.stdout or "") + (r.stderr or "")
    return ("pass" if r.returncode == 0 else "fail"), r.returncode, out, time.time() - t0


def failed_section(output: str) -> tuple[str, str]:
    """Name of the failed stage and the tail of only that stage's output."""
    lines = output.splitlines()
    start, name = 0, "unknown"
    for idx, line in enumerate(lines):
        if line.startswith("== stage: "):
            start, name = idx, line[len("== stage: ") :].strip()
        if line.startswith("== failed: "):
            name = line[len("== failed: ") :].split(" (")[0].strip()
            section = lines[start:idx]
            return name, "\n".join(section[-TAIL_LINES:])
    return name, "\n".join(lines[-TAIL_LINES:])


def stage_times(output: str) -> dict[str, int]:
    times = {}
    for m in re.finditer(r"^== (?:ok|failed|missing): (\S+) \((\d+)s\)", output, re.M):
        times[m.group(1)] = int(m.group(2))
    return times


# ---------- notices (shown to the human, never block) ----------


def notices(root: Path, cfg: dict, items: list[tuple[str, str]], base: str) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    files = {p for _, p in items} | branch_files(root, base)
    scale = cfg["scale"]
    risky = sorted(p for p in files if match_any(p, scale["risky_paths"]))
    has_design = any(p.startswith("docs/design/") for p in files)
    if not has_design and (len(files) > scale["large_if_files_over"] or risky):
        why = f"{len(files)} files" + (f", risky: {', '.join(risky[:3])}" if risky else "")
        msgs.append(("scale", f"L相当の変更です({why})。design スキルでの設計書と仕様照合を検討してください。"))

    test_globs = cfg["integrity"]["test_globs"]
    deleted = sorted(p for s, p in items if "D" in s and match_any(p, test_globs))
    diff = git(root, "diff", "-U0", base) if base else ""
    skips = [ln[1:].strip() for ln in diff.splitlines() if SKIP_RE.match(ln)]
    if deleted:
        msgs.append(("deleted", f"テストファイルが削除されています: {', '.join(deleted[:5])}"))
    if skips:
        msgs.append(("skip", f"skip/xfail が追加されています({len(skips)}件): {skips[0][:80]}"))
    return msgs


# ---------- state ----------


def load_state(root: Path) -> dict:
    p = state_dir(root) / "gate-state.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(root: Path, state: dict) -> None:
    # keep only the 20 most recent sessions
    if len(state) > 20:
        for k in sorted(state, key=lambda k: state[k].get("t", 0))[:-20]:
            del state[k]
    p = state_dir(root) / "gate-state.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(p)


# ---------- main ----------


def main() -> int:
    data = read_stdin_json()
    root = project_root(data)  # what is checked (may be a /batch worktree)
    anchor = trusted_root(data)  # config and check.sh come from here, not from the worktree
    cfg = load_config(anchor)
    gate = cfg["gate"]
    mode = gate["mode"]
    if mode == "off" or not is_git_repo(root):
        return 0

    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch and match_any(branch, gate["skip_branches"]):
        return 0

    items = changed_paths(root)
    relevant = [it for it in items if not match_any(it[1], gate["ignore"])]
    if not relevant:
        return 0

    sig = signature(root, relevant)
    state = load_state(root)
    sid = data.get("agent_id") or data.get("session_id", "default")  # each /batch unit has its own rounds
    sess = state.setdefault(sid, {"ok": "", "seen": "", "streak": 0, "noticed": []})
    sess["t"] = time.time()
    if sig in (sess["ok"], sess["seen"]):
        return 0  # nothing changed since the last check (e.g. a question-only turn)
    result, _rc, output, secs = run_check(root, int(gate["timeout_sec"]), anchor)
    # fast mode may auto-format: remember the tree as it is *after* the check
    relevant = [it for it in changed_paths(root) if not match_any(it[1], gate["ignore"])]
    sig = signature(root, relevant)
    sess["seen"] = sig
    base = base_ref(root, cfg["scale"]["base_branch"])
    event = {
        "session": sid,
        "mode": mode,
        "result": result,
        "secs": round(secs, 1),
        "files": len(relevant),
        "stages": stage_times(output),
    }
    reply: dict = {}

    if result == "timeout":
        log_event(root, event)
        reply["systemMessage"] = (
            f"[devaccel] check.sh fast が {gate['timeout_sec']}s で打ち切られました。"
            "検査は未完了です。fast の段を減らすか /devaccel-setup で再計測してください。"
        )
    elif result == "missing":
        log_event(root, event)
    elif result == "pass":
        sess["ok"], sess["streak"] = sig, 0
        log_event(root, event)
    else:
        stage, tail = failed_section(output)
        event["stage"] = stage
        max_rounds = int(gate["max_rounds"])
        if mode == "observe":
            event["result"] = "would_block"
            log_event(root, event)
            save_state(root, state)
            return 0
        sess["streak"] += 1
        event["streak"] = sess["streak"]
        if sess["streak"] <= max_rounds:
            log_event(root, event)
            reply["decision"] = "block"
            reply["reason"] = (
                f"[devaccel] check.sh fast の段 `{stage}` が失敗しました"
                f"(修正ラウンド {sess['streak']}/{max_rounds})。修正してください。"
                "テストや検査を弱める変更で通さないこと。\n\n" + tail
            )
        else:
            event["result"] = "escalate"
            log_event(root, event)
            sess["streak"] = 0
            reply["decision"] = "block"
            reply["reason"] = (
                f"[devaccel] `{stage}` が {max_rounds} ラウンド修正しても通りません。これ以上の修正はやめ、"
                "失敗した段と出力をユーザーに示し、どうするか判断を仰いでください。\n\n" + tail
            )
            reply["systemMessage"] = (
                f"[devaccel] 検査未通過のまま停止: 段 `{stage}`。判断が必要です。"
            )

    if result in ("pass", "fail"):
        fresh = [(k, m) for k, m in notices(root, cfg, relevant, base) if k not in sess["noticed"]]
        if fresh:
            sess["noticed"] = sess["noticed"] + [k for k, _ in fresh]  # once per kind per session
            note = "[devaccel] " + " / ".join(m for _, m in fresh)
            reply["systemMessage"] = (reply.get("systemMessage", "") + "\n" + note).strip()
            log_event(root, {"session": sid, "result": "notice", "notes": [m for _, m in fresh]})

    save_state(root, state)
    emit(reply)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break the session because of the gate itself
        print(f"[devaccel] stop_gate internal error: {e}", file=sys.stderr)
        sys.exit(0)
