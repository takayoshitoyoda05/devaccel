"""Median table per (task, cond) from bench results: python3 tests/bench/summarize.py [results/*.jsonl]"""

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

files = sys.argv[1:] or sorted(str(p) for p in (Path(__file__).parent / "results").glob("*.jsonl"))
rows = [json.loads(ln) for f in files for ln in open(f, encoding="utf-8") if ln.strip()]
groups = defaultdict(list)
for r in rows:
    groups[(r["task"], r["cond"])].append(r)
print("| task | cond | n | held-out | check | cost (med) | turns (med) | wall s (med) | top tools |")
print("|---|---|---|---|---|---|---|---|---|")
for (task, cond), rs in sorted(groups.items()):
    held = sum(r["heldout_failed"] == 0 for r in rs)
    tools: dict = defaultdict(int)
    for r in rs:
        for k, v in (r.get("tools") or {}).items():
            tools[k] += v
    top = ", ".join(f"{k}×{v / len(rs):.0f}" for k, v in sorted(tools.items(), key=lambda kv: -kv[1])[:4])
    print(f"| {task} | {cond} | {len(rs)} | {held}/{len(rs)} all-pass | {sum(r['check_full'] for r in rs)}/{len(rs)} "
          f"| {st.median(r['cost_usd'] or 0 for r in rs):.3f} | {st.median(r['turns'] or 0 for r in rs):.0f} "
          f"| {st.median(r['wall_s'] for r in rs):.0f} | {top} |")
