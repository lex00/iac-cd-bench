# Benchmark Report: claude-haiku-4-5-3arm-v3

## Result Integrity

- runs: **108**
- scored: **107**
- **rejected: 1**  — excluded from every number below

| Rejection reason | Runs |
| --- | --- |
| `no_extractable_output` | 1 |

> A rejected run did not measure the model: the provider returned no usable completion, a stage's binary was absent while the stage recorded a pass, or every enabled stage had nothing to act on. Such a run is re-run, not reported. `python3 -m bench.validate results/claude-haiku-4-5-3arm-v3 --verbose` lists them.

- partial: **36** run(s) are scored but flagged.

| Partial reason | Runs |
| --- | --- |
| `no_stage_ran` | 36 |

> `no_stage_ran` means the task's spec disables every build stage, so the run scores on the rubric judge alone. Its provenance is complete and it compares normally.

## Stack × Archetype Matrix

Each cell shows: **pass@1 / pass@k / avg composite score**

| Stack | Comprehend | Generate | Modify | Debug | Review | Semantics | Average |
| --- | --- | --- | --- | --- | --- | --- | --- |
| knr-ops | 0% / 0% / 0.40 | 0% / 0% / 0.64 | 0% / 0% / 0.32 | 0% / 0% / 0.31 | 0% / 0% / 0.41 | 0% / 0% / 0.77 | 0.47 |
| crossplane | — | — | — | — | — | — | 0.00 |
| terraform | — | — | — | — | — | — | 0.00 |
| pulumi-python | — | — | — | — | — | — | 0.00 |
| pulumi-typescript | — | — | — | — | — | — | 0.00 |
| chant | 0% / 0% / 0.40 | 100% / 100% / 0.78 | 100% / 100% / 0.78 | 67% / 100% / 0.74 | 0% / 0% / 0.41 | 0% / 0% / 0.75 | 0.64 |
| bare | 0% / 0% / 0.41 | 0% / 0% / 0.67 | 0% / 0% / 0.67 | 0% / 0% / 0.63 | 0% / 0% / 0.42 | 0% / 0% / 0.75 | 0.59 |

## knr-ops Cold vs Warm Delta

| Task | Cold pass@1 | Warm pass@1 | Delta |
| --- | --- | --- | --- |
| T1-comprehend | 0% | 0% | +0% |
| T2-generate | 100% | 100% | +0% |
| T3-modify | 78% | 78% | +0% |
| T4-debug | 56% | 62% | +7% |
| T5-review | 0% | 0% | +0% |
| T6-semantics | 0% | 0% | +0% |

> **Cold/warm delta measures how much in-context documentation** knr-ops needs to match training-data-driven stacks.

## Token Usage

- Input tokens: 140,463
- Output tokens: 405,835
- Total: 546,298
- Runs scored: 107 (rejected: 1)