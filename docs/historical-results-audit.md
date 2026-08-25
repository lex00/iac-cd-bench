# Historical Results Audit

Date: 2026-08-25
Scope: every result set under `results/` on `main` as of commit `0f8b215`. That is
1,140 run JSONs across 13 result sets (claude-opus-5, claude-opus-5-low,
claude-opus-4-8, claude-opus-4-8-low, gpt-5.4, gpt-5.4-low, gpt-5.6-sol-low,
glm-5.3, glm-5.3-low, kimi-k3, qwen 3.8 - local, qwen 3.8 - local-low,
qwen36-local), 5 stacks (knr-ops, crossplane, terraform, pulumi-python,
pulumi-typescript), 6 archetypes (comprehend, generate, modify, debug, review,
semantics), condition warm (1,125 runs) and cold (15, knr-ops only).

Question this answers: did the upstream author's own published runs suffer the
integrity failures this project just found and fixed (or is fixing) in its own
harness: vacuous passes, missing-binary passes, disabled-stage passes, content
truncation, and agent-transcript contamination? This is an audit, not a fix. No
scoring code or result JSON was changed. All numbers below are reproducible from
the scripts described in the Method section.

## Headline

Every failure mode this audit tested for is present in the historical dataset
except contamination (mode 5), which comes back clean. The two biggest are a
missing-binary bug that gave `pulumi-python` and `pulumi-typescript` a free pass
on static validation in essentially every run across nearly every result set, and
a disabled-stage-passed artifact that gives rubric-only tasks (comprehend, review)
credit for lint/static/semantic they were never asked to attempt. Correcting for
just the two "real bug" modes (vacuous passes and missing-binary passes, leaving
the disabled-stage scoring convention as published) still moves the #1-ranked
result set on the published leaderboard, `qwen 3.8 - local`, down to 9th of 13 by
average composite. Correcting all three moves it to 10th. The bottom of the
leaderboard is comparatively stable.

## 0. Sanity check: is agent-transcript contamination (#59) even applicable here?

