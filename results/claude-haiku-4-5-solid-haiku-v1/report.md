# Benchmark Report: claude-haiku-4-5-solid-haiku-v1

## Result Integrity

- runs: **48**
- scored: **47**
- **rejected: 1**  — excluded from every number below

| Rejection reason | Runs |
| --- | --- |
| `no_extractable_output` | 1 |

> A rejected run did not measure the model: the provider returned no usable completion, a stage's binary was absent while the stage recorded a pass, or every enabled stage had nothing to act on. Such a run is re-run, not reported. `python3 -m bench.validate results/claude-haiku-4-5-solid-haiku-v1 --verbose` lists them.

- partial: **16** run(s) are scored but flagged.

| Partial reason | Runs |
| --- | --- |
| `no_stage_ran` | 16 |

> `no_stage_ran` means the task's spec disables every build stage, so the run scores on the rubric judge alone. Its provenance is complete and it compares normally.

## Stack × Archetype Matrix

Each cell shows: **pass@1 / pass@k / avg composite score**

| Stack | Comprehend | Generate | Modify | Debug | Review | Semantics | Average |
| --- | --- | --- | --- | --- | --- | --- | --- |
| knr-ops | 0% / 0% / 0.70 | 0% / 0% / 0.67 | 0% / 0% / 0.29 | 0% / 0% / 0.39 | 0% / 0% / 0.74 | 0% / 0% / 0.76 | 0.59 |
| crossplane | — | — | — | — | — | — | 0.00 |
| terraform | 0% / 0% / 0.70 | 0% / 0% / 0.56 | 50% / 100% / 0.50 | 0% / 0% / 0.22 | 0% / 0% / 0.50 | 0% / 0% / 0.76 | 0.54 |
| pulumi-python | — | — | — | — | — | — | 0.00 |
| pulumi-typescript | — | — | — | — | — | — | 0.00 |
| chant | 0% / 0% / 0.69 | 100% / 100% / 0.78 | 100% / 100% / 0.78 | 50% / 100% / 0.72 | 0% / 0% / 0.73 | 0% / 0% / 0.73 | 0.74 |
| bare | 0% / 0% / 0.74 | 0% / 0% / 0.56 | 100% / 100% / 0.78 | 100% / 100% / 0.78 | 0% / 0% / 0.75 | 0% / 0% / 0.73 | 0.72 |

## knr-ops Cold vs Warm Delta

| Task | Cold pass@1 | Warm pass@1 | Delta |
| --- | --- | --- | --- |
| T1-comprehend | 0% | 0% | +0% |
| T2-generate | 50% | 50% | +0% |
| T3-modify | 50% | 75% | +25% |
| T4-debug | 75% | 67% | -8% |
| T5-review | 0% | 0% | +0% |
| T6-semantics | 0% | 0% | +0% |

> **Cold/warm delta measures how much in-context documentation** knr-ops needs to match training-data-driven stacks.

## Token Usage

- Input tokens: 63,895
- Output tokens: 186,898
- Total: 250,793
- Runs scored: 47 (rejected: 1)