# Historical Results — Rescored Leaderboard

Every run below is an existing, previously published run recomputed under the corrected scorer on `bench/historical-rescore` (`bench/score.py` + `bench/validate.py` + `bench/validity.py`). No model was re-invoked. See `results-rescored/README.md` for method, and `docs/historical-results-audit.md` for the audit that motivated this rescore.

**Sanity check (asserted, not just reported): no result set's corrected average composite exceeds its published average composite.** Verified for all 13 sets below.

**Note:** a small number of *individual* runs (not set averages) show a higher corrected composite than published — see "Per-run composite increases" below for the full list and why.

## Leaderboard: published vs. corrected

| # pub | Result set | Published | # corr | Corrected | Δ | Runs excluded | Excluded reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | qwen 3.8 - local | 0.677 | 1 | 0.477 | -0.200 | 44/90 | 37× `content_too_short`, 37× `no_extractable_output`, 18× `tool_missing_scored_as_pass`, 6× `all_stages_inapplicable`, 1× `agent_transcript` |
| 2 | gpt-5.6-sol-low | 0.658 | 5 | 0.431 | -0.227 | 19/90 | 18× `tool_missing_scored_as_pass`, 1× `all_stages_inapplicable` |
| 3 | claude-opus-4-8-low | 0.650 | 4 | 0.440 | -0.210 | 18/90 | 18× `tool_missing_scored_as_pass` |
| 4 | gpt-5.4-low | 0.648 | 8 | 0.424 | -0.224 | 18/90 | 18× `tool_missing_scored_as_pass` |
| 5 | kimi-k3 | 0.643 | 11 | 0.358 | -0.284 | 21/75 | 18× `tool_missing_scored_as_pass`, 2× `content_too_short`, 2× `no_extractable_output`, 1× `agent_transcript` |
| 6 | glm-5.3 | 0.642 | 9 | 0.416 | -0.226 | 18/90 | 18× `tool_missing_scored_as_pass` |
| 7 | claude-opus-5 | 0.642 | 3 | 0.440 | -0.202 | 32/90 | 31× `empty_completion`, 31× `no_extractable_output`, 18× `tool_missing_scored_as_pass`, 2× `all_stages_inapplicable` |
| 8 | gpt-5.4 | 0.641 | 7 | 0.428 | -0.212 | 21/90 | 18× `tool_missing_scored_as_pass`, 3× `content_too_short`, 3× `no_extractable_output` |
| 9 | glm-5.3-low | 0.640 | 6 | 0.430 | -0.209 | 18/90 | 18× `tool_missing_scored_as_pass` |
| 10 | qwen 3.8 - local-low | 0.621 | 2 | 0.447 | -0.174 | 18/90 | 18× `tool_missing_scored_as_pass` |
| 11 | claude-opus-4-8 | 0.620 | 12 | 0.353 | -0.267 | 18/75 | 18× `tool_missing_scored_as_pass` |
| 12 | qwen36-local | 0.617 | 13 | 0.333 | -0.285 | 29/90 | 19× `runner_error`, 19× `empty_completion`, 15× `no_extractable_output`, 9× `tool_missing_scored_as_pass`, 1× `content_too_short` |
| 13 | claude-opus-5-low | 0.597 | 10 | 0.414 | -0.183 | 24/90 | 16× `tool_missing_scored_as_pass`, 8× `runner_error`, 8× `empty_completion`, 2× `no_extractable_output` |

## Same leaderboard, corrected composite excluding the idiom axis

Idiom (weight 1 of 9, or 1 of 8 on a run where completeness is also inapplicable) carries a rubric-judge verdict — `bench.score.idiom_score` — and **every one of the 1,140 historical runs has none** (no run carries a `judge` field; the rubric judge did not exist yet when these sets were produced). Idiom scores 0.0 on literally every run in every one of the 13 sets, so it is not a measured axis for this dataset at all — it is a fixed penalty applied uniformly. This view drops it and renormalizes over the remaining applicable axes.

| # pub | Result set | Corrected (w/ idiom) | # (no idiom) | Corrected (no idiom) | Rank moves? |
| --- | --- | --- | --- | --- | --- |
| 1 | qwen 3.8 - local | 0.477 | 1 | 0.544 | no |
| 2 | gpt-5.6-sol-low | 0.431 | 5 | 0.492 | no |
| 3 | claude-opus-4-8-low | 0.440 | 4 | 0.503 | no |
| 4 | gpt-5.4-low | 0.424 | 8 | 0.484 | no |
| 5 | kimi-k3 | 0.358 | 11 | 0.418 | no |
| 6 | glm-5.3 | 0.416 | 9 | 0.476 | no |
| 7 | claude-opus-5 | 0.440 | 3 | 0.504 | no |
| 8 | gpt-5.4 | 0.428 | 7 | 0.489 | no |
| 9 | glm-5.3-low | 0.430 | 6 | 0.491 | no |
| 10 | qwen 3.8 - local-low | 0.447 | 2 | 0.511 | no |
| 11 | claude-opus-4-8 | 0.353 | 12 | 0.407 | no |
| 12 | qwen36-local | 0.333 | 13 | 0.388 | no |
| 13 | claude-opus-5-low | 0.414 | 10 | 0.474 | no |