Verified rather than assumed, per the brief. `bench/runner.py` on `main` defines
only `AnthropicAdapter` and `OpenAICompatAdapter`. `ClaudeCliAdapter` (which shells
out to `claude --print` and is the source of #59's contamination) was added on
`bench/claude-cli-provider` (commit `551a90e`) and has never been merged to
`main`. None of the 13 historical result sets could have been produced by it;
they predate that adapter's existence.

Confirmed independently by content, not just by adapter code: `bench/validity.py`
was fetched unmodified from `bench/cli-provider-fix` and its STRONG-signal
detectors (tool invocation markup, the `★ Insight` UI marker, leaked
`.claude/worktrees/agent-*` paths) were run against every run's `content` field.
Zero matches across all 1,140 runs. The assumption in the task brief holds:
#59-style contamination is specific to the `claude-cli` provider and does not
reach the published leaderboard.

## 1. Vacuous passes

Definition used: a run on a code-producing archetype (generate/modify/debug,
where `spec.yaml` enables lint and static) whose model output produced no
extractable files (`extracted_files` absent from the result JSON, meaning
`bench/runner.py`'s `extract_code_blocks` found no fenced block it could write to
disk), yet lint and/or static still recorded `passed: true`. This is stricter than
a raw log-string match because it ties the count to the actual mechanism: nothing
was extracted, so lint ran `kustomize`/`ruff`/`tsc`/`terraform validate` against
an empty or near-empty workspace and trivially succeeded, rather than just
matching incidental phrasing.

**102 of 1,140 runs (8.9%)** show at least one vacuous pass under this
definition: 66 on lint, 102 on static (a run can trip both).

By result set:

| result set | vacuous-pass runs |
|---|---|
| qwen 3.8 - local | 37 |
| claude-opus-5 | 32 |
| qwen36-local | 14 |
| glm-5.3-low | 3 |
| gpt-5.4 | 3 |
| gpt-5.4-low | 3 |
| gpt-5.6-sol-low | 3 |
| kimi-k3 | 3 |
| claude-opus-4-8 | 2 |
| claude-opus-4-8-low | 1 |
| glm-5.3 | 1 |
| claude-opus-5-low, qwen 3.8 - local-low | 0 |

By stack (code-archetype runs only, 117-126 per stack):

| stack | vacuous-pass runs | rate |
|---|---|---|
| knr-ops | 39 / 126 | 31% |
| pulumi-typescript | 20 / 117 | 17% |
| pulumi-python | 16 / 117 | 14% |
| terraform | 15 / 117 | 13% |
| crossplane | 12 / 117 | 10% |

For context, a broader raw-log-string count (any run whose lint logs contain "no
YAML files in workspace" / "no TypeScript files in workspace" / "no lint commands
for stack", or whose static logs are the literal fallback string "static
validation passed" with no `exit=` in them, regardless of archetype) is much
bigger: 182 lint runs and 346 static runs. That is because it also catches rubric
tasks where the stage was *supposed* to have nothing to lint (see §3). Restricted
to code archetypes, the raw-log-string count is close to the stricter definition:
32 lint, 165 static.

## 2. Missing-binary passes

Definition: `stages.<name>.logs` contains the literal string `"NOT FOUND:"` and
`stages.<name>.passed` is nonetheless `true`. Root cause confirmed by reading
`bench/stages/lint.py` and `bench/stages/static.py`: every `except
FileNotFoundError` branch in both files appends a `"NOT FOUND: <tool>"` log line
but never sets `all_passed = False` (or `passed = False`) in that branch. A
missing tool is architecturally indistinguishable from "nothing to check" in the
current code. This is the exact "pre-#56" behavior described in the audit brief,
and it is present on `main` today, not just historically. It has since been fixed
on `bench/integrity-gates` (commit `1976144`, "lint/static: FileNotFoundError on a
missing tool sets passed=False"), which is unmerged.

**427 of 1,140 runs (37.5%)** carry at least one missing-binary pass. All 427 are
the `static` stage; lint shows zero (every lint-stage tool: `yq`, `kubeconform`,
`terraform`, `ruff`, `tsc`, was present on whichever machine(s) generated these
result sets). All 427 are on `pulumi-python` or `pulumi-typescript`: the `pulumi`
binary was simply not on the runner's `PATH` for nearly the entire dataset.

| result set | NOT-FOUND static / total pulumi runs | rate |
|---|---|---|
| claude-opus-4-8-low | 36/36 | 100% |
| claude-opus-5 | 36/36 | 100% |
| glm-5.3 | 36/36 | 100% |
| glm-5.3-low | 36/36 | 100% |
| gpt-5.4 | 36/36 | 100% |
| gpt-5.4-low | 36/36 | 100% |
| gpt-5.6-sol-low | 36/36 | 100% |
| qwen 3.8 - local | 36/36 | 100% |
| qwen 3.8 - local-low | 36/36 | 100% |
| claude-opus-4-8 | 30/30 | 100% |
| kimi-k3 | 30/30 | 100% |
| claude-opus-5-low | 28/36 | 78% |
| qwen36-local | 15/30 | 50% |

Every stack other than the two Pulumi stacks shows zero missing-binary passes;
`kustomize`, `flux`, `crossplane`, and `terraform` were consistently available.
This is not a spread-out reliability issue. It is one missing CLI on one machine
(or a small number of machines, given the two partial exceptions) that silently
zeroed out the `static` axis's signal for 40% of the stack matrix across nearly
the whole leaderboard.

## 3. Disabled-stage passes

`spec.yaml` disables lint/static/semantic/e2e for the two rubric archetypes
(comprehend, review: no code is expected, so there is nothing to lint) and
disables lint/static for the semantics archetype (a JSON quiz graded by pytest,
not by tool validation). `main`'s `bench/runner.py` and `bench/score.py` do not
yet honor those `enabled: false` flags. That fix exists only on an unmerged
branch (`bench/integrity-gates`, commit `279f767`, "runner/score: honor
spec.yaml stage gating, exclude skipped stages from correctness"). Every
historical run therefore ran the disabled stages anyway, and because there was
no code in the workspace, they passed trivially and were counted toward
`correctness`.

**531 of 1,140 runs (46.6%)** carry at least one disabled-stage pass: lint 372,
static 454, semantic 384. The semantic figure needs a caveat: semantics-archetype
tasks disable lint and static but leave semantic enabled, so those 384 are a
real, intended check, not part of this count in the same sense as the other two.
They're included here for completeness, not because they are a bug.

By archetype: comprehend 195, review 189, semantics 147 (this last figure is
lint+static skips inside the semantics archetype, not semantic itself).
By stack: knr-ops 114, crossplane 108, terraform 105, pulumi-python 102,
pulumi-typescript 102. This is an evenly spread result, as expected, since every
stack has the same two rubric archetypes.

The upstream author's own regression test for the unmerged fix
(`tests/test_score_regression.py` on `bench/integrity-gates`) independently
confirms this. It asserts that the *old* (published) `compute_score` formula
("3 fixed stages, present-and-passed counts toward correctness, absent counts
against it") reproduces exactly across all 1,140 historical JSONs with zero
drift, which is only true because none of them carry a `skipped` flag (the flag
the fix introduces). This audit's own recomputation of `main`'s `compute_score`
against every JSON matches that author's characterization.

This mode is different in kind from modes 1 and 2. It is not a bug that silently
fabricates a pass where a check genuinely ran and failed to notice a problem; the
stages really were nothing-to-check for those archetypes. It is a scoring
methodology gap: giving comprehend/review tasks a lint/static "pass" in the
`correctness` axis inflates their contribution relative to what the axis is
supposed to measure (tool-validated correctness). The unmerged fix corrects it by
excluding disabled stages from both the numerator and denominator rather than
counting them as free passes.

## 4. Content integrity

- **58 runs (5.1%) have empty `content`** (`""`, zero characters after strip).
  - 31 in `claude-opus-5`, all with `tokens.output == 16384` (the adapter's hard
    `max_tokens` cap) and modest `tokens.input` (1,000-1,900). This is not
    truncated output; it is a complete API response in which the entire output
    budget was consumed by adaptive-thinking reasoning, leaving zero tokens for
    the answer itself. It concentrates on T2-generate/T3-modify/T4-debug across
    crossplane, pulumi-python, pulumi-typescript, and terraform (not knr-ops), and
    is systematic per (task, stack): when it happens on one run of a (task, stack)
    pair, it typically happens on all three. `claude-opus-5-low` and
    `claude-opus-4-8`/`-low` do not show this pattern at the same rate, suggesting
    it is specific to `claude-opus-5` running adaptive thinking at (or near) max
    effort on longer-context tasks.
  - 19 in `qwen36-local`, all runs where the adapter recorded an `error` field:
    `Server error '503 Service Unavailable'` from the local vLLM endpoint
    (`vllm.biggs.dog`). These are infra flakiness, not model output. `content` is
    absent from the JSON entirely (not stored as `""`) for these, and
    `bench/runner.py`'s exception path only sets `stages.lint = {"passed": False,
    ...}`, so they score as failures, not as free passes. They do not inflate
    anything, but they are missing data.
  - 8 in `claude-opus-5-low`, all `Client error '400 Bad Request'` from the
    Anthropic API, isolated to `pulumi-typescript` T4/T5/T6. Same shape as the
    qwen case: recorded as an error, scored as a failure, a reliability issue
    rather than a scoring-integrity one.
  - Combined, all 27 `error`-field runs are exactly the 27 runs missing the
    `content` key outright (verified: no other JSON in the dataset lacks it).
- **167 runs (14.6%) have short content (50-499 characters)**, but 120 of those
  are `T6-semantics`, a JSON-quiz archetype whose genuine full answers run as
  short as ~450 characters by design (confirmed against `bench/validity.py`'s own
  calibration notes). This is expected, not a red flag. The remaining 47 are
  spread across code archetypes (modify 15, debug 14, generate 13) and T5-review
  (5); a few of the T5-review ones are refusals asking the user to paste the
  Pulumi preview JSON the task already describes inline (`gpt-5.4-low`,
  `qwen 3.8 - local-low` among them, see the WEAK-signal examples below).
- The `bench/validity.py` WEAK-signal check independently flags 9 runs as
  `short_stub`: refusal/clarification phrasing under the 1,500-char floor.
  Content inspection confirms these are real model behavior, not contamination.
  For example, `kimi-k3` and `qwen 3.8 - local` open a single-turn API completion
  with "I'll analyze the repository structure... Let me start by exploring the
  codebase," despite having no tools and being handed the full context inline.
  This is the same *behavioral* tendency the `claude-cli` contamination gate
  exists to catch (a model reflexively narrating tool use it doesn't have), but
  it shows up here as ordinary short-output noise, not markup leaking into the
  transcript, because there is no agentic harness underneath these calls to leak
  from.

No result set shows truncation-by-cutoff (content ending mid-token/mid-sentence
at exactly the token cap) other than the `claude-opus-5` zero-output case above,
which is a budget-exhaustion pattern rather than a mid-answer cutoff.

## 5. Contamination scan

Zero STRONG-signal hits (`tool_invocation_markup`, `claude_code_ui_marker`,
`leaked_host_worktree_path`) across all 1,140 runs. A clean null result,
consistent with §0. This mode does not apply to the historical dataset.

## Score recomputation: before / after

Reusing `bench/score.py`'s `AXES` weights and composite formula. Three views:

- **published**: `main`'s `compute_score` exactly as it runs today (this is what
  produced the published leaderboard).
- **fix #1+#2 only**: vacuous and missing-binary passes forced to `passed: false`
  (the run genuinely gets no credit for a check that either found nothing to
  check, or couldn't find its tool), but the fixed 3-stage denominator is left
  alone. Isolates the two "real bug" modes without touching the stage-gating
  methodology question in §3.
- **full fix**: the above, plus disabled stages excluded from both numerator and
  denominator (mirrors the unmerged `bench/integrity-gates` fix).

### Correctness, code archetypes only

Generate/modify/debug only, where modes 1 and 2 apply and mode 3 does not, so
this isolates 1+2 cleanly.

| stack | n | published | fix #1+#2 | delta |
|---|---|---|---|---|
| crossplane | 117 | 0.724 | 0.655 | -0.068 |
| knr-ops | 126 | 0.545 | 0.421 | -0.124 |
| pulumi-python | 117 | 0.584 | 0.231 | -0.353 |
| pulumi-typescript | 117 | 0.533 | 0.162 | -0.370 |
| terraform | 117 | 0.390 | 0.305 | -0.085 |
| **overall** | 594 | 0.555 | 0.356 | **-0.199** |

### Correctness, all archetypes, all three views

| stack | n | published | fix #1+#2 | full fix |
|---|---|---|---|---|
| crossplane | 225 | 0.834 | 0.799 | 0.474 |
| knr-ops | 240 | 0.678 | 0.613 | 0.346 |
| pulumi-python | 225 | 0.711 | 0.376 | 0.253 |
| pulumi-typescript | 225 | 0.644 | 0.301 | 0.204 |
| terraform | 225 | 0.563 | 0.519 | 0.292 |
| **overall** | 1140 | 0.686 | 0.523 | **0.314** |

### Composite (full fix), per stack

| stack | n | published | after | delta |
|---|---|---|---|---|
| crossplane | 225 | 0.675 | 0.555 | -0.120 |
| knr-ops | 240 | 0.644 | 0.533 | -0.111 |
| pulumi-python | 225 | 0.648 | 0.495 | -0.153 |
| pulumi-typescript | 225 | 0.624 | 0.478 | -0.147 |
| terraform | 225 | 0.600 | 0.510 | -0.090 |
| **overall** | 1140 | 0.638 | 0.515 | **-0.124** |

### Leaderboard reranking (composite, full fix)

| # published | result set | published | after | # after |
|---|---|---|---|---|
| 1 | qwen 3.8 - local | 0.677 | 0.498 | 10 |
| 2 | gpt-5.6-sol-low | 0.658 | 0.535 | 1 |
| 3 | claude-opus-4-8-low | 0.650 | 0.533 | 2 |
| 4 | gpt-5.4-low | 0.648 | 0.524 | 6 |
| 5 | kimi-k3 | 0.643 | 0.510 | 9 |
| 6 | glm-5.3 | 0.642 | 0.527 | 3 |
| 7 | claude-opus-5 | 0.642 | 0.496 | 12 |
| 8 | gpt-5.4 | 0.641 | 0.514 | 7 |
| 9 | glm-5.3-low | 0.640 | 0.525 | 5 |
| 10 | qwen 3.8 - local-low | 0.621 | 0.526 | 4 |
| 11 | claude-opus-4-8 | 0.620 | 0.484 | 13 |
| 12 | qwen36-local | 0.617 | 0.498 | 11 |
| 13 | claude-opus-5-low | 0.597 | 0.513 | 8 |

`qwen 3.8 - local` is the largest mover: published #1, corrected #10. It
benefited disproportionately from exactly the two bugs this audit measured: 37
of the dataset's 102 vacuous passes (the most of any result set) plus the
universal Pulumi missing-binary pass shared by nearly every set.

`claude-opus-5` moves from #7 to #12. Its 32 vacuous passes (second-most of any
result set) are not a separate phenomenon from the §4 empty-content pattern; 31
of its 32 vacuous passes are exactly the runs where adaptive-thinking reasoning
consumed the full 16,384-token output budget, leaving nothing to extract. Once
vacuous-pass credit is removed, those runs correctly fail lint/static/semantic on
their own merits (an empty, un-extractable answer should not pass), so
`claude-opus-5`'s drop reflects one bug (mode 1) manifesting through one root
cause (reasoning-budget exhaustion), not two independent issues.

The bottom three positions (`claude-opus-4-8`, `qwen36-local`,
`claude-opus-5-low`) are less disturbed in absolute rank, though
`claude-opus-4-8` still drops two spots to dead last.

## Which stacks are most affected, and the extraction-heuristic hypothesis

The task brief's hypothesis was that stacks whose extraction heuristics are
strict, or whose expected answers skew prose-heavy, would show more no-file
(vacuous-pass) runs. All five stacks use `answer_format: code` for the
generate/modify/debug archetypes (none are prose-graded there), so this is really
a test of extraction strictness rather than prose-vs-code. It holds up:

- **knr-ops has the highest vacuous-pass rate by a wide margin**, 31% of its
  code-archetype runs versus 10-17% elsewhere. `bench/runner.py`'s
  `extract_code_blocks` applies a K8s-specific filter for `knr-ops` (and
  `crossplane`): a YAML block is only written to disk if it contains the literal
  string `apiVersion`, and only if a backtick-quoted file path appears in the
  surrounding text near the block. A model that writes correct-but-differently-
  formatted YAML (comments-only preamble before `apiVersion`, no backtick path
  reference, a Kustomize-only file without `apiVersion` such as a bare patch)
  produces nothing extractable, and lint/static then trivially pass against an
  empty workspace. `crossplane` runs through the identical filter but shows the
  lowest vacuous-pass rate of all five stacks (10%) rather than tracking
  knr-ops. Worth the upstream author checking whether Crossplane manifests in
  this task set happen to format more uniformly (backtick paths, `apiVersion`
  present near the top) than the knr-ops seeds do, since the extraction code
  path itself is identical for both stacks.
- **pulumi-python and pulumi-typescript are dominated by the missing-binary bug
  (mode 2), not the vacuous-pass bug (mode 1)**. Vacuous-pass rates there (14%,
  17%) are unremarkable, but missing-binary passes hit essentially every run
  regardless of what the model produced, because the `pulumi` CLI was absent.
  This is an infrastructure gap on the runner machine(s), not an extraction or
  model-behavior signal, and it fully explains why these two stacks show the
  largest published-vs-corrected deltas in the score tables above.
- **terraform and crossplane are the cleanest stacks** under both modes.
  Terraform never hits missing-binary (the `terraform` CLI was present) and has
  a below-average vacuous-pass rate (13%). Crossplane has the lowest
  vacuous-pass rate of all five (10%) and, like terraform, never hits
  missing-binary.

## What this means for the published leaderboard

In plain terms: the published numbers are not fabricated, and no model's output
was misrepresented. Every run really happened, every log is a real subprocess
transcript, and there is no evidence of agent-transcript contamination anywhere
in this dataset. But the scoring pipeline that turned those runs into the
leaderboard had two mechanical blind spots (a stage that says "passed" when it
actually found nothing to check, and a stage that says "passed" when its own tool
wasn't installed) plus one methodology choice that, in hindsight, over-credits
rubric-only tasks. All three push scores up, never down, so the published
leaderboard is systematically optimistic, and unevenly so: pulumi-python and
pulumi-typescript scores are inflated far more than crossplane or terraform, and
models/result sets that happened to produce more un-extractable output (vacuous
passes) or hit the missing tool more often benefit more.

The practical consequence is that the published rank ordering should not be
trusted at the individual-position level. `qwen 3.8 - local`'s #1 finish in
particular does not survive correction, though the broad shape (several mid-pack,
low-reasoning-effort variants clustering together; the two `claude-opus-4-8`
variants and `qwen36-local` anchoring the bottom) is roughly stable.

Anyone citing a specific rank from the current `results/` leaderboard should
treat it as provisional until the harness fixes for modes 2 and 3 land on
`main`. Both already exist, unmerged, on `bench/integrity-gates` (`1976144` for
missing-binary detection, `279f767` for stage gating). Mode 1 (vacuous passes)
has no equivalent fix yet on any branch found during this audit; a
workspace-emptiness check before trusting a lint/static pass would close it. Once
fixed, the historical sets should be rescored, not rerun: the raw model outputs
and logs are already on disk and sufficient to rescore honestly.

## Method

All analysis is read-only; no `results/*.json` or scoring code was modified.
Full reproduction:

1. Parse every `tasks/*/*/spec.yaml` for `archetype`, `answer_format`, and
   `stages.<name>.enabled`.
2. Walk every `results/**/*.json`, skip non-run files, load `stages`, `content`,
   `extracted_files`, `tokens`, `error`.
3. Missing-binary: `"NOT FOUND:" in stages[<name>].logs and stages[<name>].passed
   is True`.
4. Vacuous pass: `archetype in {generate, modify, debug}`, stage enabled per
   spec, `stages[<name>].passed is True`, `"extracted_files" not in result`.
5. Disabled-stage pass: spec disables the stage, `stages[<name>].passed is True`.
6. Content integrity: length of `content.strip()`, presence of the `content`
   key, presence of the `error` key, correlated against `tokens.output`.
7. Contamination: `bench/validity.py` fetched unmodified from
   `bench/cli-provider-fix` (`git show bench/cli-provider-fix:bench/validity.py`),
   run against every run's `content`.
8. Rescoring: `bench/score.py`'s `compute_score`/`AXES` reused; correctness
   recomputed with vacuous/missing-binary stages forced to failed, and (for the
   "full fix" view only) disabled stages excluded from the denominator,
   mirroring `bench/integrity-gates`'s unmerged `279f767`.

`python3 -m pytest tests/` passes unchanged (9 passed). This audit did not
modify any file under `bench/` or `tests/`.
