"""Requirement-driven tests (docs/requirements.md IDs; gaps from docs/traceability.md §2).

Run: python3 -m unittest discover -s tests -v

Mutation check: each test below was run against a deliberately broken core/ or kit/ and failed;
the file was then restored (git diff --stat core kit = empty).

| requirement      | mutation applied (temporarily)                                                    | failed? |
|------------------|-----------------------------------------------------------------------------------|---------|
| SET-01           | kit SANDBOX "failIfUnavailable": False                                            | yes |
| SET-02           | kit SANDBOX denyRead += "~/**/.env"                                               | yes |
| SET-03           | kit permissions.deny += "Read(/uv.lock)"                                          | yes |
| SET-04           | kit allow += "Bash(git diff *)"                                                   | yes |
| SET-05           | kit allow drops "Bash(git push origin HEAD)"                                      | yes |
| SET-06           | kit ask drops "Edit(**/.claude/hooks/**)"                                         | yes |
| SET-07           | kit HOOK_CMDS["stop"] prefixed with "uv run "                                     | yes |
| SET-08           | kit env CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS "20"                                 | yes |
| INST-01          | kit write_lock records sorted(files)[1:]                                          | yes |
| INST-02          | kit write_new ignores an existing destination (overwrites)                        | yes |
| INST-03          | kit cmd_install: clash check removed                                              | yes |
| INST-04          | kit cmd_install: "does not merge" hint block removed                              | yes |
| INST-05          | kit cmd_install: appends all GITIGNORE_LINES (no "missing" filter)                | yes |
| INST-06          | kit cmd_install: cfg["presets"] = []                                              | yes |
| UPD-01           | kit cmd_update: `if not locked` refusal removed / hand-edit `return 1` removed    | yes |
| UPD-03           | kit cmd_update: copy straight into the project (no staging); clash check removed; | yes |
|                  | final write_lock call removed (lock keeps old hashes)                             |     |
| DOC-01           | kit cmd_doctor returns 0 when problems exist                                      | yes |
| DOC-02           | kit cmd_doctor: hash comparison of core files removed                             | yes |
| DOC-03           | kit cmd_doctor: SubagentStop check removed                                        | yes |
| DOC-04           | kit cmd_doctor: `slow` ($HOME glob) check removed; bad_denies check removed       | yes |
| DOC-05           | kit cmd_doctor: CLAUDE.md budget check removed; .devaccel/ check removed          | yes |
| DOC-06           | kit cmd_doctor: fill regex without (?!ed)                                         | yes |
| DOC-07           | kit cmd_doctor: observe note appended to problems                                 | yes |
| DOC-08           | kit cmd_protect: confirmation check removed; PROTECTION strict True               | yes |
| GATE-03          | stop_gate: cfg = load_config(root) (worktree); also fails the fixed               | yes |
|                  | tests/test_devaccel.py::test_gate_checks_the_worktree_not_the_main_checkout       |     |
| GATE-05          | stop_gate: TAIL_LINES = 400                                                       | yes |
| GATE-05/16       | stop_gate: committed branch files not added for units                             | yes |
| GATE-06          | stop_gate: escalation reply without systemMessage                                 | yes |
| GATE-07          | stop_gate: repeat path does not increment streak                                  | yes |
| GATE-08          | stop_gate: skip_branches check removed; post-check signature not recomputed;      | yes |
|                  | gate.ignore filter removed (tests/test_devaccel.py::test_gate_ignores_docs_only)  |     |
| GATE-09          | stop_gate: timeout branch records sess["ok"] = sig                                | yes |
| GATE-10          | stop_gate load_session without try/except; common load_config without except      | yes |
| GATE-11          | stop_gate: sid = "default"                                                        | yes |
| GATE-12          | stop_gate: load_session(root) instead of anchor; "mode" dropped from the event    | yes |
| GATE-13          | stop_gate: notices set decision=block; once-per-kind filter removed               | yes |
| GATE-14          | stop_gate run_check: script = root / scripts/check.sh                             | yes |
| GATE-15          | common load_config: override applied to unit_mode too; `if override` (no MODES)   | yes |
| GRD-01           | guard _RM: `\\$HOME/?` and `\\.git/?` removed from targets                        | yes |
| GRD-02           | guard -c rule without "editor"; OUTPUT_CMDS without "show"                        | yes |
| GRD-03           | guard ASK git add rule without ^ anchor                                           | yes |
| GRD-04           | guard _protected_branches: base_branch / origin HEAD not added; master dropped    | yes |
| GRD-05           | guard: both GH and GH_ANY checks removed                                          | yes |
| GRD-06           | guard ENV_CHANGE without alias; runs-alone check removed                          | yes |
| GRD-08           | guard: lock OSError -> True; PR_FILES without devaccel_common.py / stop_gate.py;  | yes |
|                  | main() reads config from cwd                                                      |     |
| GRD-09           | guard PTY without expect/empty/socat                                              | yes |
| GRD-10           | guard __main__ except: exit without emitting ask; ask_regex loop removed          | yes |
| GRD-11           | guard REMOTE matches any `git commit -F`                                          | yes |
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from pathlib import Path

import test_devaccel as td
from test_devaccel import DEFAULTS, KIT, guard, sh

sys.dont_write_bytecode = True
DEVACCEL = KIT / "kit" / "devaccel.py"
GIT = ["-c", "user.email=a@b", "-c", "user.name=t"]


def run(cwd: Path, *cmd: str, env: dict | None = None, stdin: str = "", drop: tuple = ()) -> subprocess.CompletedProcess:
    full = {k: v for k, v in os.environ.items() if k not in drop and k != "DEVACCEL_GATE_MODE"}
    return subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True, env={**full, **(env or {})})


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if ".git" in p.relative_to(root).parts[:1] or not p.is_file():
            continue
        h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes() + b"\0" + oct(p.stat().st_mode).encode())
    return h.hexdigest()


@unittest.skipUnless(shutil.which("git"), "git required")
class ReqKit(unittest.TestCase):
    """KitTest's fixture (installed temp repo + stub check.sh) without re-running its tests."""

    setUp = td.KitTest.setUp
    tearDown = td.KitTest.tearDown
    stop = td.KitTest.stop
    gv = td.KitTest.gv
    with_origin = td.KitTest.with_origin

    # ---- helpers ----
    def commit(self, msg: str = "c", cwd: Path | None = None) -> None:
        sh(cwd or self.root, "git", "add", "-A")
        sh(cwd or self.root, "git", *GIT, "commit", "-qm", msg)

    def set_check(self, body: str) -> None:
        (self.root / "scripts/check.sh").write_text("#!/usr/bin/env bash\n" + body)
        self.commit("check")

    def set_cfg(self, over: dict, root: Path | None = None, commit: bool = True) -> None:
        p = (root or self.root) / ".claude/project.json"
        cfg = json.loads(p.read_text())
        for k, v in over.items():
            cfg.setdefault(k, {}).update(v)
        p.write_text(json.dumps(cfg))
        if commit:
            self.commit("cfg")

    def counting_check(self, extra: str = "") -> Path:
        """A check.sh that counts its runs (outside the repo) and fails on BROKEN in app.py."""
        cnt = self.tmp / "runs"
        self.set_check(f'echo x >> "{cnt}"\necho "== stage: tests"\n{extra}'
                       'if grep -q BROKEN app.py; then echo "== failed: tests (0s)"; exit 1; fi\n'
                       'echo "== ok: tests (0s)"\n')
        return cnt

    def runs(self, cnt: Path) -> int:
        return len(cnt.read_text().splitlines()) if cnt.exists() else 0

    def log(self) -> list[dict]:
        p = self.root / ".claude/state/gate-log.jsonl"
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []

    def worktree(self, name: str = "wt", branch: str = "unit") -> Path:
        wt = self.tmp / name
        sh(self.root, "git", "worktree", "add", "-q", "-b", branch, str(wt))
        return wt

    def gate(self, cwd: Path, sid: str = "s", agent: str | None = None, mode: str | None = None):
        env = {"CLAUDE_PROJECT_DIR": str(self.root)}
        if mode:
            env["DEVACCEL_GATE_MODE"] = mode
        payload = {"session_id": sid, "cwd": str(cwd)}
        if agent:
            payload["agent_id"] = agent
        r = run(cwd, "python3", str(self.root / ".claude/hooks/stop_gate.py"), env=env, stdin=json.dumps(payload))
        self.assertEqual(r.returncode, 0, r.stderr)
        return (json.loads(r.stdout) if r.stdout.strip() else {}), r

    def settings(self) -> dict:
        return json.loads((self.root / ".claude/settings.json").read_text())

    def fake_bin(self, tools=("bwrap", "socat", "ruff", "pyright", "pytest")) -> Path:
        """A PATH that holds only git and the named fake tools (no gh): doctor becomes deterministic."""
        b = self.tmp / ("bin-" + "-".join(tools))
        if not b.exists():
            b.mkdir()
            os.symlink(shutil.which("git"), b / "git")
            for t in tools:
                (b / t).write_text("#!/bin/sh\nexit 0\n")
                (b / t).chmod(0o755)
        return b

    def doctor(self, tools=("bwrap", "socat", "ruff", "pyright", "pytest"), env: dict | None = None):
        r = run(self.root, sys.executable, str(DEVACCEL), "doctor",
                env={"PATH": str(self.fake_bin(tools)), **(env or {})})
        return r.returncode, r.stdout + r.stderr

    def fresh(self, name: str) -> Path:
        d = self.tmp / name
        d.mkdir()
        sh(d, "git", "init", "-q", "-b", "main")
        (d / "pyproject.toml").write_text('[project]\nname = "p"\nversion = "0"\n')
        return d


