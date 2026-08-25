# Rescored historical results

This directory is a **recomputation** of the 13 historical result sets under
`results/`, not a new benchmark run. No model was re-invoked, no prompt was
re-sent, and no file under `results/` was modified — every JSON here is a
copy of an already-published run with a corrected score and a validity
verdict attached. `docs/historical-results-audit.md` found that the
published leaderboard over-credited runs in three ways (vacuous passes,
missing-binary passes, disabled-stage passes) and its own closing
recommendation is what this directory carries out: "the historical sets
should be rescored, not rerun: the raw model outputs and logs are already on
disk and sufficient to rescore honestly."

Read `LEADERBOARD.md` for the numbers. This file explains how they were
produced.

## What "corrected" means here

Three modules on this branch (`bench/historical-rescore`, built from
`bench/matrix-final` + `bench/historical-audit`) already implement the fix;
`tools/rescore_historical.py` applies them to the historical JSONs and does
not reimplement any scoring logic of its own beyond spec-based stage gating
(below):

- **`bench/score.py`** (`compute_score`) already treats a stage that found
  nothing to check as excluded from correctness rather than a free pass
  (`stage_inapplicable`, matched retroactively against historical log bodies
  via `VACUOUS_LOG_MARKERS`), and already excludes a `completeness` axis with
  no assertions run (`total_count == 0`) instead of defaulting it to 1.0.
- **`bench/validate.py`** (`classify_run`) classifies a run `invalid` when a
  stage recorded `passed: true` while its own log says `NOT FOUND: <tool>` —
  the missing-binary bug. An invalid run is excluded from every corrected
  aggregate entirely, not scored as a failure; that mirrors how a *fresh* run
  tripping the same gate is already treated by `bench/report.py`.
- **`bench/validity.py`** (`check_content`/`check_result`) is what
  `classify_run` calls to re-derive a content verdict (empty completion,
  agent-transcript contamination, no extractable output on a task that
  expected one) for a run written before the validity gate existed.

The one piece none of those modules can do retroactively on their own:
`compute_score` only excludes a stage disabled by `spec.yaml` when the stage
dict already carries `"skipped": true` — a flag `main`'s runner never wrote,
because `main` never honored `spec.yaml` stage gating in the first place.
Every historical run for a rubric-only task (comprehend, review) or a
lint/static-exempt task (semantics) actually *ran* its disabled stages
against workspace debris and recorded a real (sometimes passing, sometimes
failing) result. `tools/rescore_historical.py` closes that gap: for every
stage `spec.yaml` disables, it replaces the stage's dict with the same clean
`{"skipped": true, ...}` stub a corrected runner would have written, *before*
handing the run to `compute_score` and `classify_run`. This is the only
scoring behavior this tool adds; everything else is `bench/score.py` and
`bench/validate.py` running unmodified.

Two composite formulas are computed per run and stored side by side:

- **`published`**: a byte-for-byte port of `origin/main`'s (commit
  `0f8b215`) old `compute_score`, vendored into
  `tools/rescore_historical.py` as `published_compute_score` — this is
  what actually shipped, not a re-derivation from memory. It reproduces the
  audit's own "published" numbers exactly.
- **`corrected`**: `bench/score.py`'s current `compute_score`, run on the
  spec-gated copy described above.

## What's in each rescored run JSON

Same shape as the original, plus a `_rescore` block:

```json
"_rescore": {
  "method": "recomputation of an already-published run...",
  "source_file": "claude-opus-5/knr-ops/warm/T6-semantics_run0.json",
  "published_score": { "...": "the vendored old formula's output" },
  "corrected_score": { "...": "bench.score.compute_score's output" },
  "corrected_composite_no_idiom": 0.85,
  "validity_verdict": "valid | partial | invalid",
  "invalid_reasons": ["..."],
  "partial_reasons": ["..."],
  "retroactively_skipped_stages": ["lint", "static"]
}
```

`stages` itself is also corrected in place (spec-disabled stages replaced
with skip stubs); the original `stages` as published is always recoverable
from `results/<set>/...` — that tree is untouched.

## Two open questions this rescore does not settle on its own

**Idiom axis.** No historical run carries a `judge` field — the rubric judge
did not exist yet — so `idiom_score` returns 0.0 on all 1,140 runs. It is not
a measured axis for this dataset; it is a fixed penalty of weight 1 (of 9)
applied identically everywhere. `LEADERBOARD.md` reports composites with and
without it. The ranking turns out to be identical either way here, but that
is an empirical result of this dataset, not something the formula
guarantees — the idiom axis should not be read as differentiating any of
these 13 sets.

**Exclude vs. zero-fill for invalid runs.** `bench/validate.py`'s own stated
philosophy is that a run that did not measure the model is "not a
measurement," so it is dropped rather than scored as a failure. That is the
methodology `LEADERBOARD.md`'s main table uses. But dropping shrinks the
denominator, and a model that produced disproportionately more unmeasurable
output (empty completions, stubs, no extractable files) ends up averaged
over a smaller, survivor-biased sample of its own runs than a model that
reliably produced a gradeable-but-mediocre answer. `LEADERBOARD.md`'s
"Robustness check" section recomputes every leader's composite with excluded
runs scored 0.0 instead, and the ordering changes for several sets — most
visibly `qwen 3.8 - local`, which stays #1 under strict exclusion (its worst
44 of 90 runs are dropped from its own average) but falls to the bottom
under zero-fill. Neither view is "the" corrected leaderboard; both are
reported, and the narrative report accompanying this rescore states which
one is being treated as the fairer top-line comparison and why.

## Reproducing this

```
python3 tools/rescore_historical.py             # all 13 sets
python3 tools/rescore_historical.py --set NAME   # one set, for iteration
```

Reads `results/<set>/**/*.json` and `tasks/<stack>/<task>/spec.yaml`, writes
`results-rescored/<set>/...` plus `results-rescored/LEADERBOARD.md` and
`results-rescored/rescore-stats.json`. Nothing under `results/` or `tasks/`
is written to.