**Ordering is stable once idiom is dropped.** Since idiom is a uniform 0.0 across every run in every set, this isolates whether idiom's fixed weight is doing any of the reordering work in the corrected leaderboard above, versus the reordering coming entirely from correctness/completeness/safety, which the historical runs did genuinely measure.

## Robustness check: exclude vs. zero-fill invalid runs

The corrected leaderboard above follows the instructed methodology: a run `bench.validate.classify_run` marks `invalid` is dropped from the average entirely, per that module's own stated philosophy — "a trial which did not measure the tool is not a low score, it is not a measurement." That is defensible, but it means a model that produced disproportionately more unmeasurable output (empty completions, stubs, no extractable files) gets averaged over a smaller, survivor-biased sample than a model that reliably produced a gradeable-but-mediocre answer. This section checks whether that shrinks-the-denominator effect is doing real work by re-scoring every excluded run as 0.0 instead of dropping it, and keeping it in the denominator.

| # pub | Result set | Corrected (excluded dropped) | # (excluded=0) | Corrected (excluded=0) | Rank moves? |
| --- | --- | --- | --- | --- | --- |
| 1 | qwen 3.8 - local | 0.477 | 12 | 0.244 | yes (1 -> 12) |
| 2 | gpt-5.6-sol-low | 0.431 | 4 | 0.340 | yes (5 -> 4) |
| 3 | claude-opus-4-8-low | 0.440 | 2 | 0.352 | yes (4 -> 2) |
| 4 | gpt-5.4-low | 0.424 | 5 | 0.339 | yes (8 -> 5) |
| 5 | kimi-k3 | 0.358 | 11 | 0.258 | no |
| 6 | glm-5.3 | 0.416 | 6 | 0.333 | yes (9 -> 6) |
| 7 | claude-opus-5 | 0.440 | 9 | 0.284 | yes (3 -> 9) |
| 8 | gpt-5.4 | 0.428 | 7 | 0.328 | no |
| 9 | glm-5.3-low | 0.430 | 3 | 0.344 | yes (6 -> 3) |
| 10 | qwen 3.8 - local-low | 0.447 | 1 | 0.358 | yes (2 -> 1) |
| 11 | claude-opus-4-8 | 0.353 | 10 | 0.268 | yes (12 -> 10) |
| 12 | qwen36-local | 0.333 | 13 | 0.225 | no |
| 13 | claude-opus-5-low | 0.414 | 8 | 0.304 | yes (10 -> 8) |

**Ordering is NOT stable under zero-filling.** The exclude-vs-penalize choice changes the ordering — see README.md and the narrative report for which sets move and why; this is the single largest methodological sensitivity found in this rescore.

## Per-stack composite (n-weighted, all 13 sets combined)

| Stack | n | Published | n scored | Corrected | Δ |
| --- | --- | --- | --- | --- | --- |
| knr-ops | 240 | 0.644 | 223 | 0.397 | -0.248 |
| crossplane | 225 | 0.675 | 213 | 0.435 | -0.240 |
| terraform | 225 | 0.600 | 206 | 0.408 | -0.192 |
| pulumi-python | 225 | 0.648 | 100 | 0.431 | -0.216 |
| pulumi-typescript | 225 | 0.624 | 100 | 0.418 | -0.206 |
| **overall** | 1140 | 0.638 | 842 | 0.416 | -0.223 |

### Per-model x stack composite (published)

| Result set | knr-ops | crossplane | terraform | pulumi-python | pulumi-typescript |
| --- | --- | --- | --- | --- | --- |
| claude-opus-5 | 0.60 | 0.70 | 0.64 | 0.65 | 0.62 |
| claude-opus-5-low | 0.65 | 0.62 | 0.55 | 0.65 | 0.51 |
| claude-opus-4-8 | 0.65 | 0.64 | 0.56 | 0.64 | 0.61 |
| claude-opus-4-8-low | 0.63 | 0.68 | 0.63 | 0.68 | 0.63 |
| gpt-5.4 | 0.65 | 0.65 | 0.60 | 0.67 | 0.63 |
| gpt-5.4-low | 0.66 | 0.67 | 0.59 | 0.67 | 0.65 |
| gpt-5.6-sol-low | 0.66 | 0.67 | 0.62 | 0.69 | 0.66 |
| glm-5.3 | 0.63 | 0.66 | 0.61 | 0.67 | 0.64 |
| glm-5.3-low | 0.65 | 0.67 | 0.58 | 0.66 | 0.63 |
| kimi-k3 | 0.65 | 0.73 | 0.57 | 0.64 | 0.63 |
| qwen 3.8 - local | 0.67 | 0.72 | 0.68 | 0.68 | 0.63 |
| qwen 3.8 - local-low | 0.59 | 0.66 | 0.63 | 0.64 | 0.59 |
| qwen36-local | 0.66 | 0.72 | 0.53 | 0.44 | 0.68 |