# ====================================================================== SETTINGS
class SettingsTest(ReqKit):
    def test_SET01_sandbox_flags(self):
        """SET-01: sandbox enabled / failIfUnavailable / autoAllowBashIfSandboxed true, allowUnsandboxed false."""
        sb = self.settings()["sandbox"]
        self.assertIs(sb["enabled"], True)
        self.assertIs(sb["failIfUnavailable"], True)
        self.assertIs(sb["autoAllowBashIfSandboxed"], True)
        self.assertIs(sb["allowUnsandboxedCommands"], False)

    def test_SET02_denyread_home_secrets_without_globs(self):
        """SET-02: denyRead names .env and home secrets directly; no ~/ glob, no ~/.config/gh."""
        deny = self.settings()["sandbox"]["filesystem"]["denyRead"]
        for p in ["~/.ssh", "~/.aws", "~/.gnupg", "~/.netrc", "~/.docker/config.json", "~/.kube", "~/.npmrc",
                  "~/.pypirc"]:
            self.assertIn(p, deny)
        self.assertTrue(any(".env" in p and p.startswith("./") for p in deny), deny)
        self.assertEqual([p for p in deny if p.startswith("~") and any(c in p for c in "*?[")], [])
        self.assertFalse(any(p.startswith("~/.config/gh") or p in ("~", "~/") for p in deny), deny)

    def test_SET03_read_edit_denies_are_secrets_only(self):
        """SET-03: permissions Read/Edit deny only .env patterns (never uv.lock, .venv, .claude/worktrees)."""
        deny = self.settings()["permissions"]["deny"]
        file_rules = [r for r in deny if r.startswith(("Read(", "Edit("))]
        self.assertTrue(file_rules)
        for r in file_rules:
            self.assertIn(".env", r, r)
        for bad in ("uv.lock", ".venv", "worktrees"):
            self.assertFalse(any(bad in r for r in deny), bad)

    def test_SET04_exact_git_allows_and_required_denies(self):
        """SET-04: git/check.sh allow entries are exact (no trailing wildcard); required denies present."""
        perms = self.settings()["permissions"]
        pr_path = {"Bash(git add *)", "Bash(git commit *)"}  # SET-05: guard-enforced parallel-PR path
        for r in perms["allow"]:
            if (r.startswith("Bash(git ") and r not in pr_path) or "check.sh" in r:
                self.assertNotIn("*", r, r)
        self.assertIn("Bash(scripts/check.sh fast)", perms["allow"])
        for r in ["Bash(git * --out*)", "Bash(git * --ext*)", "Bash(gh *)", "Bash(git push --force*)",
                  "Bash(git push -f *)", "Bash(git remote add *)", "Bash(git remote set-url *)"]:
            self.assertIn(r, perms["deny"])

    def test_SET05_parallel_pr_path_allowed(self):
        """SET-05: git add/commit, git push origin HEAD and the PR script are allowed; no Bash(git push*) ask."""
        perms = self.settings()["permissions"]
        for r in ["Bash(git add *)", "Bash(git commit *)", "Bash(git push origin HEAD)",
                  "Bash(python3 .claude/hooks/devaccel_pr.py *)"]:
            self.assertIn(r, perms["allow"])
        self.assertFalse(any(r.startswith("Bash(git push") for r in perms.get("ask", [])))

    def test_SET06_machinery_edits_ask_in_main_and_worktrees(self):
        """SET-06: Edit of check.sh / hooks / settings / project.json / workflows asks, plain and **/ forms."""
        ask = self.settings()["permissions"]["ask"]
        for p in ["scripts/check.sh", ".claude/hooks/**", ".claude/settings.json", ".claude/project.json",
                  ".github/workflows/**"]:
            self.assertIn(f"Edit(./{p})", ask)
            self.assertIn(f"Edit(**/{p})", ask)

    def test_SET07_hooks_wired_with_direct_python(self):
        """SET-07: PreToolUse(Bash)->guard, Stop and SubagentStop->stop_gate, direct python3 (no uv run)."""
        hooks = self.settings()["hooks"]
        pre = [h for e in hooks["PreToolUse"] if e.get("matcher") == "Bash" for h in e["hooks"]]
        self.assertEqual([h["command"] for h in pre], ['python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/guard.py'])
        for ev in ("Stop", "SubagentStop"):
            cmds = [h["command"] for e in hooks[ev] for h in e["hooks"]]
            self.assertEqual(cmds, ['python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/stop_gate.py'], ev)

    def test_SET08_domains_caches_env(self):
        """SET-08: github domains always, PyPI + npm and tool caches for python; env 3 subagents on sonnet."""
        st = self.settings()
        doms = st["sandbox"]["network"]["allowedDomains"]
        for d in ["github.com", "api.github.com", "pypi.org", "files.pythonhosted.org", "registry.npmjs.org"]:
            self.assertIn(d, doms)
        self.assertIn("~/.cache/uv", st["sandbox"]["filesystem"]["allowWrite"])
        self.assertEqual(st["env"]["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"], "3")
        self.assertEqual(st["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "sonnet")


# ====================================================================== INSTALL / UPDATE
class InstallUpdateTest(ReqKit):
    def test_INST01_lock_records_every_core_file(self):
        """INST-01: every core file is copied and its sha256 recorded; version and ref lines written."""
        lock = (self.root / ".claude/devaccel.lock").read_text().splitlines()
        self.assertIn("version " + (KIT / "VERSION").read_text().strip(), lock)
        self.assertTrue(any(ln.startswith("ref ") for ln in lock))
        core = KIT / "core"
        files = sorted(str(p.relative_to(core)) for p in core.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        recorded = {ln.split()[1]: ln.split()[0] for ln in lock if ln and ln[0] not in "#vr"}
        self.assertEqual(sorted(recorded), files)
        for f, h in recorded.items():
            self.assertEqual(hashlib.sha256((self.root / f).read_bytes()).hexdigest(), h, f)

    def test_INST02_INST04_existing_project_files_kept(self):
        """INST-02/INST-04: existing project-layer files (incl. settings.json) are not overwritten and are listed."""
        d = self.fresh("p2")
        mine = {"CLAUDE.md": "# mine\n", ".claude/project.json": '{"mine": 1}\n', "scripts/check.sh": "# mine\n",
                ".github/workflows/check.yml": "mine: 1\n", ".claude/settings.json": '{"mine": true}\n',
                ".claude/skills/design/SKILL.md": "mine\n"}
        for f, t in mine.items():
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text(t)
        r = sh(d, str(KIT / "install.sh"))
        self.assertEqual(r.returncode, 0, r.stdout)
        kept = next(ln for ln in r.stdout.splitlines() if ln.startswith("kept existing"))
        for f, t in mine.items():
            self.assertEqual((d / f).read_text(), t, f)
            self.assertIn(f, kept)
        # INST-04: settings.json not merged, the hook wiring to add is printed instead
        self.assertIn("does not merge", r.stdout)
        self.assertIn("hooks/stop_gate.py", r.stdout)
        self.assertIn("SubagentStop", r.stdout)

    def test_INST03_refuses_conflicting_core_and_writes_nothing(self):
        """INST-03: a differing file at a core path -> rc 1, no lock, no core/seed files written; no double install."""
        d = self.fresh("p3")
        (d / ".claude/hooks").mkdir(parents=True)
        (d / ".claude/hooks/guard.py").write_text("# my own guard\n")
        before = tree_hash(d)
        r = sh(d, str(KIT / "install.sh"))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn(".claude/hooks/guard.py", r.stdout)
        self.assertEqual(tree_hash(d), before)
        self.assertFalse((d / ".claude/devaccel.lock").exists())
        # already installed: refused, lock untouched
        lock = (self.root / ".claude/devaccel.lock").read_bytes()
        r = sh(self.root, str(KIT / "install.sh"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual((self.root / ".claude/devaccel.lock").read_bytes(), lock)

    def test_INST05_gitignore_appends_only_missing_lines(self):
        """INST-05: .gitignore keeps existing lines and gets each devaccel line exactly once."""
        d = self.fresh("p5")
        (d / ".gitignore").write_text("node_modules/\n.claude/state/\n__pycache__/")
        self.assertEqual(sh(d, str(KIT / "install.sh")).returncode, 0)
        lines = (d / ".gitignore").read_text().splitlines()
        self.assertIn("node_modules/", lines)
        for ln in [".claude/state/", ".claude/settings.local.json", ".claude/worktrees/", ".devaccel/", "__pycache__/"]:
            self.assertEqual(lines.count(ln), 1, (ln, lines))

    def test_INST06_python_project_generation(self):
        """INST-06: python project -> presets ["python"], executable check.sh with a runner, CI workflow."""
        d = self.fresh("p6")
        (d / "uv.lock").write_text("")
        self.assertEqual(sh(d, str(KIT / "install.sh")).returncode, 0)
        self.assertEqual(json.loads((d / ".claude/project.json").read_text())["presets"], ["python"])
        check = d / "scripts/check.sh"
        self.assertTrue(os.access(check, os.X_OK))
        self.assertIn('R="uv run"', check.read_text())
        wf = (d / ".github/workflows/check.yml").read_text()
        self.assertIn("setup-uv", wf)
        self.assertIn("scripts/check.sh full", wf)

    def test_UPD01_refuses_without_lock_or_with_hand_edit_changing_nothing(self):
        """UPD-01: no lock -> rc 1 and nothing changed; a hand-edited core file -> rc 1 and nothing changed."""
        (self.root / ".claude/devaccel.lock").unlink()
        before = tree_hash(self.root)
        r = sh(self.root, str(KIT / "update.sh"))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(tree_hash(self.root), before)
        sh(self.root, "git", "checkout", "-q", "--", ".claude/devaccel.lock")
        # an old core file the kit would replace + a hand edit elsewhere: refuse, change nothing
        old = self.root / ".claude/hooks/devaccel_report.py"
        lock = self.root / ".claude/devaccel.lock"
        h = hashlib.sha256(old.read_bytes()).hexdigest()
        old.write_text(old.read_text() + "# older version\n")
        lock.write_text(lock.read_text().replace(h, hashlib.sha256(old.read_bytes()).hexdigest()))
        g = self.root / ".claude/hooks/guard.py"
        g.write_text(g.read_text() + "\n# hack\n")
        before = tree_hash(self.root)
        r = sh(self.root, str(KIT / "update.sh"))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("+# hack", r.stdout.replace("-# hack", "+# hack"))  # the diff is shown
        self.assertEqual(tree_hash(self.root), before)

    def kit_copy(self) -> Path:
        k = self.tmp / "kit"
        for d in ("core", "kit", "seed"):
            shutil.copytree(KIT / d, k / d, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(KIT / "VERSION", k / "VERSION")
        return k

    def update_with(self, kit: Path) -> subprocess.CompletedProcess:
        return run(self.root, sys.executable, str(kit / "kit/devaccel.py"), "update")

    def test_UPD03_lock_matches_new_core_after_update(self):
        """UPD-03: after a successful update every lock hash equals the new core file's sha256."""
        k = self.kit_copy()
        p = k / "core/.claude/hooks/devaccel_report.py"
        p.write_text(p.read_text() + "# new kit version\n")
        r = self.update_with(k)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(".claude/hooks/devaccel_report.py", r.stdout)
        lock = (self.root / ".claude/devaccel.lock").read_text().splitlines()
        recorded = {ln.split()[1]: ln.split()[0] for ln in lock if ln and ln[0] not in "#vr"}
        self.assertIn(".claude/hooks/devaccel_report.py", recorded)
        for f, h in recorded.items():
            self.assertEqual(hashlib.sha256((self.root / f).read_bytes()).hexdigest(), h, f)
            self.assertEqual(h, hashlib.sha256((k / "core" / f).read_bytes()).hexdigest(), f)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores file modes")
    def test_UPD03_staging_failure_changes_nothing(self):
        """UPD-03: if staging fails (unreadable kit file), the project is left unchanged."""
        k = self.kit_copy()
        g = k / "core/.claude/hooks/guard.py"  # sorts before stop_gate.py: would be replaced first
        g.write_text(g.read_text() + "# new\n")
        bad = k / "core/.claude/hooks/stop_gate.py"
        bad.chmod(0)
        try:
            before = tree_hash(self.root)
            r = self.update_with(k)
        finally:
            bad.chmod(stat.S_IRUSR | stat.S_IWUSR)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(tree_hash(self.root), before)
        self.assertEqual(list((self.root / ".claude").glob(".devaccel-staging-*")), [])

    def test_UPD03_new_core_path_clash_refused(self):
        """UPD-03: a path that becomes core in the new kit but holds a user's file -> refused, nothing changed."""
        k = self.kit_copy()
        (k / "core/.claude/hooks/devaccel_new.py").write_text("# kit\n")
        (self.root / ".claude/hooks/devaccel_new.py").write_text("# mine\n")
        before = tree_hash(self.root)
        r = self.update_with(k)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("devaccel_new.py", r.stdout)
        self.assertEqual(tree_hash(self.root), before)


# ====================================================================== DOCTOR / PROTECT
class DoctorTest(ReqKit):
    def mutate(self, rel: str, fn):
        p = self.root / rel
        orig = p.read_bytes() if p.exists() else None
        mode = p.stat().st_mode if p.exists() else None

        def restore():
            if not self.root.exists():  # cleanups run after tearDown removed the fixture
                return
            if orig is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(orig)
                os.chmod(p, mode)
        self.addCleanup(restore)
        fn(p)
        return restore

    def edit_settings(self, fn):
        def f(p: Path) -> None:
            st = json.loads(p.read_text())
            fn(st)
            p.write_text(json.dumps(st))
        return self.mutate(".claude/settings.json", f)

    def assertProblem(self, msg: str, **kw) -> None:
        rc, out = self.doctor(**kw)
        self.assertEqual(rc, 1, out)
        self.assertTrue(any(ln.startswith("✗ ") and msg in ln for ln in out.splitlines()), (msg, out))

    def test_DOC01_clean_ok_problem_rc1_and_read_only(self):
        """DOC-01: clean install -> `OK` and rc 0, files untouched; any problem -> rc 1."""
        before = tree_hash(self.root)
        rc, out = self.doctor()
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.strip().splitlines()[-1], "OK")
        self.assertNotIn("✗", out)
        self.assertEqual(tree_hash(self.root), before)
        (self.root / ".claude/hooks/devaccel_report.py").unlink()
        rc, out = self.doctor()
        self.assertEqual(rc, 1, out)
        self.assertIn("1 problem(s)", out)

    def test_DOC02_missing_and_hand_edited_core(self):
        """DOC-02: a missing core file and a hand-edited one are problems."""
        self.mutate(".claude/hooks/devaccel_report.py", lambda p: p.unlink())
        self.assertProblem("core file missing: .claude/hooks/devaccel_report.py")
        self.mutate(".claude/hooks/guard.py", lambda p: p.write_text(p.read_text() + "# hack\n"))
        self.assertProblem("core file edited by hand: .claude/hooks/guard.py")

    def test_DOC03_unwired_hooks(self):
        """DOC-03: SubagentStop unwired -> problem with the snippet to add; guard/stop unwired -> problem."""
        undo = self.edit_settings(lambda st: st["hooks"].pop("SubagentStop"))
        rc, out = self.doctor()
        self.assertEqual(rc, 1, out)
        self.assertIn("SubagentStop is not wired", out)
        self.assertIn('{"SubagentStop": [{"hooks": [{"type": "command", "command": "python3', out)
        undo()
        self.edit_settings(lambda st: st["hooks"].pop("PreToolUse"))
        self.assertProblem("hooks not wired in .claude/settings.json")

    def test_DOC04_sandbox_and_permission_drift(self):
        """DOC-04: sandbox off, bwrap/socat missing, $HOME glob denyRead, bad Read denies, git push ask, no api.github."""
        cases = [
            ("sandbox not enabled", lambda st: st["sandbox"].update(enabled=False)),
            ("scans all of $HOME", lambda st: st["sandbox"]["filesystem"]["denyRead"].append("~/**/.env")),
            ("breaks git/uv/worktrees", lambda st: st["permissions"]["deny"].append("Read(/uv.lock)")),
            ("breaks git/uv/worktrees", lambda st: st["permissions"]["deny"].append("Read(/.venv/**)")),
            ("breaks git/uv/worktrees", lambda st: st["permissions"]["deny"].append("Read(/.claude/worktrees/**)")),
            ("blocks parallel PR units", lambda st: st["permissions"]["ask"].append("Bash(git push*)")),
            ("lacks api.github.com", lambda st: st["sandbox"]["network"]["allowedDomains"].remove("api.github.com")),
        ]
        for msg, fn in cases:
            with self.subTest(msg):
                undo = self.edit_settings(fn)
                self.assertProblem(msg)
                undo()
        self.assertProblem("bubblewrap/socat missing", tools=("socat", "ruff", "pyright", "pytest"))

    def test_DOC05_check_gitignore_budget_tools(self):
        """DOC-05: check.sh missing/non-exec/empty, gitignore lines, CLAUDE.md budget, python tools missing."""
        cases = [
            ("scripts/check.sh", lambda p: p.chmod(0o644), "scripts/check.sh missing or not executable"),
            ("scripts/check.sh", lambda p: p.write_text(p.read_text() + 'echo "no checks configured"\n'),
             "scripts/check.sh has no checks"),
            (".gitignore", lambda p: p.write_text(p.read_text().replace(".devaccel/\n", "")),
             ".devaccel/ not gitignored"),
            (".gitignore", lambda p: p.write_text(p.read_text().replace(".claude/state/\n", "")),
             ".claude/state/ not gitignored"),
            ("CLAUDE.md", lambda p: p.write_text("x\n" * 100), "CLAUDE.md is 100 lines (budget 60)"),
        ]
        for rel, fn, msg in cases:
            with self.subTest(msg):
                undo = self.mutate(rel, fn)
                self.assertProblem(msg)
                undo()
        self.assertProblem("pyright not found", tools=("bwrap", "socat", "ruff", "pytest"))

    def test_DOC06_fill_markers(self):
        """DOC-06: unfilled devaccel:fill markers are shown; devaccel:filled is not treated as unfilled."""
        cm = self.root / "CLAUDE.md"
        cm.write_text("# p\n<!-- devaccel:filled -->\n")
        _, out = self.doctor()
        self.assertNotIn("CLAUDE.md still has devaccel:fill", out)
        cm.write_text("# p\n<!-- devaccel:fill name -->\n")
        rc, out = self.doctor()
        self.assertIn("· CLAUDE.md still has devaccel:fill placeholders", out)
        self.assertEqual(rc, 0, out)  # a note, not a problem

    def test_DOC07_notes_are_not_problems(self):
        """DOC-07: gate modes, observe advice, personal override, untrusted workspace, gate stats are notes only."""
        self.set_cfg({"gate": {"mode": "observe"}}, commit=False)
        (self.root / ".claude/settings.local.json").write_text('{"env": {"DEVACCEL_GATE_MODE": "enforce"}}')
        (self.root / ".claude/state").mkdir(exist_ok=True)
        (self.root / ".claude/state/gate-log.jsonl").write_text(
            json.dumps({"ts": "2026-01-01T00:00:00", "result": "pass", "secs": 1}) + "\n")
        home = self.tmp / "home"
        home.mkdir()
        rc, out = self.doctor(env={"HOME": str(home)})
        self.assertEqual(rc, 0, out)
        for note in ["· gate: session=observe unit=enforce", "· gate.mode=observe runs check.sh every turn",
                     "· personal override DEVACCEL_GATE_MODE", "· workspace not trusted yet", "· gate runs=1"]:
            self.assertIn(note, out)

    def test_DOC08_protect_only_on_yes_with_required_payload(self):
        """DOC-08: protect changes GitHub only after `yes`, with the required protection payload."""
        sh(self.root, "git", "remote", "add", "origin", "https://github.com/o/r.git")
        b = self.fake_bin()
        log, body = self.tmp / "gh.log", self.tmp / "gh.in"
        (b / "gh").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n{shutil.which("cat")} > "{body}"\n')
        (b / "gh").chmod(0o755)
        r = run(self.root, sys.executable, str(DEVACCEL), "protect", env={"PATH": str(b)}, stdin="no\n")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(log.exists())
        r = run(self.root, sys.executable, str(DEVACCEL), "protect", env={"PATH": str(b)}, stdin="yes\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(log.read_text().strip(), "api -X PUT repos/o/r/branches/main/protection --input -")
        p = json.loads(body.read_text())
        self.assertIs(p["enforce_admins"], True)
        self.assertIs(p["allow_force_pushes"], False)
        self.assertIs(p["allow_deletions"], False)
        self.assertEqual(p["required_pull_request_reviews"]["required_approving_review_count"], 0)
        self.assertEqual(p["required_status_checks"], {"strict": False, "checks": [{"context": "check", "app_id": 15368}]})


# ====================================================================== GATE
class GateTest(ReqKit):
    def test_GATE03_worktree_config_cannot_relax_unit_gate(self):
        """GATE-03: a unit's own project.json (unit_mode off, max_rounds 0) does not change its gate."""
        wt = self.worktree()
        self.set_cfg({"gate": {"unit_mode": "off", "mode": "off", "max_rounds": 0}}, root=wt, commit=False)
        (wt / "app.py").write_text("BROKEN\n")
        reply, r = self.gate(wt, agent="a1")
        self.assertEqual(reply.get("decision"), "block", r.stdout + r.stderr)
        self.assertIn("1/3", reply["reason"])

    def test_GATE15_env_override_is_session_only_and_validated(self):
        """GATE-15: DEVACCEL_GATE_MODE=off leaves units enforced; an invalid value is ignored."""
        wt = self.worktree()
        (wt / "app.py").write_text("BROKEN\n")
        reply, r = self.gate(wt, agent="a1", mode="off")
        self.assertEqual(reply.get("decision"), "block", r.stdout + r.stderr)
        cnt = self.counting_check()
        (self.root / "app.py").write_text("BROKEN\n")
        reply, _ = self.gate(self.root, mode="bogus")  # project mode is off (default): bogus must not enable it
        self.assertEqual(reply, {})
        self.assertEqual(self.runs(cnt), 0)

    def test_GATE08_skip_branch_and_unchanged_since_pass(self):
        """GATE-08: no check.sh run on spike/* branches, nor for a tree unchanged since a pass (after auto-format)."""
        cnt = self.counting_check(extra="sed -i 's/X=/X = /' app.py\n")
        (self.root / "app.py").write_text("X=5\n")
        self.assertNotIn("decision", self.stop())
        self.assertEqual(self.runs(cnt), 1)
        self.assertEqual((self.root / "app.py").read_text(), "X = 5\n")  # auto-formatted by the "check"
        self.assertEqual(self.stop(), {})
        self.assertEqual(self.runs(cnt), 1)  # remembered as passed in its formatted state
        sh(self.root, "git", "checkout", "-q", "-b", "spike/x")
        (self.root / "app.py").write_text("BROKEN\n")
        self.assertEqual(self.stop(session="s2"), {})
        self.assertEqual(self.runs(cnt), 1)

    def test_GATE09_timeout_is_not_a_pass(self):
        """GATE-09: a check.sh timeout is reported and logged as unverified and re-run on the next stop."""
        self.set_cfg({"gate": {"timeout_sec": 1}})
        cnt = self.counting_check(extra="sleep 3\n")
        (self.root / "app.py").write_text("X = 2\n")
        reply = self.stop()
        self.assertIn("打ち切", reply.get("systemMessage", ""))
        self.assertNotIn("decision", reply)
        self.assertEqual(self.log()[-1]["result"], "timeout")
        self.stop()
        self.assertEqual(self.runs(cnt), 2)

    def test_GATE13_notices_never_block_and_show_once(self):
        """GATE-13: scale/risky/test-deletion/skip notices go to systemMessage only, once per kind per session."""
        (self.root / "tests").mkdir()
        (self.root / "tests/test_a.py").write_text("def test_a():\n    assert 1\n")
        self.commit("tests")
        sh(self.root, "git", "rm", "-q", "tests/test_a.py")
        (self.root / "tests").mkdir(exist_ok=True)
        (self.root / "tests/test_b.py").write_text("import pytest\n\n\n@pytest.mark.skip\ndef test_b():\n    pass\n")
        (self.root / "auth").mkdir()
        (self.root / "auth/x.py").write_text("Z = 1\n")
        sh(self.root, "git", "add", "-A")
        reply = self.stop()
        self.assertNotIn("decision", reply)
        msg = reply.get("systemMessage", "")
        for word in ("L相当", "auth/x.py", "削除", "skip"):
            self.assertIn(word, msg)
        (self.root / "app.py").write_text("X = 7\n")
        self.assertEqual(self.stop(), {})  # same kinds again: not repeated

    def test_GATE05_block_carries_only_failed_stage_tail(self):
        """GATE-05: the block reason names the failed stage, its last <=40 lines only, and the round."""
        self.set_check('echo "== stage: lint"; for i in $(seq 100); do echo lintline$i; done; echo "== ok: lint (0s)"\n'
                       'echo "== stage: tests"\n'
                       'if grep -q BROKEN app.py; then for i in $(seq 100); do echo testline$i; done\n'
                       '  echo "== failed: tests (0s)"; exit 1; fi\necho "== ok: tests (0s)"\n')
        (self.root / "app.py").write_text("BROKEN\n")
        reply = self.stop()
        self.assertEqual(reply.get("decision"), "block")
        reason = reply["reason"]
        self.assertIn("`tests`", reason)
        self.assertIn("1/3", reason)
        self.assertIn("testline100", reason)
        self.assertIn("testline61\n", reason)
        self.assertNotIn("testline60\n", reason)
        self.assertNotIn("lintline", reason)

    def test_GATE05_GATE16_committed_unmerged_unit_work_is_checked(self):
        """GATE-05/GATE-16: a unit that committed a broken change (clean tree) is still blocked at SubagentStop."""
        wt = self.worktree()
        (wt / "app.py").write_text("BROKEN\n")
        self.commit("unit work", cwd=wt)
        self.assertEqual(sh(wt, "git", "status", "--porcelain").stdout, "")
        reply, r = self.gate(wt, agent="a1")
        self.assertEqual(reply.get("decision"), "block", r.stdout + r.stderr)
        self.assertEqual(self.log()[-1]["scope"], "unit")

    def test_GATE06_escalation_message_and_log(self):
        """GATE-06: past max_rounds the human gets a systemMessage and `escalate` is logged."""
        for i in range(4):
            (self.root / "app.py").write_text(f"BROKEN {i}\n")
            reply = self.stop()
        self.assertIn("判断が必要", reply.get("systemMessage", ""))
        self.assertEqual(self.log()[-1]["result"], "escalate")

    def test_GATE07_repeat_stop_counts_rounds(self):
        """GATE-07: stopping again on an unchanged failed tree re-blocks and advances the round."""
        (self.root / "app.py").write_text("BROKEN\n")
        self.assertIn("1/3", self.stop()["reason"])
        self.assertIn("2/3", self.stop()["reason"])

    def test_GATE10_corrupt_state_and_invalid_config(self):
        """GATE-10: a garbage state file or invalid project.json does not lose the block; config error on stderr."""
        (self.root / "app.py").write_text("BROKEN\n")
        gate_dir = self.root / ".claude/state/gate"
        gate_dir.mkdir(parents=True, exist_ok=True)
        (gate_dir / "s.json").write_text("{not json")
        self.assertEqual(self.stop().get("decision"), "block")
        (self.root / ".claude/project.json").write_text("{broken")
        reply, r = self.gate(self.root, sid="s2", mode="enforce")
        self.assertEqual(reply.get("decision"), "block", r.stderr)
        self.assertIn("invalid JSON", r.stderr)

    def test_GATE11_rounds_are_per_session(self):
        """GATE-11: two sessions/units failing in turn keep independent round counters."""
        (self.root / "app.py").write_text("BROKEN 1\n")
        self.assertIn("1/3", self.stop(session="a")["reason"])
        self.assertIn("1/3", self.stop(session="b")["reason"])
        (self.root / "app.py").write_text("BROKEN 2\n")
        self.assertIn("2/3", self.stop(session="a")["reason"])

    def test_GATE12_log_in_trusted_root_with_fields(self):
        """GATE-12: unit runs log to the main checkout only, with branch/scope/mode/result."""
        wt = self.worktree()
        (wt / "app.py").write_text("BROKEN\n")
        self.gate(wt, agent="a1")
        self.assertFalse((wt / ".claude/state").exists())
        ev = self.log()[-1]
        self.assertEqual((ev["branch"], ev["scope"], ev["mode"], ev["result"]), ("unit", "unit", "enforce", "fail"))
        self.assertTrue(list((self.root / ".claude/state/gate").glob("a1.json")))

    def test_GATE14_missing_trusted_check_is_not_replaced_by_worktree(self):
        """GATE-14: no check.sh in the trusted root -> `missing` (never the worktree's own check.sh)."""
        wt = self.worktree()
        (self.root / "scripts/check.sh").unlink()
        (wt / "app.py").write_text("BROKEN\n")
        reply, _ = self.gate(wt, agent="a1")
        self.assertNotIn("decision", reply)
        self.assertIn("未検査", reply.get("systemMessage", ""))
        self.assertEqual(self.log()[-1]["result"], "missing")


# ====================================================================== GUARD
class GuardReqTest(unittest.TestCase):
    def v(self, cmd: str, cfg: dict | None = None):
        r = guard.decide(cmd, cfg or DEFAULTS)
        return r[0] if r else None

    def test_GRD01_broad_rm_targets(self):
        """GRD-01: rm -rf of $HOME and .git (also quoted) is denied."""
        for cmd in ["rm -rf $HOME", 'rm -rf "$HOME"', "rm -rf .git", "rm -fr .git/"]:
            self.assertEqual(self.v(cmd), "deny", cmd)
        self.assertIsNone(self.v("rm -rf .github_cache"))

    def test_GRD02_external_command_and_output_options(self):
        """GRD-02: git -c core.editor, git show --output, ${IFS}-split --output/--ext-diff are denied."""
        for cmd in ["git -c core.editor=x commit", "git show --output=x", "git diff${IFS}--output=x",
                    "git log${IFS}--ext-diff"]:
            self.assertEqual(self.v(cmd), "deny", cmd)

    def test_GRD03_ask_words_inside_strings_do_not_fire(self):
        """GRD-03: git ask rules apply only at a segment start, not to words inside a string."""
        self.assertIsNone(self.v('echo "git add -A"'))
        self.assertIsNone(self.v("echo 'run git reset --hard later'"))
        self.assertEqual(self.v("git add -A"), "ask")

    def test_GRD05_gh_behind_wrapper(self):
        """GRD-05: gh behind a `timeout` wrapper is denied."""
        self.assertEqual(self.v("timeout 5 gh pr list"), "deny")

    def test_GRD09_pty_wrappers(self):
        """GRD-09: expect / empty / socat pseudo-terminal wrappers are denied."""
        for cmd in ["expect x", "empty -f x", "socat - x"]:
            self.assertEqual(self.v(cmd), "deny", cmd)

    def test_GRD10_ask_regex_applies(self):
        """GRD-10: a valid project guard.ask_regex is applied."""
        cfg = json.loads(json.dumps(DEFAULTS))
        cfg["guard"]["ask_regex"] = [r"\bterraform\s+apply\b"]
        self.assertEqual(self.v("terraform apply", cfg), "ask")
        self.assertIsNone(self.v("terraform plan", cfg))

    def test_GRD10_internal_error_asks(self):
        """GRD-10: an internal error in the guard yields `ask`, never a silent allow."""
        r = run(KIT, sys.executable, str(KIT / "core/.claude/hooks/guard.py"), stdin=json.dumps({"tool_input": "x"}))
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "ask")
        self.assertIn("internal error", out["permissionDecisionReason"])

    def test_GRD11_ordinary_commands_pass(self):
        """GRD-11: git commit -F file and heredoc file creation mentioning ask words are not denied/asked."""
        for cmd in ["git commit -F msg.txt", "git commit -F .devaccel/msg.txt",
                    "cat > notes.md <<'EOF'\nnotes: git add -A, git reset --hard\nEOF"]:
            self.assertIsNone(self.v(cmd), cmd)


class GuardKitTest(ReqKit):
    def test_GRD04_push_from_protected_or_detached(self):
        """GRD-04: push denied from master, custom base_branch, origin default branch, detached HEAD; GIT_DIR=."""
        self.set_cfg({"scale": {"base_branch": "trunk"}})
        sh(self.root, "git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
        for br in ["master", "trunk", "develop"]:
            sh(self.root, "git", "checkout", "-q", "-B", br)
            self.assertEqual(self.gv("git push origin HEAD"), "deny", br)
        sh(self.root, "git", "checkout", "-q", "-B", "feat")
        self.assertIsNone(self.gv("git push origin HEAD"))
        for cmd in ["GIT_DIR=.git git push origin HEAD", "git config credential.helper store",
                    "git config push.default current"]:
            self.assertEqual(self.gv(cmd), "deny", cmd)
        sh(self.root, "git", "checkout", "-q", "--detach")
        self.assertEqual(self.gv("git push origin HEAD"), "deny")

    def test_GRD06_pr_script_not_combined(self):
        """GRD-06: devaccel_pr.py with alias / cd / a pipe to another command is denied."""
        sh(self.root, "git", "checkout", "-qb", "feat")
        self.assertIsNone(self.gv("python3 .claude/hooks/devaccel_pr.py --title t"))
        for cmd in ["alias python3=sh; python3 .claude/hooks/devaccel_pr.py --title x",
                    "cd x; python3 .claude/hooks/devaccel_pr.py --title x",
                    "python3 .claude/hooks/devaccel_pr.py --title x | tee y"]:
            self.assertEqual(self.gv(cmd), "deny", cmd)

    def test_GRD08_lock_missing_or_dependency_tampered(self):
        """GRD-08: PR script denied when the lock is missing or devaccel_common.py / stop_gate.py differ."""
        sh(self.root, "git", "checkout", "-qb", "feat")
        cmd = "python3 .claude/hooks/devaccel_pr.py --title t"
        self.assertIsNone(self.gv(cmd))
        lock = self.root / ".claude/devaccel.lock"
        saved = lock.read_bytes()
        lock.unlink()
        self.assertEqual(self.gv(cmd), "deny")
        lock.write_bytes(saved)
        for name in ("devaccel_common.py", "stop_gate.py"):
            with self.subTest(name):
                p = self.root / ".claude/hooks" / name
                orig = p.read_bytes()
                p.write_bytes(orig + b"\n# hack\n")
                self.assertEqual(self.gv(cmd), "deny", name)
                p.write_bytes(orig)

    def test_GRD08_guard_config_from_trusted_root(self):
        """GRD-08: guard rules come from the main checkout's project.json, not the worktree's."""
        wt = self.worktree()
        self.set_cfg({"guard": {"deny_regex": [r"\bforbidden_tool\b"]}}, commit=False)
        r = run(wt, sys.executable, str(self.root / ".claude/hooks/guard.py"), env={"CLAUDE_PROJECT_DIR": str(self.root)},
                stdin=json.dumps({"cwd": str(wt), "tool_input": {"command": "forbidden_tool run"}}))
        self.assertIn('"deny"', r.stdout, r.stderr)


if __name__ == "__main__":
    unittest.main()
