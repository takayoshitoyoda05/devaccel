# devaccel core — DO NOT EDIT.
"""Compact summary of the gate log for the tune skill / doctor (stdout, <= ~25 lines)."""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from devaccel_common import load_config, project_root  # noqa: E402


def summarize(root: Path) -> list[str]:
    cfg = load_config(root)
    out = [f"gate.mode={cfg['gate']['mode']} max_rounds={cfg['gate']['max_rounds']} "
           f"fast_budget={cfg['gate']['fast_budget_sec']}s"]
    log = root / ".claude" / "state" / "gate-log.jsonl"
    events = []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    runs = [e for e in events if e.get("result") in ("pass", "fail", "would_block", "escalate", "timeout", "missing", "error")]
    if not runs:
        out.append("gate log: no runs yet")
    else:
        res = collections.Counter(e["result"] for e in runs)
        out.append(f"gate runs={len(runs)} since {runs[0]['ts']}: " + ", ".join(f"{k}={v}" for k, v in res.most_common()))
        stages = collections.Counter(e.get("stage") for e in runs if e.get("stage"))
        if stages:
            out.append("failing stages: " + ", ".join(f"{k}={v}" for k, v in stages.most_common(5)))
        secs = sorted(e.get("secs", 0) for e in runs)
        out.append(f"check secs: median={secs[len(secs) // 2]} max={secs[-1]}")
        slow = collections.defaultdict(list)
        for e in runs:
            for st, s in (e.get("stages") or {}).items():
                slow[st].append(s)
        if slow:
            out.append("stage avg secs: " + ", ".join(
                f"{k}={sum(v) / len(v):.1f}" for k, v in sorted(slow.items(), key=lambda kv: -sum(kv[1]))))
        notes = collections.Counter(n for e in events if e.get("result") == "notice" for n in e.get("notes", []))
        for n, c in notes.most_common(3):
            out.append(f"notice x{c}: {n[:100]}")
    cm = root / "CLAUDE.md"
    if cm.exists():
        n = len(cm.read_text(encoding="utf-8").splitlines())
        out.append(f"CLAUDE.md lines={n} (budget {cfg['budget']['claude_md_max_lines']})")
    return out


if __name__ == "__main__":
    print("\n".join(summarize(project_root())))
