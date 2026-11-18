> **0.9.0・0.10.0 で更新**: この表は監査時点(テスト 34 本・要件 94 件)のもの。その後 `tests/test_requirements.py` に 51 本(0.9.0)と 0.10.x の監査修正分を追加した。追加したテストはすべて、対応するコードを戻すと失敗することを確認済み(各回の内訳は test_requirements.py 冒頭の表)。§2 の穴のうち SET-01..08、INST-01..06、UPD-01/03、DOC-01..08、GATE-03/05..15/16(単位のコミット済み変更)、GRD-01..06/08..11 を埋めた。空振りしていた 2 本(GATE-08 の docs スキップ、GATE-03 の unit_mode 改ざん)も修正。残りは requirements.md §5。

# devaccel requirement ↔ test traceability

Audit date 2026-11-18, against `docs/requirements.md` (94 requirements, devaccel 0.8.4) and the test assets as they stand:
`tests/test_devaccel.py` (34 unittest cases, all passing; CI job `test`), `tests/integration/generated_check.sh` (CI job `integration`),
`tests/smoke/release_smoke.py` (manual, real Claude Code), `tests/bench/` (measurement only).

Criterion: **yes** = an existing test would fail if the requirement were violated. **partial** = some clauses are guarded, others are not
(or the assertion is too weak). **no** = nothing would fail. Touching the code is not coverage. RISK-xx rows are non-guarantees and are not listed.

Abbreviations: `T::` = `tests/test_devaccel.py::KitTest` (or `GuardTest` where noted), `IT` = `tests/integration/generated_check.sh`,
`SMOKE[n]` = step n of `tests/smoke/release_smoke.py`, `BENCH` = `tests/bench/bench.py` + `summarize.py`.

Summary: **yes 6 / partial 52 / no 36**.

## 1. Table

### INSTALL

| ID | covered? | test(s) | note |
|---|---|---|---|
| INST-01 | partial | T::test_install_layout; T::test_update_refuses_hand_edit_then_succeeds (indirect) | Only checks that the lock exists and that one core file exists. Nothing checks that every core file is copied, that each sha256 is recorded, or that version/ref are written. |
| INST-02 | no | — | No test pre-creates CLAUDE.md, project.json, check.sh, check.yml or settings.json and checks that they survive or are listed. |
| INST-03 | partial | T::test_install_layout (second install → rc 1) | Only covers the case where a lock already exists. Not covered: a differing file at a core path, and "no lock written" after refusal. |
| INST-04 | no | — | No test for an existing settings.json being left unchanged, or for the printed hook-wiring snippet. |
| INST-05 | partial | T::test_install_layout (`.claude/state/` in .gitignore) | Only one of the five lines is checked. Not covered: existing lines kept, no duplicates on a pre-filled .gitignore. |
| INST-06 | partial | IT (runs `scripts/check.sh` directly, uv project) | Covers an executable check.sh with the uv runner. Not covered: `presets=["python"]`, the PATH runner, and the generated CI workflow. Unit setUp overwrites check.sh, so the generated file is only tested in IT. |
| INST-07 | partial | IT | Covers lint and type failures, fast ok stages, and `.claude/hooks/*.py` untouched. Not covered: test-failure detection, "files not modified" (only hooks are hashed), tool-missing → full fails / fast `missing`, and 0 tests → success. |
| INST-08 | no | — | CI runs Python 3.12 only and pyrightconfig pins 3.10, so a 3.8-incompatible construct would pass. Nothing checks that the installed project is independent of the kit clone path. |

### UPDATE

| ID | covered? | test(s) | note |
|---|---|---|---|
| UPD-01 | partial | T::test_update_refuses_hand_edit_then_succeeds | Covers rc 1 and the diff message. Not covered: "changed nothing" after refusal (no hash comparison), and a missing lock → rc 1. |
| UPD-02 | partial | T::test_update_never_touches_project_files | Only CLAUDE.md is checked. Not covered: check.sh, project.json, settings.json, seed skills and local layer. |
| UPD-03 | no | — | No staging-failure test. The lock is not compared with the new hashes after update. |
| UPD-04 | partial | T::test_update_ignores_malicious_lock_entries | Covers `../` and a path outside `.claude/`. Not covered: absolute paths, symlinks, and the warning text. |

