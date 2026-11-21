#!/usr/bin/env python3
"""PostToolUse(Bash) hook: start the evidence for a draft PR that ship just opened (devaccel_pr.py --finalize).

ship runs inside Claude Code's sandbox, where anything left running dies with the command; this hook runs outside
it (trusted code, like the Stop gate) and only starts finalize, detached. The request file is written by ship from
inside the sandbox, so it is untrusted: everything in it is re-checked against git and the branch rules here, and
finalize itself re-derives the evidence from the pushed commit (base check.sh, confined by bwrap).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True  # nothing may appear next to the locked scripts (the guard refuses them then)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from devaccel_common import load_config, trusted_root  # noqa: E402
from devaccel_pr import SECRET  # noqa: E402

REQUEST = ".devaccel/finalize.json"
MAX = 16384


def read_request(root: Path) -> dict | None:
    """Read and remove .devaccel/finalize.json, relative to a directory fd opened without following links:
    no symlink at either level, regular files only (a FIFO would hang the hook), bounded size."""
    import stat
    try:
        dfd = os.open(root / ".devaccel", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        try:
            fd = os.open("finalize.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        except OSError:
            try:
                os.unlink("finalize.json", dir_fd=dfd)  # e.g. a planted symlink: drop it, read nothing
            except OSError:
                pass
            return None
        try:
            os.unlink("finalize.json", dir_fd=dfd)  # consumed, valid or not
        except OSError:
            pass
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None
            raw = f.read(MAX + 1)
    finally:
        os.close(dfd)
    if len(raw) > MAX:
        return None
    try:
        req = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return req if isinstance(req, dict) else None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    root = trusted_root(data if isinstance(data, dict) else {})  # the main checkout, never the agent's cwd
    req = read_request(root)
    if req is None:
        return 0
    cfg = load_config(root)
    sha, branch = str(req.get("sha", "")), str(req.get("branch", ""))
    title, notes = str(req.get("title", ""))[:200], str(req.get("notes", ""))[:4096]
    protected = {"main", "master", cfg["scale"]["base_branch"]}
    if (not re.fullmatch(r"[0-9a-f]{40}", sha) or not re.fullmatch(r"\w[\w./-]*", branch) or ".." in branch
            or branch in protected or not title.strip() or SECRET.search(title + "\n" + notes)):
        print(f"devaccel finalize: request refused ({branch!r})", file=sys.stderr)
        return 0
    # finalize itself checks GitHub (an open draft for exactly this commit) before it runs anything; here only one
    # run per branch at a time, so a request written over and over cannot pile up checks
    state = root / ".claude" / "state"
    if state.is_symlink():
        return 0
    state.mkdir(parents=True, exist_ok=True)
    lock = state / ("finalize-" + hashlib.sha256(branch.encode()).hexdigest()[:16] + ".pid")
    try:
        pid = int(lock.read_text()) if lock.exists() and not lock.is_symlink() else 0
        if pid and Path(f"/proc/{pid}").exists():
            print(f"devaccel finalize: one is already running for {branch}", file=sys.stderr)
            return 0
    except (OSError, ValueError):
        pass
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "devaccel_pr.py"), "--title=" + title,
           "--finalize", sha, "--branch", branch]
    if notes.strip():
        fd, tmp = tempfile.mkstemp(prefix="devaccel-notes-", suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(notes)
        cmd += ["--verify-notes", tmp]
    fd = os.open(state / "finalize.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as log:
        log.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {branch} {sha}\n")
        log.flush()
        env = {k: v for k, v in os.environ.items() if k != "SANDBOX_RUNTIME"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        child = subprocess.Popen(cmd, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                                 start_new_session=True)
    try:
        lfd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lfd, "w") as f:
            f.write(str(child.pid))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
