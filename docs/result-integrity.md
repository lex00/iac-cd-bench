# Result integrity

A benchmark number is only worth reading if the run behind it measured the
model. This harness has published numbers that did not, six times, each costing
hours before anyone noticed. The gates below exist so that each of those
failures is now either structurally impossible or loudly detected.

The design is ported from two harnesses that already learned these lessons:
[chant-bench](https://github.com/lex00/chant-bench) (the publishing side) and
[aws-bench](https://github.com/lex00/aws-bench) (the running side). Their
governing rule, which this file adopts:

> A run the gates rejected is not published. Neither is one whose provenance is
> incomplete. A number nobody can trace, or one that measured a broken harness
> rather than a tool, is worse than no number.

## The rules

### 1. Nothing starts without the tools

`bench/preflight.py` probes every binary the selected stacks' lint, static and
e2e stages will shell out to, records `name -> {path, version}`, and raises
`PreflightError` before the adapter is built if any is absent. `bench.runner`
exits 2 on that.

A stage whose binary is missing cannot tell a correct answer from an unchecked
one. Fixing the stage runners to report `passed: False` on `FileNotFoundError`
(#56) stops the lie per-stage but still burns a full matrix of API spend to
produce a wall of failures, so the check has to run before the first token.

`--allow-missing-tools` is the deliberate escape hatch. It stamps the result
set `partial: true`, and `bench.validate` downgrades every run in it, so a
knowingly-incomplete run can never later be quoted as a clean one.

Run it standalone with `make preflight STACKS=knr-ops,chant`.

### 2. Every run carries its provenance

`bench/provenance.py` stamps each result JSON with:

| field | why |
| --- | --- |
| `harness.commit`, `harness.branch`, `harness.dirty` | a re-run after any harness change is a different experiment; `dirty` matters as much as the sha, because a sha alone cannot describe a tree with uncommitted edits |
| `task.prompt_sha256`, `task.spec_sha256`, `task.scenario_sha256` | the instruction is part of the experiment |
| `toolchain` | `{binary: {path, version}}` from the preflight |
| `provider`, `model`, `reasoning_effort` | what was actually pinned, not what was intended |
| `judge_model`, `judge_prompt_sha256` | when `--judge` was used |
| `partial` | set when the preflight was overridden |

`_provenance.json` in the result-set directory carries the same block plus the
preflight report that authorised the set.

`toolchain_fingerprint()` hashes name+version only, never paths: two worktrees
resolve the same binary at different paths without any behavioural difference,
and a fingerprint that moved on path alone would flag every set as
incomparable and be ignored within a week.

### 3. A stage with nothing to act on is `inapplicable`, not `passed`

This is the highest-value guard and the one that had never been fixed anywhere.

`lint` used to return `{"passed": True, "logs": "no YAML files in workspace"}`.
`static` used to return `{"passed": True, "logs": "static validation passed"}`
when it found no kustomization, claim or manifest. `semantic` used to return a
pass for a task shipping no grader. `completeness` defaulted to `1.0` whenever
no assertion was evaluated.

The result: a run that produced no extractable output scored 2 of 3 stages plus
full marks on the second-heaviest axis. **The most broken runs scored highest.**

Now those paths return `bench.stages.lint.inapplicable(reason)` — a dict with
no `passed` key at all, so every existing `.get("passed", False)` reader treats
it as not-passed — and `bench.score`:

- excludes inapplicable stages from both sides of the correctness ratio;
- drops `completeness` from the weighted composite when no assertion ran,
  rather than defaulting it;
- recognises the old log bodies (`VACUOUS_LOG_MARKERS`) so stored results are
  re-scored honestly instead of the fix applying only to future runs.

A run whose every enabled stage was inapplicable is rejected outright.

**Measured impact on the 1140 historical result JSONs** (pinned in
`tests/test_score_regression.py`):

- 744 runs (65%) carried at least one vacuously-passed stage
  — semantic 621, static 346, lint 182
- 119 runs had *every* enabled stage inapplicable
- 762 composites change, **every one of them downward**, mean −0.22

Zero composites move up, which is the invariant the test asserts: withdrawing
credit that was never earned can only lower a score.

### 4. A completion that is not an answer is rejected, not scored

`bench/validity.py` classifies the raw completion before any stage runs:

- **empty** — the provider returned no text;
- **too short** — under 200 characters, below any usable answer in this suite;
- **agent transcript** — tool-call markup (`<invoke name=`, Claude Code's `⏺`
  bullets, `TodoWrite`/`str_replace_editor`, "I'll use the Read tool"), or two
  distinct narration markers, or three narration lines;
- **no extractable output** — the task's enabled stages act on files the model
  was to produce, and the completion has no fenced code block.

That last one is what makes #59 and the vacuous pass the same failure: a
provider returning preambles gives lint and static nothing to check, so the
arm's gate rate goes *up* because its provider is broken.

The gate is pure text classification — no network, no subprocess — so it
re-runs identically over historical result JSONs. Swept over all 1140 of them
it flags 58 empty completions, 43 too-short ones, and 2 genuine agent
transcripts, with no false positives on real answers.

### 5. A rejected run gets no number

`bench/report.py` partitions runs before averaging anything. A rejected run
contributes to no cell, and the count is stated above the matrix as
**`rejected: N`** with a reason histogram, not in a footnote.

chant-bench's `rate()` is the source: *"An invalid run gets no number. Not a
low one, not a caveated one — none."* terraform-m1 published `1.000` beside an
`invalid` badge after losing 22 of its 24 trials, and the badge lost to the
number.

`--fail-on-rejected` makes that non-zero-exit for CI.

### 6. Sets that are not the same experiment do not get a table

`bench.report --compare` refuses (exit 2) when the sets disagree on harness
commit, toolchain versions, provider or reasoning effort. `--allow-incomparable`
renders it anyway with the conflicts stated in the report body.

The model is deliberately not a comparability axis: differing models is what a
comparison is *for*.

Sets predating the provenance stamp are labelled **unverifiable** rather than
agreeing — a set that cannot be shown to differ has not been shown to match.

### 7. The validator

```
python3 -m bench.validate results/claude-opus-5 --verbose
make validate DIRS="results/claude-opus-5 results/gpt-5.4"
```

Classifies each run `valid` / `partial` / `invalid` with reasons, then judges
the set. A set is **refused** (exit 1) when:

- errored runs exceed `CRASH_LIMIT` (10%) of the set — a rate over the
  survivors is not a rate over the run set;
- rejected runs exceed `REJECT_LIMIT` (10%);
- run counts per task are uneven — a 1-run task beside 3-run tasks is a smoke
  test that landed on the leaderboard;
- harness commits, toolchains or providers are mixed *within* one set.

Errored runs stay in the denominator throughout. Dropping them from both sides
of the ratio is how a catastrophe reads as a triumph.

## Mechanism map

| iac-cd-bench | ported from | what it fixes here |
| --- | --- | --- |
| `bench/preflight.py` `check()` | aws-bench `benchmarks/agent-env/preflight.py`, `aws_bench/cli/preflight.py` (`preflight_docker_cli` / `_daemon`) | #56, failure mode 1 |
| `preflight.probe_binary` version capture | aws-bench `tool-version.py` (last non-empty line, never a notice-as-version) | failure mode 5 |
| `_chant_package_version` reads the installed tree | aws-bench `arms.py` `_PKG_VERSION` — "read off the installed tree by path" | chant's pin vs its installed version |
| `--allow-missing-tools` → `partial` | chant-bench `gates.tool_missing` + the publish refusal | deliberate partial runs |
| `bench/provenance.py` `harness_commit()` incl. `dirty` | aws-bench `emit-result.py::git_commit` (`-dirty` suffix) | failure mode 6 |
| `task_fingerprint()` prompt/spec hashes | chant-bench `briefing.sha256`; aws-bench `emit-result.py` briefing block | failure mode 6 |
| `toolchain_fingerprint()` | aws-bench `prepare.py::workspace_fingerprint` (stat-only digest, cheap and stable) | failure mode 5 |
| `lint.inapplicable()` + `score.stage_inapplicable` | aws-bench `aggregation.py` `_tool_stats` (`success_ratio` 0 when no calls), `estate-check.py`'s "no instances at all" backstop | failure mode 3 |
| composite drops unmeasurable axes | aws-bench `emit-result.py` `"pass_rate": ... if trials else None` — null rather than a number | failure mode 3 |
| `bench/validity.py` | aws-bench `audit.py` classification ladder; chant-bench postflight audit | #59, failure mode 4 |
| `validate.classify_run` `tool_missing_scored_as_pass` | aws-bench `audit.py` `MISSING` / `MISSING_NAME` regexes | #56 in stored results |
| `validate.CRASH_LIMIT = 0.10` | chant-bench `validate_results.py::CRASH_LIMIT`, aws-bench `audit.py` — collapsed into one constant here, since aws-bench carries it twice and the copies can drift | errored-run denominators |
| uneven-k refusal | chant-bench `validate_results.py` trial-count homogeneity (mode of `expected_trials`) | smoke runs on the board |
| errored runs stay in the denominator | aws-bench `emit-result.py` `trials` / `expected_trials` / `completed` / `errored` | terraform-m1's 2/2 = 1.000 |
| `report.partition_by_validity` + `rejected: N` | chant-bench `build_pages.py::valid()` / `rate()` | failure mode 3, 4 |
| `--compare` comparability refusal | chant-bench `skills/chant-bench-results.md` ("same harness commit and briefing SHA"); the gap this closes is that chant-bench states the rule but never enforces it in code | failure mode 5, 6 |
| `python3 -m bench.validate` CLI | chant-bench `scripts/validate_results.py` | all of the above |

## Not yet guarded

- **Judge-model drift.** `judge_model` / `judge_prompt_sha256` are recorded and
  surfaced in the coverage table, but the comparability check does not refuse
  on them; two sets judged by different judges still render side by side.
- **Task-content drift across sets.** `task.prompt_sha256` is recorded per run,
  but `comparability()` compares harness/toolchain/provider/effort only. Two
  sets run against different versions of the same task's `prompt.md` would
  compare cleanly.
- **The `safety` axis still defaults to 1.0 when nothing ran.** It is the same
  "nothing checked, full marks" shape the completeness axis just lost, and
  dropping it was tried and deliberately reverted: with `safety` gone too, an
  unjudged rubric-only task scores exactly 0.0 on every axis, which reads as
  "the model did terribly" rather than "nothing was measured" — the same
  misleading-number failure, pointing the other way. What contains it for now
  is that runs where every enabled stage was inapplicable are rejected
  outright and contribute no number at all. The underlying heuristic
  (`"safety" not in output.lower()` in `bench/stages/semantic.py`) is not a
  real safety gate either, and both want replacing together with an
  unmeasurable-composite sentinel rather than a 0.0.
- **Independence / tool-use evidence.** aws-bench audits the agent trajectory
  to prove the arm's own CLI ran. This harness is one-shot and has no
  trajectory, so there is nothing equivalent to audit; the validity gate is a
  weaker proxy that reads only the completion.
- **`consistency` is computed at aggregate level only** and is 0.0 in every
  per-run composite, which drags every composite down by a fixed amount rather
  than measuring anything.
- **No CI enforcement.** chant-bench gates its build on
  `validate_results.py` and on regenerating pages and diffing them. Nothing
  here runs `bench.validate` automatically.
- **Historical result sets are all refused.** Every set under `results/` fails
  validation today (no provenance, plus the stored `NOT FOUND: pulumi` passes).
  They are left on disk deliberately — they are the evidence — but no number
  from them should be quoted without re-running.