### DOCTOR / PROTECT

| ID | covered? | test(s) | note |
|---|---|---|---|
| DOC-01 | no | — | Doctor's exit code is never asserted, and the "doesn't modify files" clause is untested. |
| DOC-02 | no | T::test_update_refuses_hand_edit_then_succeeds (negative only) | That test only asserts doctor does *not* report after the file is reverted. Nothing asserts that doctor reports a hand edit or a missing file. |
| DOC-03 | no | — | Note: the requirement says SubagentStop is "displayed", but §4 #9 says it became a problem in 0.9.0. The text needs reconciling. |
| DOC-04 | no | — | None of the sandbox, denyRead, deny or ask checks is exercised. |
| DOC-05 | no | — | |
| DOC-06 | no | — | |
| DOC-07 | no | — | |
| DOC-08 | no | — | No fake-gh test for protect. |

### SETTINGS

| ID | covered? | test(s) | note |
|---|---|---|---|
| SET-01 | no | — | The generated settings.json is never inspected except for one key (see SET-07). |
| SET-02 | no | — | This is the 0.8.1 regression (`~/` glob): it is unguarded at unit level. Only SMOKE[1] latency would notice it indirectly. |
| SET-03 | no | — | 0.6.4/0.7.2 regressions. Only SMOKE[2] would notice them indirectly. |
| SET-04 | no | — | GuardTest covers the guard, not the permissions allow/deny lists. |
| SET-05 | no | — | |
| SET-06 | no | — | |
| SET-07 | partial | T::test_settings_wire_subagent_stop | Only SubagentStop→stop_gate is checked. Not covered: Stop, PreToolUse(Bash)→guard, and the `python3 "$CLAUDE_PROJECT_DIR"/…` form without `uv run`. |
| SET-08 | no | — | |
| SET-09 | partial | SMOKE[1] (`uv run python -c pass`), SMOKE[2] (worktree edit, Write, commit, 0 denials) | Not covered: `git stash` / merge. Step 1 doesn't check that the commands succeeded or weren't denied. |
| SET-10 | no | — | |

### GATE