### Per-model x stack composite (corrected)

| Result set | knr-ops | crossplane | terraform | pulumi-python | pulumi-typescript |
| --- | --- | --- | --- | --- | --- |
| claude-opus-5 | 0.39 | 0.48 | 0.47 | 0.45 | 0.45 |
| claude-opus-5-low | 0.44 | 0.41 | 0.40 | 0.45 | 0.29 |
| claude-opus-4-8 | 0.35 | 0.39 | 0.38 | 0.29 | 0.29 |
| claude-opus-4-8-low | 0.41 | 0.46 | 0.44 | 0.45 | 0.45 |
| gpt-5.4 | 0.44 | 0.43 | 0.40 | 0.44 | 0.45 |
| gpt-5.4-low | 0.42 | 0.42 | 0.40 | 0.45 | 0.45 |
| gpt-5.6-sol-low | 0.42 | 0.42 | 0.43 | 0.45 | 0.45 |
| glm-5.3 | 0.39 | 0.41 | 0.42 | 0.45 | 0.45 |
| glm-5.3-low | 0.41 | 0.45 | 0.41 | 0.44 | 0.45 |
| kimi-k3 | 0.36 | 0.45 | 0.32 | 0.29 | 0.29 |
| qwen 3.8 - local | 0.45 | 0.51 | 0.44 | 0.49 | 0.49 |
| qwen 3.8 - local-low | 0.42 | 0.44 | 0.48 | 0.45 | 0.45 |
| qwen36-local | 0.32 | 0.41 | 0.29 | — | 0.29 |

## Biggest rank movers

Ranked by |published rank − corrected(exclude) rank|. The corrected(zero-fill) rank is shown alongside because for some sets (`qwen 3.8 - local` most visibly) the two corrected views disagree sharply — see "Robustness check" above.

| Result set | Published rank | Corrected(exclude) rank | Corrected(zero-fill) rank | Rank Δ (exclude) | Composite Δ | Runs excluded |
| --- | --- | --- | --- | --- | --- | --- |
| qwen 3.8 - local | 1 | 1 | 12 | +0 | -0.200 | 44/90 |
| qwen 3.8 - local-low | 10 | 2 | 1 | -8 | -0.174 | 18/90 |
| glm-5.3-low | 9 | 6 | 3 | -3 | -0.209 | 18/90 |
| kimi-k3 | 5 | 11 | 11 | +6 | -0.284 | 21/75 |
| claude-opus-5-low | 13 | 10 | 8 | -3 | -0.183 | 24/90 |
| claude-opus-5 | 7 | 3 | 9 | -4 | -0.202 | 32/90 |

## Coverage and exclusions, per set

| Result set | Total | Valid | Partial | Invalid (excluded) | Retroactively-skipped stages |
| --- | --- | --- | --- | --- | --- |
| claude-opus-5 | 90 | 0 | 58 | 32 | 120 |
| claude-opus-5-low | 90 | 0 | 66 | 24 | 111 |
| claude-opus-4-8 | 75 | 0 | 57 | 18 | 90 |
| claude-opus-4-8-low | 90 | 0 | 72 | 18 | 120 |
| gpt-5.4 | 90 | 0 | 69 | 21 | 120 |
| gpt-5.4-low | 90 | 0 | 72 | 18 | 120 |
| gpt-5.6-sol-low | 90 | 0 | 71 | 19 | 120 |
| glm-5.3 | 90 | 0 | 72 | 18 | 120 |
| glm-5.3-low | 90 | 0 | 72 | 18 | 120 |
| kimi-k3 | 75 | 0 | 54 | 21 | 90 |
| qwen 3.8 - local | 90 | 0 | 46 | 44 | 120 |
| qwen 3.8 - local-low | 90 | 0 | 72 | 18 | 120 |
| qwen36-local | 90 | 0 | 61 | 29 | 90 |

> "Valid" vs "partial": every historical run predates the provenance stamp (harness commit, toolchain fingerprint, prompt hash), so `bench.validate.classify_run` marks every non-excluded run `partial` rather than `valid` — this is expected for the whole dataset and is not a new finding. Partial runs are still counted in the corrected composite; only `invalid` runs are excluded.

## Per-run composite increases

