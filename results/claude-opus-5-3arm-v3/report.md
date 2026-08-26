# Benchmark Report: claude-opus-5-3arm-v3

## Result Integrity

- runs: **36**
- scored: **36**
- **rejected: 0**

- partial: **12** run(s) are scored but flagged.

| Partial reason | Runs |
| --- | --- |
| `no_stage_ran` | 12 |

> `no_stage_ran` means the task's spec disables every build stage, so the run scores on the rubric judge alone. Its provenance is complete and it compares normally.

## Stack × Archetype Matrix

Each cell shows: **pass@1 / pass@k / avg composite score**

| Stack | Comprehend | Generate | Modify | Debug | Review | Semantics | Average |
| --- | --- | --- | --- | --- | --- | --- | --- |
| knr-ops | 0% / 0% / 0.42 | 0% / 0% / 0.67 | 0% / 0% / 0.40 | 0% / 0% / 0.33 | 0% / 0% / 0.42 | 0% / 0% / 0.78 | 0.50 |
| crossplane | — | — | — | — | — | — | 0.00 |
| terraform | — | — | — | — | — | — | 0.00 |
| pulumi-python | — | — | — | — | — | — | 0.00 |
| pulumi-typescript | — | — | — | — | — | — | 0.00 |
| chant | 0% / 0% / 0.42 | 100% / 100% / 0.52 | 100% / 100% / 0.78 | 100% / 100% / 0.78 | 0% / 0% / 0.41 | 0% / 0% / 0.76 | 0.61 |
| bare | 0% / 0% / 0.43 | 0% / 0% / 0.67 | 0% / 0% / 0.67 | 0% / 0% / 0.61 | 0% / 0% / 0.42 | 0% / 0% / 0.78 | 0.60 |

## knr-ops Cold vs Warm Delta

| Task | Cold pass@1 | Warm pass@1 | Delta |
| --- | --- | --- | --- |
| T1-comprehend | 0% | 0% | +0% |
| T2-generate | 100% | 100% | +0% |
| T3-modify | 100% | 100% | +0% |
| T4-debug | 33% | 67% | +33% |
| T5-review | 0% | 0% | +0% |
| T6-semantics | 0% | 0% | +0% |

> **Cold/warm delta measures how much in-context documentation** knr-ops needs to match training-data-driven stacks.

## Token Usage

- Input tokens: 72
- Output tokens: 66,745
- Total: 66,817
- Runs scored: 36 (rejected: 0)