| ID | covered? | test(s) | note |
|---|---|---|---|
| GATE-01 | yes | T::test_gate_defaults_off_in_session_enforce_in_units (no output, no log ⇒ check.sh not run); T::test_gate_observe_never_blocks | |
| GATE-02 | partial | T::test_gate_defaults_off_in_session_enforce_in_units (worktree → block, `scope: unit`) | Not covered: robustness to symlinks and path case (0.8.3). |
| GATE-03 | partial | T::test_gate_checks_the_worktree_not_the_main_checkout | The check.sh tamper is guarded. The project.json tamper is **ineffective**: it writes `gate.mode=off`, but units use `unit_mode`, and the env forces enforce anyway. The test would pass even if config were read from the worktree. |
| GATE-04 | yes | T::test_gate_checks_the_worktree_not_the_main_checkout (cwd=worktree with CLAUDE_PROJECT_DIR=main blocks; hostile worktree name creates no `PWNED`; unrelated repo cwd ignored) | |
| GATE-05 | partial | T::test_gate_rounds_then_escalate ("1/3") | Not asserted: the stage name in the reason, the tail ≤40 lines, and that only the failed stage's output is included. |
| GATE-06 | partial | T::test_gate_rounds_then_escalate (4th reason "判断を仰いで", then unchanged → `{}`) | Not asserted: `systemMessage` and the `escalate` log record. |
| GATE-07 | partial | T::test_gate_review_fixes (re-stop blocks, `repeat: true` logged) | The round count increasing on a repeat stop is not asserted. |
| GATE-08 | no | T::test_gate_ignores_docs_only (vacuous) | The docs-only test is **vacuous**: the stub check.sh only greps app.py, so it passes even if the gate runs it on README.md. Not covered: outside git, `skip_branches`, "unchanged since pass → not re-run", and signature after auto-format. |
| GATE-09 | no | — | No timeout test, and no check of the 110 s cap. |
| GATE-10 | partial | T::test_gate_review_fixes (non-UTF-8 file names still block) | Not covered: corrupt state file, invalid project.json, and the internal-error stderr message. |
| GATE-11 | partial | T::test_gate_review_fixes (`state/gate/*.json` exists) | Only checks that some per-session file exists. Not covered: two agent_ids keeping independent rounds, and emit-before-save. |
| GATE-12 | partial | T::test_gate_checks_the_worktree… (log in main checkout, branch); T::test_gate_defaults… (scope); T::test_gate_review_fixes (result, repeat) | Not asserted: no `.claude/state` written inside the worktree, the `mode` field, and escalation on a repeat stop being logged. |
| GATE-13 | no | — | No notice tests: scale, risky paths, test deletion, skip/xfail, and once-per-session. |
| GATE-14 | partial | T::test_gate_review_fixes (`cd /tmp` → not block, `result: missing`) | Not covered: check.sh absent from the trusted root. |
| GATE-15 | partial | T::test_gate_pass_and_off (env off in session) | Not covered: env `off` must not disable the unit gate (§4 #10 fix), and invalid values being ignored. |
| GATE-16 | no | SMOKE[2] runs a worktree subagent but never inspects gate-log.jsonl. | |

### GUARD

| ID | covered? | test(s) | note |
|---|---|---|---|
| GRD-01 | partial | GuardTest::test_deny | Not covered: `$HOME` and `.git` targets. The code currently denies both, so only the test is missing. |
| GRD-02 | partial | GuardTest::test_deny, test_ask | `${IFS}` is only asserted as ask-or-deny, but the requirement says deny (the code denies today). Not covered: `-c core.editor` and `git show --output`. |
| GRD-03 | partial | GuardTest::test_ask; KitTest::test_push_policy (heredoc in commit msg allowed) | No test that git ask words inside a string (`echo "git add -A"`) don't fire. |
| GRD-04 | partial | KitTest::test_push_policy | Not covered: custom `base_branch`, `master`, origin default branch, detached HEAD, `GIT_DIR=`, and credential / push config changes. |
| GRD-05 | partial | KitTest::test_push_policy | Not covered: the `timeout gh …` wrapper. |
| GRD-06 | partial | KitTest::test_land_policy_in_guard | Not covered: `alias`, `cd` + pr.py, and pr.py piped into another command. |
| GRD-07 | yes | KitTest::test_land_policy_in_guard | |
| GRD-08 | partial | KitTest::test_pr_script_must_match_lock; test_land_policy_in_guard; test_gate_checks_the_worktree… (worktree lock forged → deny) | Not covered: lock missing/unreadable → deny, tampered `devaccel_common.py` / `stop_gate.py`, and guard config not read from the worktree. |
| GRD-09 | partial | KitTest::test_land_policy_in_guard (script, unbuffer, glob, brace, cd) | Not covered: `expect`, `empty`, `socat`. |
| GRD-10 | partial | GuardTest::test_bad_custom_regex_keeps_builtins, test_project_regex | Not covered: internal error → ask (fail-closed), and `ask_regex`. |
| GRD-11 | partial | GuardTest::test_allow, test_secrets_are_not_the_guards_job; test_push_policy (`2>&1`) | Not covered: `git commit -F file`, and quoted strings containing checked words (`echo "sudo"`). |

### PR

| ID | covered? | test(s) | note |
|---|---|---|---|
| PR-01 | partial | T::test_pr_script_refuses_secret_notes (on main → rc 2) | Not covered: uncommitted changes, detached HEAD, custom base_branch, non-github origin, and unpushed HEAD. |
| PR-02 | partial | T::test_pr_triage_evidence_ok ("check.sh full" in body); test_pr_body_records_base_and_docs_note | Not asserted in the body: stages, scale, verify notes, design / AC section, and the failure tail. |
| PR-03 | partial | T::test_pr_cannot_weaken_its_own_checks | Covers the base check.sh being used. Not covered: fetching origin base before judging, and config read from the trusted root. |
| PR-04 | partial | T::test_pr_triage_defect_injection, test_pr_triage_needs_human, test_pr_triage_risky_path | Covers (a) fail, (b), (d), (e), (f), (g), (i). Not covered: (a) timeout/missing, (c) file count over the threshold, (h) gate escalation on the branch. |
| PR-05 | partial | defect_injection "machinery" (pytest.ini); test_pr_cannot_weaken_its_own_checks (scripts/check.sh) | Not covered: `.claude/**`, `.github/**`, CLAUDE.md, AGENTS.md, conftest.py, pyproject tool lines, and "regardless of project.json" (e.g. a branch editing risky_paths). |
| PR-06 | yes | defect_injection "benign"; test_pr_body_records_base_and_docs_note (docs note ≠ reason) | |
| PR-07 | partial | T::test_pr_script_refuses_secret_notes (credential content; file outside repo/tmp) | Not covered: `.env*` name, >4096 bytes, nonexistent file. Only `rc != 0` is asserted, not the error text. |
| PR-08 | partial | T::test_pr_body_records_base_and_docs_note | Forged marker neutralised (count == 1) and base sha. Not asserted: the marker is the **last** line (land relies on that), and the head sha. |
| PR-09 | partial | T::test_pr_rerun_updates_existing | Covers update + label swap and head mismatch → rc 2. Not covered: fork, base mismatch. |
| PR-10 | yes | T::test_pr_rerun_updates_existing (base moved → stays needs-human) | |
| PR-11 | partial | pr_dry_run helper (body + JSON label) | Not covered: "dry-run calls no gh" (no fake-gh log in dry-run tests), `-R owner/repo` (assertions stop before `-R`), and auto_merge default-off / required-check condition. |

### LAND

| ID | covered? | test(s) | note |
|---|---|---|---|
| LAND-01 | partial | T::test_land_detects_textual_conflict (`--label evidence-ok` query); test_land_rejects… (fork skipped); test_land_orders_docs_last | Not covered: base filter, open-state filter, and numeric order among code PRs. |
| LAND-02 | yes | T::test_land_rejects_stale_label_fork_and_risky | |
| LAND-03 | partial | T::test_land_detects_textual_conflict | Not covered: verification continuing **after** a conflict (no 3rd PR), and merge-abort state. |
| LAND-04 | partial | T::test_land_green_alone_red_together; test_land_uses_base_check | Rollback of the failing merge is not verified (it needs a following PR that must still pass). |
| LAND-05 | partial | T::test_land_detects_textual_conflict | Covers add needs-human and only querying evidence-ok. Not covered: the reason/fix comment (`pr comment`). |
| LAND-06 | partial | test_land_detects_textual_conflict (no `pr merge`); test_land_green_alone_red_together (dry-run: no `pr edit`) | In dry-run, only `pr edit` is checked. A `pr comment` or `pr merge` would go unnoticed. |
| LAND-07 | partial | T::test_land_policy_in_guard (no TTY → rc 2) | Not covered: the TTY path (typing anything other than `merge` aborts; `merge` proceeds). |
| LAND-08 | no | — | No test with `--merge`. Not covered: `--match-head-commit`, base moved → stop, tree mismatch → stop. |
| LAND-09 | partial | T::test_land_detects_textual_conflict (scratch worktree removed) | Not covered: main tree/branch unchanged, cleanup on failure/abort, and overlapping-file pairs shown. |
| LAND-10 | no | — | manual |

### SKILLS / CLAUDE.md

| ID | covered? | test(s) | note |
|---|---|---|---|
| SKL-01 | no | — | No static test of seed CLAUDE.md line count, skill frontmatter (`disable-model-invocation`, no `model:`), or the absence of agents/rules. |
| SKL-02 | no | — | No extraction of skill commands → guard + allow. This class regressed in 0.6.5 and 0.7.1. |
| SKL-03 | no | — | |
| SKL-04 | no | — | |
| SKL-05 | no | — | |
| SKL-06 | partial | SMOKE[2] | Covers edit, Write notes, commit, dry-run label, 0 denials. The prompt never runs `check.sh`, so that step is not exercised. |
| SKL-07 | no | — | manual |

### PERFORMANCE

| ID | covered? | test(s) | note |
|---|---|---|---|
| PERF-01 | partial | BENCH (`cost_usd`) | Measured but never compared to the +5% threshold. No pass/fail verdict. |
| PERF-02 | partial | BENCH (`wall_s`) | Same: no +10% verdict. |
| PERF-03 | partial | BENCH (`heldout_*`, `check_full`) | Same: no "≥ vanilla" verdict. |
| PERF-04 | partial | SMOKE[1] | The median threshold is 3.0 s; the requirement says <2 s. It measures 3 commands, not just `ls`. |
| PERF-05 | no | — | No timing test for guard or for stop_gate with off. |

### NON-PYTHON

| ID | covered? | test(s) | note |
|---|---|---|---|
| NPY-01 | no | — | Every KitTest installs into a project with pyproject.toml. |
| NPY-02 | no | — | |
| NPY-03 | partial | All gate/PR/land tests use a language-neutral bash stub check.sh that relies only on rc + `== ok/failed` lines | Not covered: `== missing` handling in PR/land, and a non-Python project install. |
| NPY-04 | no | — | manual |

## 2. Prioritized gap list (unit / integration level)

Ordered by (chance a regression goes unnoticed) × (impact). Most are cheap: the KitTest fixture already provides an installed temp repo, worktrees, a bare origin and a fake gh.

1. **SET-01..08: generated settings.json is unasserted.** Every 0.6–0.8 field regression (0.6.4 Read deny uv.lock, 0.7.2 worktrees deny, 0.8.1 `~/**` denyRead, `Bash(git push*)` ask) lives here. Only paid smoke would catch them. *Test:* after install, load `.claude/settings.json` and assert:
   - SET-01: sandbox flags are true/false as required.
   - SET-02: the 8 home secrets are present, there is no `~/` entry containing `*`, and `~/.config/gh` is absent.
   - SET-03: Read/Edit deny ⊆ `.env*` patterns.
   - SET-04: no `*` in git/check.sh allow entries; the required deny entries are present.
   - SET-05: the PR path is allowed and there is no `Bash(git push*)` ask.
   - SET-06: Edit on the machinery paths is ask, in both plain and `**/` forms.
   - SET-07: Stop, SubagentStop and PreToolUse are wired with `python3 "$CLAUDE_PROJECT_DIR"`.
   - SET-08: domains, caches, and env `3` / `sonnet`.
2. **DOC-01..05: doctor problem detection is untested.** By RISK-10, doctor is the only safety net for settings drift in existing projects. *Test:* for each mutation, assert rc 1 and a matching line. Mutations: delete a core file; append to guard.py; drop SubagentStop; set `sandbox.enabled=false`; add `~/**/x` to denyRead; add a `Read(/uv.lock)` deny; remove `.devaccel/` from .gitignore; write 100 lines to CLAUDE.md. Also: a clean install gives rc 0 + `OK`, and the tree hash is unchanged.
3. **GATE-03 (trust boundary): the worktree project.json tamper is ineffective.** *Test:* in a worktree, write `{"gate":{"unit_mode":"off","max_rounds":0}}`, break app.py, stop with agent_id. Assert `decision == block` and the reason contains `1/3`.
4. **GATE-15: the env override must not disable unit gates** (§4 #10 fix, currently unguarded). *Test:* worktree + `DEVACCEL_GATE_MODE=off` → still blocks. Main checkout + `DEVACCEL_GATE_MODE=bogus` + project `mode=enforce` → blocks.
5. **GATE-08: skip logic is unguarded, and the docs-only test is vacuous.** *Test:* use a stub that always fails (`exit 1`). Assert:
   - a README.md-only change → `{}` and no log line;
   - on branch `spike/x` with app.py changed → `{}`;
   - outside git → `{}`;
   - a passing stub that also reformats a file, then a second stop → no new log line.
6. **INST-02 / INST-04 / INST-03: install must not clobber user files.** *Test:* pre-create CLAUDE.md, `.claude/project.json`, `scripts/check.sh` and `.claude/settings.json` with sentinel text, run install, and assert all are byte-identical and their names appear in stdout. Separately, pre-create `.claude/hooks/guard.py` with other content → rc 1, and `.claude/devaccel.lock` absent and no core files written.
7. **GATE-09: a timeout must not be remembered as a pass.** *Test:* stub `sleep 5`, `gate.timeout_sec=1`. Assert `systemMessage` contains "打ち切", a log line with `result: timeout`, and a second stop runs check.sh again (one more log line).
8. **GATE-13: notices must never block.** *Test:* use a passing stub. Delete a committed test file and add `@pytest.mark.skip` → the reply has `systemMessage`, no `decision`. Change again → no second notice of the same kind.
9. **GRD-08: lock missing → deny; the other trusted files are hashed.** *Test:* remove `.claude/devaccel.lock` → `gv("python3 .claude/hooks/devaccel_pr.py --title t") == "deny"`. Restore it, append to `devaccel_common.py` → deny. Same for `stop_gate.py`.
10. **UPD-03 / UPD-01: update must be all-or-nothing.** *Test:* delete the lock → update rc 1 with the tree unchanged. After a hand edit, the refusal leaves every file hash unchanged. After a successful update, every lock line equals the sha256 of the file. Simulate staging failure by making one kit core file unreadable in a copied kit → target unchanged.
11. **PR-01 / PR-05 / PR-04(c, h) / PR-07: PR triage holes.**
    - PR-01 (non-dry-run with fake gh): uncommitted → rc 2; unpushed → rc 2; origin `https://gitlab.com/x` → rc 2.
    - PR-05 machinery cases: `.claude/skills/x.md`, `.github/workflows/a.yml`, `CLAUDE.md`, pyproject `[tool.ruff]` line, and a branch that edits `project.json` risky_paths to `[]` while touching `auth/`. Each → needs-human.
    - PR-04(c): change 5 files → needs-human.
    - PR-04(h): write an escalate log line for the branch → needs-human.
    - PR-07: `.env.notes`, a 5000-byte file, and a missing path → rc ≠ 0 with the specific message.
12. **SKL-02: skill commands must pass guard and allow** (0.6.5 / 0.7.1 regressions). *Test:* parse the fenced `bash` blocks / backticked commands in `devaccel-pr` and `devaccel-batch` SKILL.md. Assert each has no `$(`, `$`, `&&`, heredoc or `cd`; `guard.decide` returns None on a work branch; and it matches some `Bash(...)` allow pattern in the generated settings.json.
13. **GATE-05 / GATE-06: block payload content.** *Test:* stub prints stage `lint` with 100 lines, then stage `tests` failing with 100 lines. Assert the reason contains `tests`, contains none of the lint lines, and has ≤ 40 + header lines. On the 4th round, assert `systemMessage` is present and the log has `result: escalate`.
14. **LAND-08 / LAND-05 / LAND-06: the merge path and side effects.** *Test:* run `--merge` under a pty (`pty.spawn`) typing `merge`, with fake gh. Assert:
    - the gh log has `pr merge N -R o/r --squash --match-head-commit <oid>`;
    - the base moved before merge → "stopped";
    - in dry-run the log has no `pr comment` / `pr merge`;
    - non-dry-run demotion has a `pr comment` with "直し方".
15. **GATE-10 / GATE-11: robustness.** *Test:* write garbage to `state/gate/s.json` and invalid JSON to project.json → still `block` and stderr mentions "invalid JSON". Interleave two agent_ids failing → each has its own round counter (1/3, 1/3, then 2/3 for the first).
16. **NPY-01 / NPY-02: non-Python install.** *Test:* install into a repo without pyproject. Assert project.json `presets == []`, settings has no pypi domain or `~/.cache/uv`, `scripts/check.sh` prints `no checks configured`, and doctor rc 1 with the "passes anything" problem.
17. **LAND-03 / LAND-04 / LAND-09: continuation and rollback.** *Test:* PRs 1 (ok), 2 (conflicts with 1), 3 (independent) → `#3 ok`. Green-alone-red-together followed by an independent PR 3 → `#3 ok` (proves 2 was rolled back). After land, the main checkout's `git status` and branch are unchanged.
18. **GRD-01 / GRD-02 / GRD-09 / GRD-11 list completions.** All currently behave correctly, so these are just missing table entries:
    - deny: `rm -rf $HOME`, `rm -rf .git`, `timeout 5 gh pr list`, `git -c core.editor=x commit`, `git show --output=x`, `expect x`, `socat - x`;
    - change `${IFS}` from ask-or-deny to `assertEqual deny`;
    - allow: `git commit -F msg.txt`, `echo "git add -A"`.
19. **INST-08: Python 3.8 compatibility.** *Test:* add a CI matrix entry for Python 3.8 running the unittest suite (or `pyright --pythonversion 3.8` on hooks and kit). Also grep installed files for the kit's absolute path → none.
20. **PERF-05.** *Test:* time 50 `guard.py` invocations and 10 `stop_gate.py` invocations with off. Assert median < 0.5 s and that `check.sh` was not run (marker file absent).

## 3. Verification levels that look wrong

| ID | stated | suggested | why |
|---|---|---|---|
| GATE-02, GATE-03, GATE-04 | integration | unit | They need only a temp git repo + `git worktree` + stub check.sh. The existing unit tests already do this. No real uv/ruff/pyright is involved. |
| PR-01, PR-03, PR-04, PR-05, PR-06 | integration | unit | Covered (partially) today by unit tests with a stub check.sh and a local bare origin. Real tools add nothing to triage logic. |
| PR-10, LAND-02, LAND-03, LAND-04, LAND-08, LAND-09 | integration (gh faked) | unit (gh faked) | They use the same fixture as existing unit tests (bare repo via `insteadOf` + fake gh). |
| NPY-03 | integration | unit | The gate, PR and land only see rc and `==` lines. The language-neutral bash stub already exercises this. |
| PERF-05 | integration | unit (timing) | No real tools are needed: guard and stop_gate-off never start check.sh. |
| SKL-04 | unit (static) | unit (static, text present) + e2e-smoke / bench | "Use /batch only when ≥4 independent S/M" is model behaviour. Static checks can only confirm the instruction text exists. |
| SKL-02 | unit | unit + e2e-smoke | The extraction test catches guard/allow mismatches. Whether the model actually emits only those forms needs SMOKE[2] (which already watches denials). |
| GATE-11 (concurrency clause) | unit | unit + stress | A sequential unit test can show per-agent files. True simultaneous stops need a multi-process race test, otherwise lost-update bugs stay invisible. |
| DOC-04 (bubblewrap / socat) | unit | unit with a controlled PATH | It is only cheap if the test fakes PATH, so state it explicitly. On a dev box with both installed, a naive test can't see the "missing" branch. |
| INST-08 | integration | integration on a Python 3.8 interpreter | The current CI (3.12, pyright 3.10) cannot detect a 3.8 violation. The level is right but the environment is not specified anywhere. |
| PERF-01..03 | bench | bench + an automated threshold check | summarize.py prints medians but never compares them with the +5% / +10% / ≥ vanilla limits, so the "verification" is a human reading a table. |
| PERF-04 | e2e-smoke | e2e-smoke (align threshold) | The requirement says <2 s; smoke uses 3.0 s. One of them should change. |
| DOC-03 | unit | unit (fix the text first) | The requirement text ("display" for SubagentStop) contradicts §4 #9 (problem since 0.9.0). Also, GATE-15 cites 0.9.0 while the target is 0.8.4. |


## 0.10.x で追加した要件の対応

| ID | covered? | テスト |
|---|---|---|
| DOC-10 | yes | test_requirements.py::AuditDoctorTest(hooks_wired_structural、doctor_runs_kit_report_isolated、required_denies_and_denywrite)、R3 の doctor 系 |
| SET-11 | yes | AuditDoctorTest::test_AUD_generated_denywrite、R3 の settings 系 |
| GATE-17 | yes(bwrap がある環境) | ConfinementTest::test_GATE17_check_runs_confined、R3 の .env/$HOME 系 |
| GATE-18 | yes | GateHardeningTest::test_GATE_unit_cannot_opt_out、UnitCommittedTest、R3 の壊れた worktree |
| PR-12 | yes | TriageEvasionTest(6 本)、AuditPrTest、R3 の HEAD スナップショット |
| GRD-12 | partial | ShadowTest(余剰ファイルで拒否)。sys.path の順序は防御にならない(スクリプトのディレクトリは常に sys.path[0])ため、要件の後半は撤回 |
