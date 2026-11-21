"""Sequential vs parallel on the same independent tasks (kit-side; costs quota).

Arms (choose with --arms):
  seq_old   one session, implements in order, then the old 5-6 turn PR flow (notes, add, commit, push, PR script)
  seq_ship  one session, implements in order, then devaccel-pr (one-command devaccel_ship.py)
  par       /devaccel-batch as a user would call it (the skill may choose sequential for small work)
  par_force /devaccel-batch, told to always run devaccel-unit (haiku) units in parallel, then ship --units
  <arm>_haiku  the same arm with the session itself on haiku (e.g. seq_ship_haiku, par_force_haiku)
Measured per arm: wall clock until the PR exists, cost (+ per-model breakdown), turns, PR labels,
held-out tests on the integrated result. Each arm's PRs/branches/worktrees are cleaned up afterwards.

usage: python3 tests/bench/parallel/run.py --trial <trusted project, devaccel installed, GitHub origin>
           [--tasks tasks.md] [--heldout heldout/test_par_heldout.py] [--arms seq_ship,par] [--reps 1]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAIL = "確認は不要なので、そのまま最後まで進めて。"
OLD_PR = ("最後に次の手順で PR を 1 本作って: 確認メモを `.devaccel/pr-notes.md` に Write → `git add <変更したパス>` → "
          "コミットメッセージを `.devaccel/commit-msg.txt` に Write → `git commit -F .devaccel/commit-msg.txt` → "
          "`git push origin HEAD` → `python3 .claude/hooks/devaccel_pr.py --title \"<要約>\" --verify-notes "
          ".devaccel/pr-notes.md`。各コマンドは単独で実行する。")


def sh(cmd: list[str], cwd: Path, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


CAP: int | None = None  # --cap: CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS for this run (command-line settings win)


FOLLOWUP: str | None = None  # --followup: a second request in the same session (e.g. "rename this")


def claude(prompt: str, cwd: Path, model: str, effort: str = "", resume: str = "") -> tuple[dict, float]:
    t0 = time.time()
    extra = ["--settings", json.dumps({"env": {"CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": str(CAP)}})] if CAP else []
    r = sh(["claude", "-p", prompt, "--output-format", "json", "--model", model, "--permission-mode", "acceptEdits",
            *(["--effort", effort] if effort else []), *(["--resume", resume] if resume else []), *extra], cwd)
    wall = time.time() - t0
    try:
        return json.loads(r.stdout), wall
    except ValueError:
        return {"is_error": True, "result": (r.stdout + r.stderr)[-800:]}, wall


def with_followup(j: dict, wall: float, cwd: Path, model: str, effort: str, suffix: str = "") -> tuple[dict, float]:
    """--followup: send the second request into the same session; time and cost are the sum of both."""
    if not FOLLOWUP or not j.get("session_id"):
        return j, wall
    j2, w2 = claude(FOLLOWUP + suffix + TAIL, cwd, model, effort, resume=j["session_id"])
    merged = dict(j2)
    merged["total_cost_usd"] = round((j.get("total_cost_usd") or 0) + (j2.get("total_cost_usd") or 0), 4)
    merged["num_turns"] = (j.get("num_turns") or 0) + (j2.get("num_turns") or 0)
    merged["first_wall"] = round(wall)
    merged["result"] = (j.get("result") or "") + "\n\n--- followup ---\n" + (j2.get("result") or "")
    return merged, wall + w2


def save_answer(patch: Path, j: dict) -> None:
    patch.with_suffix(".answer.md").write_text(j.get("result") or "", encoding="utf-8")


def open_prs(trial: Path) -> list[dict]:
    r = sh(["gh", "pr", "list", "--state", "open", "--json", "number,headRefName,labels,title"], trial)
    return json.loads(r.stdout or "[]")


def grade(trial: Path, branches: list[str], heldout: Path, patch: Path | None = None) -> dict:
    wt = Path(sh(["mktemp", "-d"], trial).stdout.strip()) / "g"
    sh(["git", "fetch", "-q", "origin"], trial)
    sh(["git", "worktree", "add", "-q", "--detach", str(wt), "origin/main"], trial)
    try:
        conflicts = []
        for b in branches:
            m = sh(["git", "-c", "user.name=g", "-c", "user.email=g@g", "merge", "--no-edit", f"origin/{b}"], wt)
            if m.returncode != 0:
                conflicts.append(b)
                sh(["git", "merge", "--abort"], wt)
        if patch is not None:  # the integrated diff, for the blind quality review
            patch.write_text(sh(["git", "diff", "origin/main", "HEAD"], wt).stdout, encoding="utf-8")
        shutil.copy(heldout, wt / "tests" / heldout.name)
        sh(["uv", "sync", "-q"], wt)
        r = sh(["uv", "run", "pytest", "-q", f"tests/{heldout.name}"], wt)
        last = (r.stdout.strip().splitlines() or [""])[-1]
        return {"heldout": last, "heldout_ok": r.returncode == 0, "merge_conflicts": conflicts}
    finally:
        sh(["git", "worktree", "remove", "--force", str(wt)], trial)


def cleanup(trial: Path, prs: list[dict]) -> None:
    for p in prs:
        sh(["gh", "pr", "close", str(p["number"]), "-c", "bench run; closed automatically"], trial)
        sh(["git", "push", "-q", "origin", "--delete", p["headRefName"]], trial)
    for line in sh(["git", "worktree", "list", "--porcelain"], trial).stdout.splitlines():
        if line.startswith("worktree ") and "/.claude/worktrees/" in line:
            sh(["git", "worktree", "remove", "--force", line.split(" ", 1)[1]], trial)
    sh(["git", "checkout", "-q", "-f", "main"], trial)
    # a run that stopped without a PR leaves its files behind; the next run would build on them
    sh(["git", "reset", "-q", "--hard", "HEAD"], trial)
    sh(["git", "clean", "-q", "-fd"], trial)  # untracked, not ignored (.devaccel/.venv stay)
    for b in sh(["git", "branch", "--format=%(refname:short)"], trial).stdout.split():
        if b != "main":
            sh(["git", "branch", "-D", b], trial)
    for b in sh(["git", "ls-remote", "--heads", "origin"], trial).stdout.split():
        if b.startswith("refs/heads/") and b != "refs/heads/main" and any(k in b for k in ("worktree-agent", "bench",
                                                                                               "unit/", "batch/")):
            sh(["git", "push", "-q", "origin", "--delete", b[len("refs/heads/"):]], trial)
    sh(["git", "fetch", "-q", "--prune"], trial)


def usage(j: dict) -> dict:
    return {m: {"cost": round(u.get("costUSD", 0), 3), "out": u.get("outputTokens"),
                "cache_read": u.get("cacheReadInputTokens"), "cache_write": u.get("cacheCreationInputTokens")}
            for m, u in (j.get("modelUsage") or {}).items()}


TASKS_PATH: Path | None = None


def run_fanout(trial: Path, extra: list[str] | None = None) -> tuple[dict, float]:
    """devaccel_batch.py: deterministic fan-out, no LLM parent (run as a human would, outside Claude Code)."""
    import os
    import re
    import sys
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["DEVACCEL_TIMING"] = "1"
    t0 = time.time()
    r = subprocess.run([sys.executable, ".claude/hooks/devaccel_batch.py", str(TASKS_PATH), "--branch",
                        "batch/fanout-bench", *(extra or [])], cwd=trial, capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=3600)
    wall = time.time() - t0
    m = re.search(r"units: (\d+)/(\d+) ok, \d+s, \$([\d.]+)", r.stdout)
    return {"total_cost_usd": float(m.group(3)) if m else None, "num_turns": 0,
            "result": (r.stdout + r.stderr)[-2500:]}, wall


VANILLA = Path.home() / "programming/python/devaccel-vanilla"  # the trial without devaccel (same personal trimming)


def run_vanilla(arm: str, tasks: str, heldout: Path, effort: str = "") -> dict:
    """Plain Claude Code, one session, sequential, no devaccel; commits at the end (no PR: that only flatters
    the baseline). Quality is graded on the resulting diff exactly like the other arms."""
    model = {"vanilla_sonnet": "claude-sonnet-5-5", "vanilla_opus": "claude-opus-5-5"}[arm]
    base = sh(["git", "rev-parse", "HEAD"], VANILLA).stdout.strip()
    prompt = tasks + "\n実装とテストが終わったら git commit して。" + TAIL
    j, wall = claude(prompt, VANILLA, model, effort)
    j, wall = with_followup(j, wall, VANILLA, model, effort, "\n終わったら git commit して。")
    sh(["git", "add", "-A"], VANILLA)
    sh(["git", "-c", "user.name=b", "-c", "user.email=b@b", "commit", "-qm", "leftover"], VANILLA)
    patch = HERE / "patches" / f"{dt.datetime.now():%m%d-%H%M%S}-{arm}.patch"
    patch.parent.mkdir(exist_ok=True)
    patch.write_text(sh(["git", "diff", base, "HEAD"], VANILLA).stdout, encoding="utf-8")
    save_answer(patch, j)
    wt = Path(sh(["mktemp", "-d"], VANILLA).stdout.strip()) / "g"
    sh(["git", "worktree", "add", "-q", "--detach", str(wt), "HEAD"], VANILLA)
    shutil.copy(heldout, wt / "tests" / heldout.name)
    sh(["uv", "sync", "-q"], wt)
    r = sh(["uv", "run", "pytest", "-q", f"tests/{heldout.name}"], wt)
    sh(["git", "worktree", "remove", "--force", str(wt)], VANILLA)
    sh(["git", "reset", "-q", "--hard", base], VANILLA)
    sh(["git", "clean", "-q", "-fdx", "-e", ".claude/settings.local.json", "-e", ".venv"], VANILLA)
    return {"arm": arm + ("_med" if effort else ""), "wall_s": round(wall), "cost_usd": j.get("total_cost_usd"),
            "turns": j.get("num_turns"), "models": usage(j), "prs": [], "result_tail": (j.get("result") or "")[-300:],
            "heldout": (r.stdout.strip().splitlines() or [""])[-1], "heldout_ok": r.returncode == 0,
            "merge_conflicts": [], "patch": patch.name, "first_wall": j.get("first_wall")}


def run_arm(arm: str, trial: Path, tasks: str, heldout: Path, model: str) -> dict:
    if arm.startswith("vanilla_"):
        med = arm.endswith("_med")
        return run_vanilla(arm[: -len("_med")] if med else arm, tasks, heldout, "medium" if med else "")
    sh(["git", "checkout", "-q", "main"], trial)
    sh(["git", "pull", "-q"], trial)
    before = {p["number"] for p in open_prs(trial)}
    if arm.startswith("fanout"):
        extra = {"fanout_hedge": ["--hedge", "2"], "fanout_sonnet": ["--model", "sonnet"],
                 "fanout_med": ["--effort", "medium"], "fanout_high": ["--effort", "high"],
                 "fanout_noctx": ["--no-context"], "fanout_strong1": ["--strong", "1"],
                 "fanout_strong2": ["--strong", "2"]}.get(arm)
        j, wall = run_fanout(trial, extra)
        new = [p for p in open_prs(trial) if p["number"] not in before]
        rec = {"arm": arm, "wall_s": round(wall), "cost_usd": j.get("total_cost_usd"), "turns": 0, "models": {},
               "prs": [(p["number"], [x["name"] for x in p["labels"]]) for p in new], "result_tail": j["result"]}
        patch = HERE / "patches" / f"{dt.datetime.now():%m%d-%H%M%S}-{arm}.patch"
        patch.parent.mkdir(exist_ok=True)
        rec.update(grade(trial, [p["headRefName"] for p in new], heldout, patch))
        rec["patch"] = patch.name
        cleanup(trial, new)
        return rec
    effort, label = "", arm
    if arm.endswith("_low"):  # the parent session at low effort
        effort, arm = "low", arm[: -len("_low")]
    elif arm.endswith("_med"):  # the parent session at medium effort (units keep their own)
        effort, arm = "medium", arm[: -len("_med")]
    elif arm.endswith("_high"):  # the parent session at high effort
        effort, arm = "high", arm[: -len("_high")]
    if arm.endswith("_haiku"):  # the whole session (parent) on haiku; units are haiku anyway
        model = "claude-haiku-5-5"
        arm_base = arm[: -len("_haiku")]
    else:
        arm_base = arm
    if arm_base in ("par", "par_force"):
        force = ("\n計測のため、使う条件(件数・規模)にかかわらず、必ず devaccel-unit を単位の数だけ並列に起動して実装し、"
                 "ship --units で統合して。" if arm_base == "par_force" else "")
        prompt = "/devaccel-batch " + tasks + force + "\n" + TAIL
    elif arm_base == "auto":  # no routing hint: the session decides (fan-out for >=4 independent tasks) and ships
        prompt = tasks + "\n" + TAIL
    elif arm_base == "auto_spec":  # experiment: one feature through the design doc + haiku units (watch)
        prompt = (tasks + "\n(計測) 1 機能でも devaccel-batch の「設計書」の手順(書きながら走らせる --watch)で進めて: "
                  "判断一覧と、重い処理ごとに分けた 2〜3 件(別ファイル・関数の型・規則・例)を短く書き、haiku の単位に"
                  "実装させる。件どうしは import しない形に分ける。\n" + TAIL)
    elif arm_base == "auto_found":  # experiment: L work as foundation -> parallel parts -> integration
        prompt = (tasks + "\n(計測) 大きい変更なので「土台 → 並列 → 統合」で進めて:\n"
                  "1. 作業ブランチ `feat/<名前>` を作り、土台だけを書く: 共有する型と既存ファイルへの最小の変更、新しいモジュールは"
                  "関数・クラスの型と docstring(決めた扱い `D1: …`)だけで本体は `raise NotImplementedError`。"
                  "`git add <パス>` と `git commit -m \"foundation\"` で commit する(検査はまだ通らなくてよい)。\n"
                  "2. `docs/design/<名前>.md` に部品を番号付きで書く(1 件 = 土台の 1 モジュールの本体 + そのテストファイル。"
                  "関数の型・規則・例。件どうしは互いのモジュールを編集しない)。\n"
                  "3. Bash を run_in_background で `python3 .claude/hooks/devaccel_batch.py docs/design/<名前>.md "
                  "--branch batch/<名前> --parts`(土台の commit から haiku/sonnet の単位が並列に作る)。\n"
                  "4. 待つ間に、自分は CLI の配線と、部品をつなぐ統合テストを書く(部品のファイルは触らない)。\n"
                  "5. 完了通知の `parts: …` を受けて `python3 .claude/hooks/devaccel_ship.py --check --file .devaccel/ship.md "
                  "--units <parts のブランチ...> --paths <自分が作ったファイル...>` で統合・検査・PR。\n" + TAIL)
    elif arm_base == "auto_fn":  # experiment: function-sized leaves on many haiku units, parent glues meanwhile
        prompt = (tasks + "\n(計測) 「関数 1 つ = 単位 1 つ」で進めて(haiku は小さい件なら迷わず速い):\n"
                  "1. `docs/design/<名前>.md` に、冒頭(目的・共通前提・判断一覧)を書き、続けて部品を番号付きで 1 件ずつ書く。"
                  "1 件 = 純粋な関数 1〜2 個 + そのテスト(`src/kakeibo/_<部品>.py` + `tests/test__<部品>.py`)。"
                  "関数の型・規則・例の表を書く。部品どうしは import しない(必要なものは引数で受け取る)。"
                  "最初に冒頭と 2〜3 件を書いたら最後の行に `<!-- more -->` を置く。\n"
                  "2. すぐに Bash を run_in_background で `python3 .claude/hooks/devaccel_batch.py docs/design/<名前>.md "
                  "--branch batch/<名前> --watch --parts`(書いた件から単位が動き出す)。\n"
                  "3. 残りの部品を Edit で `<!-- more -->` の前に書き足し、最後に `<!-- end -->` を置く。\n"
                  "4. 待つ間に、各機能の公開モジュール(部品をつなぐ薄い関数)と、つないだ振る舞いのテストを自分で書く"
                  "(部品のファイルは触らない)。\n"
                  "5. 完了通知の `parts: …` を受けて `python3 .claude/hooks/devaccel_ship.py --check --file .devaccel/ship.md "
                  "--branch feat/<名前> --units <parts のブランチ...> --paths <自分が作ったファイル...>` で統合・検査・PR。\n" + TAIL)
    elif arm_base == "auto_nodesign":  # baseline for loosely worded requests: no design doc
        prompt = tasks + "\n設計書は書かずに、そのまま進めて。\n" + TAIL
    elif arm_base == "auto_design":  # the proposal under test: a design doc with acceptance criteria first
        prompt = (tasks + "\nまず設計書を書いてから進めて: 各件のファイル・関数とクラスの名前と型・入力と出力の具体例(端の"
                  "ケースと出す例外)・結果の並び順・受け入れ条件を、件ごとに番号付きで書く。それを実装の指示にする。\n" + TAIL)
    else:
        sh(["git", "checkout", "-q", "-B", f"bench/{arm}", "main"], trial)
        how = OLD_PR if arm_base == "seq_old" else "最後に devaccel-pr スキルで PR を 1 本作って。"
        prompt = tasks + "\n上の各件を 1 つのセッションで順番に実装し、" + how + TAIL
    t_start = time.time()
    j, wall = claude(prompt, trial, model, effort)
    j, wall = with_followup(j, wall, trial, model, effort)
    new = [p for p in open_prs(trial) if p["number"] not in before]
    fan = trial / ".devaccel" / "batch-last.json"  # nested fan-out units are billed outside this session's JSON
    fan_cost = None
    if fan.exists():
        fj = json.loads(fan.read_text())
        if fj.get("ts", 0) >= t_start:
            fan_cost = fj.get("cost_usd")
    if fan_cost is not None and j.get("total_cost_usd") is not None:
        j["total_cost_usd"] = round(j["total_cost_usd"] + fan_cost, 4)
    rec = {"arm": label, "wall_s": round(wall), "cost_usd": j.get("total_cost_usd"), "fanout_cost": fan_cost, "turns": j.get("num_turns"),
           "models": usage(j), "prs": [(p["number"], [x["name"] for x in p["labels"]]) for p in new],
           "result_tail": (j.get("result") or "")[-300:]}
    patch = HERE / "patches" / f"{dt.datetime.now():%m%d-%H%M%S}-{arm}.patch"
    patch.parent.mkdir(exist_ok=True)
    rec.update(grade(trial, [p["headRefName"] for p in new], heldout, patch))
    rec["patch"] = patch.name
    rec["first_wall"] = j.get("first_wall")
    save_answer(patch, j)
    cleanup(trial, new)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, default=HERE / "tasks.md")
    ap.add_argument("--heldout", type=Path, default=HERE / "heldout" / "test_par_heldout.py")
    ap.add_argument("--arms", default="seq_old,seq_ship,par")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--cap", type=int, default=None, help="max concurrent subagents for this run")
    ap.add_argument("--followup", default=None, help="a second request sent into the same session")
    ap.add_argument("--setup", type=Path, default=None,
                    help="a patch applied (and committed) to both the trial's main and the vanilla clone before the "
                         "runs, removed afterwards: a planted bug, a precondition")
    a = ap.parse_args()
    global CAP, FOLLOWUP
    CAP = a.cap
    FOLLOWUP = a.followup
    trial = a.trial.expanduser().resolve()
    tasks = a.tasks.read_text(encoding="utf-8")
    global TASKS_PATH
    TASKS_PATH = a.tasks.resolve()
    out = HERE / "results.jsonl"
    undo = setup(trial, a.setup.resolve()) if a.setup else None
    try:
        return run_all(a, trial, tasks, out)
    finally:
        if undo:
            undo()


def setup(trial: Path, patch: Path):
    """Commit the patch on the trial's main (pushed: units and ship start from origin/main) and on the vanilla
    clone; returns the undo (a revert commit on the trial, a hard reset on the vanilla clone)."""
    sh(["git", "checkout", "-q", "main"], trial)
    sh(["git", "pull", "-q"], trial)
    vbase = sh(["git", "rev-parse", "HEAD"], VANILLA).stdout.strip()
    for repo in (trial, VANILLA):
        r = sh(["git", "apply", str(patch)], repo)
        if r.returncode != 0:
            raise SystemExit(f"setup patch does not apply in {repo}: {r.stderr.strip()}")
        sh(["git", "add", "-A", "src", "tests"], repo)
        sh(["git", "-c", "user.name=b", "-c", "user.email=b@b", "commit", "-qm", f"bench setup: {patch.name}"], repo)
    sh(["git", "push", "-q", "origin", "main"], trial)
    tsetup = sh(["git", "rev-parse", "HEAD"], trial).stdout.strip()

    def undo() -> None:
        sh(["git", "checkout", "-q", "-f", "main"], trial)
        sh(["git", "revert", "--no-edit", tsetup], trial)
        sh(["git", "push", "-q", "origin", "main"], trial)
        sh(["git", "reset", "-q", "--hard", vbase], VANILLA)
    return undo


def run_all(a, trial: Path, tasks: str, out: Path) -> int:
    for rep in range(a.reps):
        for arm in a.arms.split(","):
            rec = run_arm(arm, trial, tasks, a.heldout.resolve(), a.model)
            rec.update({"rep": rep, "tasks": a.tasks.name, "cap": a.cap,
                        "ts": dt.datetime.now().isoformat(timespec="seconds")})
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(json.dumps(rec, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
