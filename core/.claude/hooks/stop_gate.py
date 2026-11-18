# devaccel core — DO NOT EDIT. Tune behavior in .claude/project.json instead.
"""Stop hook: L1 mechanical gate.

Runs `scripts/check.sh fast` once per changed working tree, returns only the
failed stage to Claude, escalates to the human after N failed rounds, and
shows (never blocks on) scale / test-weakening notices.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.append(str(Path(__file__).resolve().parent))  # (the script dir is already sys.path[0]; planted modules are refused by guard _pr_script_intact)
from devaccel_common import (  # noqa: E402
    check_script_for,
    confined,
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


def run_check(root: Path, timeout: int, anchor: Path | None = None,
              sandbox: bool = True) -> tuple[str, int, str, float]:
    """Returns (result, returncode, output, seconds). result: pass|fail|timeout|missing.
    Runs the anchor's (main checkout's) check.sh against root, so a worktree cannot weaken its gate."""
    script = (anchor or root) / "scripts" / "check.sh"
    if not script.exists():
        return "missing", 0, "", 0.0
    t0 = time.time()
    # the path goes in through the environment, never pasted into shell text
    text = check_script_for(script.read_text(encoding="utf-8", errors="replace"))
    if text is None:
        return "missing", 0, "scripts/check.sh: unrecognised cd line (see CHECK_HEAD)", 0.0
    cmd, env = ["bash", "-c", text, "check.sh", "fast"], {**os.environ}
    if sandbox:  # check.sh runs tests the agent wrote: never with the user's full rights (hooks are unsandboxed)
        protect = [root / ".claude", root / "scripts" / "check.sh"]
        wrapped = confined(cmd, root, protect, mask_env_in=[anchor] if anchor and anchor != root else None)
        if wrapped is None:
            return "missing", 0, "bubblewrap (bwrap) が無いので check.sh を隔離して実行できません(gate.sandbox)", 0.0
        cmd, env = wrapped
    env["DEVACCEL_ROOT"] = str(root)
    try:
        r = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True, errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "timeout", -1, "", time.time() - t0
    except OSError as e:
        return "missing", 0, str(e), time.time() - t0
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


# One state file per session/unit: parallel /batch units never read-modify-write a shared file.
SESSION_DEFAULT = {"ok": "", "seen": "", "fail": "", "reason": "", "escalated": "", "streak": 0, "noticed": []}


def _state_path(root: Path, sid: str) -> Path:
    d = state_dir(root) / "gate"
    d.mkdir(exist_ok=True)
    return d / (re.sub(r"[^A-Za-z0-9_.-]", "_", sid)[:80] + ".json")


def load_session(root: Path, sid: str) -> dict:
    try:
        raw = json.loads(_state_path(root, sid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    sess = dict(SESSION_DEFAULT)
    for k, d in SESSION_DEFAULT.items():  # wrong types fall back (a crash would fail open)
        v = raw.get(k, d)
        sess[k] = v if isinstance(v, type(d)) and not (isinstance(d, int) and isinstance(v, bool)) else d
    if isinstance(raw.get("stage"), str):
        sess["stage"] = raw["stage"]
    sess["noticed"] = [x for x in sess["noticed"] if isinstance(x, str)]
    return sess


def save_session(root: Path, sid: str, sess: dict) -> None:
    p = _state_path(root, sid)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")  # unique per process
    tmp.write_text(json.dumps(sess), encoding="utf-8")
    tmp.replace(p)
    olds = sorted(p.parent.glob("*.json"), key=lambda f: f.stat().st_mtime)[:-50]  # keep the 50 newest
    for f in olds:
        f.unlink(missing_ok=True)


def relevant_paths(root: Path, gate: dict, cfg: dict, unit: bool) -> list[tuple[str, str]]:
    """What the gate judges: uncommitted changes, plus (in a unit) committed-but-unmerged work,
    since units commit before stopping (devaccel-pr)."""
    relevant = [it for it in changed_paths(root) if not match_any(it[1], gate["ignore"])]
    if unit:
        seen_paths = {p for _s, p in relevant}
        relevant += [("C", p) for p in sorted(branch_files(root, base_ref(root, cfg["scale"]["base_branch"])))
                     if p not in seen_paths and not match_any(p, gate["ignore"]) and (root / p).exists()]
    return relevant


# ---------- main ----------


CTX: dict = {}  # for the error log: what we knew when it failed


def main() -> int:
    data = read_stdin_json()
    CTX.update({"session": str(data.get("agent_id") or data.get("session_id") or "")})
    root = project_root(data)  # what is checked (may be a /batch worktree)
    anchor = trusted_root(data)  # config and check.sh come from here, not from the worktree
    cfg = load_config(anchor)
    gate = cfg["gate"]
    # a /batch unit = a linked worktree (git-dir != common-dir); robust to symlinks and path case
    unit = (git(root, "rev-parse", "--path-format=absolute", "--git-dir").strip()
            != git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    # a unit that breaks its worktree's .git link must not fall back to the (off) session mode
    cwd = str(data.get("cwd") or "")
    if "/.claude/worktrees/" in cwd + "/":
        unit = True
        if "/.claude/worktrees/" not in str(root) + "/":  # resolved to the main checkout: link broken
            # a unit must not escape its gate by breaking .git: block like a failure, escalate after max_rounds
            sid = str(data.get("agent_id") or data.get("session_id") or "default")
            sess = load_session(anchor, sid)
            sess["streak"] += 1
            sig = "broken-worktree:" + cwd
            if sess["escalated"] == sig:
                return 0
            reason = "作業単位の worktree が git として壊れていて検査できません(.git リンクを元に戻してください)。"
            reply = _block_or_escalate(sess, sig, "worktree", reason, int(gate["max_rounds"]))
            log_event(anchor, {"session": sid, "scope": "unit", "mode": "enforce", "stage": "worktree",
                               "result": "escalate" if "systemMessage" in reply else "fail",
                               "error": "worktree is not its own git checkout"})
            emit(reply)
            save_session(anchor, sid, sess)
            return 0
    mode = gate.get("unit_mode", "enforce") if unit else gate["mode"]
    CTX.update({"scope": "unit" if unit else "session", "mode": mode})
    if mode == "off" or not is_git_repo(root):
        return 0

    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    CTX["branch"] = branch
    if branch and not unit and match_any(branch, gate["skip_branches"]):  # units cannot opt out by renaming
        return 0

    relevant = relevant_paths(root, gate, cfg, unit)
    if not relevant:
        return 0

    sig = signature(root, relevant)
    sid = str(data.get("agent_id") or data.get("session_id") or "default")  # each /batch unit has its own rounds
    sess = load_session(anchor, sid)
    max_rounds = int(gate["max_rounds"])
    if sig == sess["ok"] or sig == sess["escalated"]:
        return 0  # verified, or already handed to the user, and nothing changed since
    if mode == "observe" and sig == sess["seen"]:
        return 0
    if mode == "enforce" and sig == sess["fail"]:
        # stopping again without changing anything does not get past a failed check
        sess["streak"] += 1
        stage = sess["stage"] if "stage" in sess else "?"
        reply = _block_or_escalate(sess, sig, stage, sess["reason"], max_rounds)
        log_event(anchor, {"session": sid, "branch": branch, "mode": mode, "scope": "unit" if unit else "session",
                           "result": "escalate" if "systemMessage" in reply else "fail", "stage": stage,
                           "streak": sess["streak"], "repeat": True})
        emit(reply)
        save_session(anchor, sid, sess)
        return 0
    # the hook itself is killed by Claude Code at its settings timeout (120 s): stay below it
    result, _rc, output, secs = run_check(root, min(int(gate["timeout_sec"]), 110), anchor, bool(gate.get("sandbox", True)))
    # fast mode may auto-format: remember the tree as it is *after* the check
    relevant = relevant_paths(root, gate, cfg, unit)  # same definition as before the run (else sigs never match)
    sig = signature(root, relevant)
    sess["seen"] = sig
    base = base_ref(root, cfg["scale"]["base_branch"])
    event = {
        "session": sid,
        "branch": branch,  # devaccel_pr counts escalations for its own branch
        "mode": mode,
        "scope": "unit" if unit else "session",
        "result": result,
        "secs": round(secs, 1),
        "files": len(relevant),
        "stages": stage_times(output),
    }
    reply: dict = {}

    if result == "timeout":
        sess["seen"] = ""  # unverified: check again next time
        log_event(anchor, event)
        reply["systemMessage"] = (
            f"[devaccel] check.sh fast が {gate['timeout_sec']}s で打ち切られました。"
            "検査は未完了です。fast の段を減らすか /devaccel-setup で再計測してください。"
        )
    elif result == "missing":
        log_event(anchor, event)
        if mode == "enforce":  # never pass silently when the check could not run
            reply["systemMessage"] = f"[devaccel] check.sh を実行できず未検査です: {output[:200] or 'scripts/check.sh がありません'}"
    elif result == "pass":
        sess["ok"], sess["streak"], sess["fail"] = sig, 0, ""
        log_event(anchor, event)
    else:
        stage, tail = failed_section(output)
        event["stage"] = stage
        if mode == "observe":
            event["result"] = "would_block"
            log_event(anchor, event)
            save_session(anchor, sid, sess)
            return 0
        sess["streak"] += 1
        sess["fail"], sess["reason"], sess["stage"] = sig, tail, stage
        event["streak"] = sess["streak"]
        reply = _block_or_escalate(sess, sig, stage, tail, max_rounds)
        if "systemMessage" in reply:
            event["result"] = "escalate"
        log_event(anchor, event)

    if result in ("pass", "fail"):
        fresh = [(k, m) for k, m in notices(root, cfg, relevant, base) if k not in sess["noticed"]]
        if fresh:
            sess["noticed"] = sess["noticed"] + [k for k, _ in fresh]  # once per kind per session
            note = "[devaccel] " + " / ".join(m for _, m in fresh)
            reply["systemMessage"] = (reply.get("systemMessage", "") + "\n" + note).strip()
            log_event(anchor, {"session": sid, "branch": branch, "mode": mode, "scope": "unit" if unit else "session",
                               "result": "notice", "notes": [m for _, m in fresh]})

    emit(reply)  # the decision goes out first; a state-write problem must not swallow a block
    save_session(anchor, sid, sess)
    return 0


def _block_or_escalate(sess: dict, sig: str, stage: str, tail: str, max_rounds: int) -> dict:
    if sess["streak"] <= max_rounds:
        return {"decision": "block", "reason": (
            f"[devaccel] check.sh fast の段 `{stage}` が失敗しました"
            f"(修正ラウンド {sess['streak']}/{max_rounds})。修正してください。"
            "テストや検査を弱める変更で通さないこと。\n\n" + tail)}
    sess["streak"], sess["escalated"] = 0, sig
    return {"decision": "block",
            "reason": (f"[devaccel] `{stage}` が {max_rounds} ラウンド修正しても通りません。これ以上の修正はやめ、"
                       "失敗した段と出力をユーザーに示し、どうするか判断を仰いでください。\n\n" + tail),
            "systemMessage": f"[devaccel] 検査未通過のまま停止: 段 `{stage}`。判断が必要です。"}


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break the session because of the gate itself, but leave a trace
        print(f"[devaccel] stop_gate internal error: {e}", file=sys.stderr)
        try:
            log_event(trusted_root(None), {**CTX, "result": "error", "error": repr(e)[:300]})
        except Exception:
            pass
        sys.exit(0)
