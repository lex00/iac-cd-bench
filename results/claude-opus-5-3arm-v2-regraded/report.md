# Benchmark Report: claude-opus-5-3arm-v2-regraded

## Result Integrity

- runs: **36**
- scored: **36**
- **rejected: 0**

- partial provenance: **12** run(s) carry incomplete provenance (no harness commit, prompt hash or toolchain versions) and cannot be compared against another result set.

## Stack × Archetype Matrix

Each cell shows: **pass@1 / pass@k / avg composite score**

| Stack | Comprehend | Generate | Modify | Debug | Review | Semantics | Average |
| --- | --- | --- | --- | --- | --- | --- | --- |
| knr-ops | 0% / 0% / 0.41 | 0% / 0% / 0.67 | 0% / 0% / 0.47 | 0% / 0% / 0.33 | 0% / 0% / 0.42 | 0% / 0% / 0.78 | 0.51 |
| crossplane | — | — | — | — | — | — | 0.00 |
| terraform | — | — | — | — | — | — | 0.00 |
| pulumi-python | — | — | — | — | — | — | 0.00 |
| pulumi-typescript | — | — | — | — | — | — | 0.00 |
| chant | 0% / 0% / 0.41 | 100% / 100% / 0.52 | 100% / 100% / 0.78 | 100% / 100% / 0.78 | 0% / 0% / 0.42 | 0% / 0% / 0.75 | 0.61 |
| bare | 0% / 0% / 0.43 | 0% / 0% / 0.67 | 0% / 0% / 0.67 | 0% / 0% / 0.67 | 0% / 0% / 0.43 | 0% / 0% / 0.78 | 0.61 |

## knr-ops Cold vs Warm Delta

| Task | Cold pass@1 | Warm pass@1 | Delta |
| --- | --- | --- | --- |
| T1-comprehend | 0% | 0% | +0% |
| T2-generate | 100% | 100% | +0% |
| T3-modify | 100% | 100% | +0% |
| T4-debug | 67% | 67% | +0% |
| T5-review | 0% | 0% | +0% |
| T6-semantics | 0% | 0% | +0% |

> **Cold/warm delta measures how much in-context documentation** knr-ops needs to match training-data-driven stacks.

## Token Usage

- Input tokens: 72
- Output tokens: 64,468
- Total: 64,540
- Runs scored: 36 (rejected: 0)