Individual runs (not set averages) where the corrected composite exceeds the published one. This can happen even though the corrected scorer never awards new credit, because removing a *disabled* stage's leftover real result can remove a genuine failure (not just a fake pass) from the correctness denominator — see README.md for why this is expected, not a bug in this tool.

| Result set | Run | Published | Corrected | Δ |
| --- | --- | --- | --- | --- |
| claude-opus-5 | claude-opus-5/knr-ops/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| claude-opus-5 | claude-opus-5/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| claude-opus-5 | claude-opus-5/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| claude-opus-5 | claude-opus-5/pulumi-typescript/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| claude-opus-5 | claude-opus-5/pulumi-typescript/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| claude-opus-5 | claude-opus-5/pulumi-typescript/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| claude-opus-5-low | claude-opus-5-low/knr-ops/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| claude-opus-5-low | claude-opus-5-low/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| claude-opus-5-low | claude-opus-5-low/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| claude-opus-4-8-low | claude-opus-4-8-low/knr-ops/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| claude-opus-4-8-low | claude-opus-4-8-low/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| claude-opus-4-8-low | claude-opus-4-8-low/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| claude-opus-4-8-low | claude-opus-4-8-low/pulumi-typescript/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| claude-opus-4-8-low | claude-opus-4-8-low/pulumi-typescript/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| claude-opus-4-8-low | claude-opus-4-8-low/pulumi-typescript/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4 | gpt-5.4/knr-ops/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4 | gpt-5.4/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4 | gpt-5.4/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4 | gpt-5.4/pulumi-typescript/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4 | gpt-5.4/pulumi-typescript/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4 | gpt-5.4/pulumi-typescript/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4-low | gpt-5.4-low/knr-ops/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4-low | gpt-5.4-low/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4-low | gpt-5.4-low/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4-low | gpt-5.4-low/pulumi-typescript/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4-low | gpt-5.4-low/pulumi-typescript/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| gpt-5.4-low | gpt-5.4-low/pulumi-typescript/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| gpt-5.6-sol-low | gpt-5.6-sol-low/knr-ops/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| gpt-5.6-sol-low | gpt-5.6-sol-low/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| gpt-5.6-sol-low | gpt-5.6-sol-low/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| gpt-5.6-sol-low | gpt-5.6-sol-low/pulumi-typescript/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| gpt-5.6-sol-low | gpt-5.6-sol-low/pulumi-typescript/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| gpt-5.6-sol-low | gpt-5.6-sol-low/pulumi-typescript/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| glm-5.3 | glm-5.3/knr-ops/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| glm-5.3 | glm-5.3/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| glm-5.3 | glm-5.3/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| glm-5.3 | glm-5.3/pulumi-typescript/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| glm-5.3 | glm-5.3/pulumi-typescript/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| glm-5.3 | glm-5.3/pulumi-typescript/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| glm-5.3-low | glm-5.3-low/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| glm-5.3-low | glm-5.3-low/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| glm-5.3-low | glm-5.3-low/pulumi-typescript/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| glm-5.3-low | glm-5.3-low/pulumi-typescript/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| glm-5.3-low | glm-5.3-low/pulumi-typescript/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| qwen 3.8 - local | qwen 3.8 - local/knr-ops/warm/T6-semantics_run0.json | 0.635 | 0.746 | +0.111 |
| qwen 3.8 - local | qwen 3.8 - local/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| qwen 3.8 - local | qwen 3.8 - local/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| qwen 3.8 - local | qwen 3.8 - local/pulumi-typescript/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| qwen 3.8 - local | qwen 3.8 - local/pulumi-typescript/warm/T6-semantics_run1.json | 0.635 | 0.746 | +0.111 |
| qwen 3.8 - local | qwen 3.8 - local/pulumi-typescript/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| qwen 3.8 - local-low | qwen 3.8 - local-low/knr-ops/warm/T6-semantics_run0.json | 0.667 | 0.778 | +0.111 |
| qwen 3.8 - local-low | qwen 3.8 - local-low/knr-ops/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| qwen 3.8 - local-low | qwen 3.8 - local-low/knr-ops/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| qwen 3.8 - local-low | qwen 3.8 - local-low/pulumi-typescript/warm/T6-semantics_run0.json | 0.635 | 0.746 | +0.111 |
| qwen 3.8 - local-low | qwen 3.8 - local-low/pulumi-typescript/warm/T6-semantics_run1.json | 0.667 | 0.778 | +0.111 |
| qwen 3.8 - local-low | qwen 3.8 - local-low/pulumi-typescript/warm/T6-semantics_run2.json | 0.667 | 0.778 | +0.111 |
| glm-5.3-low | glm-5.3-low/knr-ops/warm/T6-semantics_run0.json | 0.603 | 0.714 | +0.111 |
