# Harness-invalid vs. model-failure (#69)

The validity gate used to reject two unrelated things under one verdict, and
the scorer excluded both from the denominator. Excluding a model's own empty
answers drops its worst runs from its own average — the same free credit the
vacuous-pass work (#56, #59) removed, arriving through the other door.

`qwen 3.8 - local` is the proof. Under blanket exclusion it holds rank **#1 of
13**, because 44 of its 90 runs are dropped rather than counted. Split the two
causes apart and 19 of those 44 turn out to be the harness's fault and 25 the
model's. Charge it for its own 25 and it lands **#13 of 13** — last.

## The two categories

`bench/validity.py` assigns every rejection reason a category. The sub-reason
strings are unchanged, so nothing already recorded on disk loses its meaning;
the category is a new axis over them.

**HARNESS-INVALID — excluded from every aggregate.** The harness failed to
capture a completion, so no measurement of the model exists. Charging the
model for it would be a false accusation.

| Sub-reason | What happened |
| --- | --- |
| `tool_invocation_markup` | Claude Code's own tool-call markup in the answer |
| `claude_code_ui_marker` | Its UI dividers (`★ Insight`) in the answer |
| `leaked_host_worktree_path` | A real host worktree path — the model saw its own environment |
| `agent_transcript` | Structural transcript markers: a transcript, not an answer |
| `runner_error` / `adapter_error` / `timeout` | The adapter raised, the API errored, the request timed out |
| `tool_missing_scored_as_pass` | A stage passed with its own binary absent from PATH (#56) |
| `unreadable_json` | The result file did not parse |

**MODEL-FAILURE — scored 0, kept in the denominator.** The harness worked and
the model produced nothing usable. This is a measurement, and the worst one
available.

| Sub-reason | What happened |
| --- | --- |
| `empty_or_near_empty` / `empty_completion` | No text at all |
| `short_stub` / `content_too_short` | Too short to be an answer to anything in this suite |
| `no_extractable_output` | Prose where the task's enabled stages needed a file |
| `all_stages_inapplicable` | Every enabled stage had nothing to act on — no artifact was produced |
| `empty_reasoning_exhausted` | Empty, having billed a full output budget on reasoning (below) |

An unrecognised reason categorises as harness-invalid: excluding an unknown
costs one data point, while charging a model for an unclassified failure mode
is the false-accusation error.

When a run shows both, harness-invalid wins. If the harness produced the text,
nothing in it can be attributed to the model.

## The ambiguous case, and the call made on it

`claude-opus-5` returned 31 completions of zero visible characters in its
90-run historical set. Every one billed exactly `max_tokens` (16,384) of
output. Nothing was truncated and no API error was raised: the model spent its
entire output allowance on reasoning and emitted no answer.

**Scored as a model failure.** The harness sets a token budget and asks a
question; how a model spends that budget is part of what a benchmark at that
configuration measures. A model that reliably thinks past its own output
allowance has failed the task as surely as one that answers wrongly — the user
gets nothing either way. Calling it "not a measurement" would mean a model
could raise its average by thinking longer, which is the exact incentive this
work closes.

The counter-argument is real, which is why the call is configurable rather
than asserted: the budget is a harness parameter, so one could argue the
harness under-provisioned the model. `IAC_BENCH_REASONING_EXHAUSTION=harness-invalid`
scores it the other way. The distinct sub-reason `empty_reasoning_exhausted`
is recorded either way, so the choice stays visible in the data and reversible
without a re-run.

Detection is budget-agnostic: a completion under the empty floor whose
provider billed more than 1,024 output tokens spent them somewhere invisible.
That holds whatever `max_tokens` was, and does not fire on genuinely terse
answers — `qwen 3.8 - local`'s stubs bill 43-200 output tokens, matching their
visible length.

Of the 31 empty `claude-opus-5` completions, 17 also carry
`tool_missing_scored_as_pass` and are excluded as harness failures; the
remaining 14 are the ones this decision actually moves.

## The corrected historical leaderboard

All 13 sets, recomputed by `tools/rescore_historical.py`. No model was
re-invoked and nothing under `results/` was modified.

| Result set | Published | #68 exclude-all | #68 zero-fill | **#69 taxonomy** | Rank: pub → #68-exclude → **#69** |
| --- | --- | --- | --- | --- | --- |
| qwen 3.8 - local-low | 0.621 | 0.447 (2) | 0.358 (1) | **0.447** | 10 → 2 → **1** |
| claude-opus-4-8-low | 0.650 | 0.440 (4) | 0.352 (2) | **0.440** | 3 → 4 → **2** |
| glm-5.3-low | 0.640 | 0.430 (6) | 0.344 (3) | **0.430** | 9 → 6 → **3** |
| gpt-5.6-sol-low | 0.658 | 0.431 (5) | 0.340 (4) | **0.425** | 2 → 5 → **4** |
| gpt-5.4-low | 0.648 | 0.424 (8) | 0.339 (5) | **0.424** | 4 → 8 → **5** |
| glm-5.3 | 0.642 | 0.416 (9) | 0.333 (6) | **0.416** | 6 → 9 → **6** |
| claude-opus-5-low | 0.597 | 0.414 (10) | 0.304 (8) | **0.414** | 13 → 10 → **7** |
| gpt-5.4 | 0.641 | 0.428 (7) | 0.328 (7) | **0.411** | 8 → 7 → **8** |
| claude-opus-5 | 0.642 | 0.440 (3) | 0.284 (9) | **0.355** | 7 → 3 → **9** |
| claude-opus-4-8 | 0.620 | 0.353 (12) | 0.268 (10) | **0.353** | 11 → 12 → **10** |
| kimi-k3 | 0.643 | 0.358 (11) | 0.258 (11) | **0.346** | 5 → 11 → **11** |
| qwen36-local | 0.617 | 0.333 (13) | 0.225 (13) | **0.327** | 12 → 13 → **12** |
| qwen 3.8 - local | 0.677 | 0.477 (1) | 0.244 (12) | **0.309** | 1 → 1 → **13** |

Where each set's losses came from:

| Result set | Runs #68 dropped | Harness's fault | Model's fault |
| --- | --- | --- | --- |
| qwen 3.8 - local | 44/90 | 19 | **25** |
| claude-opus-5 | 32/90 | 18 | **14** |
| qwen36-local | 29/90 | 28 | 1 |
| claude-opus-5-low | 24/90 | 24 | 0 |
| kimi-k3 | 21/75 | 19 | 2 |
| gpt-5.4 | 21/90 | 18 | 3 |
| gpt-5.6-sol-low | 19/90 | 18 | 1 |
| everything else | 18/90 | 18 | 0 |

### How this compares to the two views PR #68 published

PR #68 reported both and declined to pick, because the choice turned on
whether unusable model output is "no data" or "a failure" — a question it
could not answer without splitting the two causes apart. The split answers it:
"no data" for a harness failure, "a failure" for an empty answer. The result is
neither of PR #68's views and does not sit between them:

- **vs. exclude-all**: only two sets move materially, and they are exactly the
  two whose losses were largely the model's — `qwen 3.8 - local` (−12 ranks,
  #1 → #13) and `claude-opus-5` (−6, #3 → #9). The other eleven move at most
  ±3 and only because those two vacated the top. Ten of thirteen sets have an
  identical composite under both views, because ten of thirteen lost nothing
  to the model.
- **vs. zero-fill**: every set scores higher, because the 18-per-set
  `tool_missing_scored_as_pass` runs (the pulumi binary being off PATH) stop
  being charged to models that had nothing to do with it. `qwen 3.8 - local`
  still finishes last, but at 0.309 rather than 0.244 — it is being charged
  for its own 25 empty answers and not for the harness's 19.

The three views agree that `qwen 3.8 - local`'s published #1 was an artifact.
They disagree on where it lands, and this one puts it last for a stated
reason: on 71 runs the harness successfully measured, it produced nothing
usable on 25.

Note that `qwen 3.8 - local-low` — the same model at low reasoning effort —
takes #1 with 0 empty answers in 90 runs. The high-effort configuration is
what fails to answer.

## v2 matrix

`results/claude-haiku-4-5-3arm-v2`, 33 runs on disk at time of writing (the
matrix is still running):

| | |
| --- | --- |
| harness-rejected | 0 |
| empty answers | 0 |
| #68 exclude-all | 0.588 |
| #68 zero-fill | 0.588 |
| **#69 taxonomy** | **0.588** |

**Delta: 0.000.** The set is clean — the fixed claude-cli provider (#61)
captures every completion, and haiku-4-5 answers all of them. The taxonomy
change does not move the running v2 matrix at all, which is the expected
result for a harness that works and a model that answers: the split only bites
where one of those two things failed.

## What changed in the code

- `bench/validity.py` — `HARNESS_INVALID` / `MODEL_FAILURE`, the
  `REASON_CATEGORIES` map, `categorize_reason` / `merge_categories`, and the
  `empty_reasoning_exhausted` detector. Harness markers are now tested *before*
  the empty floor, so a 40-character completion of pure tool markup is filed as
  a harness failure rather than as an empty answer.
- `bench/score.py` — `run_category`, `apply_validity`, `score_run`,
  `partition_by_category`. `compute_score` stays a pure function of `stages`
  (that is what `tests/test_score_regression.py` pins over 1,218 historical
  JSONs); the taxonomy is applied one layer up. `aggregate_scores` reports
  `model_failure_runs` and `harness_rejected_runs` separately.
- `bench/validate.py` — `classify_run` gains a `model-failure` verdict and a
  `model_failure_reasons` list. `REJECT_LIMIT` is scoped to harness rejections
  and `CRASH_LIMIT` to `runner_error`, so a set full of empty answers is
  publishable. `MODEL_FAILURE_LIMIT = None` exists to be found by anyone
  looking for the limit that is deliberately absent.
- `bench/report.py` — `harness-rejected: N` and `empty answers: N` as distinct
  lines with distinct reason tables, in both the single-model report and the
  comparison coverage table.

### One bug found while rescoring

`bench/validity.py` carries two content classifiers with different floors:
`check_validity` rejects below 50 characters, `check_content` below 200. A
120-character stub is valid to the first and invalid to the second. Consulting
only the first left `qwen 3.8 - local`'s stubs unzeroed, scored on the vacuous
lint/static passes an empty workspace produces. `run_category` now merges both,
and prefers `bench.validate.classify_run`'s verdict when the caller has one,
since only that path loads the task spec and can see `no_extractable_output`
and `all_stages_inapplicable`. Pinned by
`test_a_stub_between_the_two_floors_is_still_a_model_failure`.
