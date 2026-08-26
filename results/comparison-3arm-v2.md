# Comparative Benchmark Report

Comparing 2 result sets: `claude-haiku-4-5-3arm-v2-regraded`, `claude-opus-5-3arm-v2-regraded`

## Comparability

Harness commit, toolchain versions, provider and reasoning effort agree across every set below.

## Composite Score by Stack

Mean composite score across all runs in the stack.

| Stack | claude-haiku-4-5-3arm-v2-regraded | claude-opus-5-3arm-v2-regraded |
| --- | --- | --- |
| knr-ops | 0.60 | 0.62 |
| crossplane | — | — |
| terraform | — | — |
| pulumi-python | — | — |
| pulumi-typescript | — | — |
| chant | 0.73 | 0.71 |
| bare | 0.70 | 0.71 |
| **Overall** | 0.68 | 0.68 |

## Composite Score by Stack × Archetype

| Stack / Archetype | claude-haiku-4-5-3arm-v2-regraded | claude-opus-5-3arm-v2-regraded |
| --- | --- | --- |
| knr-ops / Comprehend | 0.71 | 0.72 |
| knr-ops / Generate | 0.62 | 0.67 |
| knr-ops / Modify | 0.40 | 0.47 |
| knr-ops / Debug | 0.31 | 0.33 |
| knr-ops / Review | 0.72 | 0.74 |
| knr-ops / Semantics | 0.77 | 0.78 |
| chant / Comprehend | 0.69 | 0.72 |
| chant / Generate | 0.78 | 0.52 |
| chant / Modify | 0.78 | 0.78 |
| chant / Debug | 0.74 | 0.78 |
| chant / Review | 0.73 | 0.74 |
| chant / Semantics | 0.67 | 0.75 |
| bare / Comprehend | 0.73 | 0.75 |
| bare / Generate | 0.67 | 0.67 |
| bare / Modify | 0.67 | 0.67 |
| bare / Debug | 0.67 | 0.67 |
| bare / Review | 0.75 | 0.74 |
| bare / Semantics | 0.75 | 0.78 |

## Coverage

| Result set | Scored | Rejected | Judged runs | Judge model | Judge prompt |
| --- | --- | --- | --- | --- | --- |
| claude-haiku-4-5-3arm-v2-regraded | 107 | **1** | 36 | claude-haiku-4-5 | 8bac4198059e310e |
| claude-opus-5-3arm-v2-regraded | 36 | **0** | 12 | claude-haiku-4-5 | 8bac4198059e310e |

> Rejected runs contribute to no cell above. A run the gates rejected did
> not measure the model, so it has to happen again rather than be averaged in.

> Runs without a judge verdict score 0.0 on the idiom axis (weight 1 of 9),
> so composites are only strictly comparable between equally judged sets.