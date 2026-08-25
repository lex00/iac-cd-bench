# IaC/CD Understanding Benchmark

Measures how well AI models understand continuous-delivery workflows across five infrastructure-as-code stacks:

| Stack | Delivery model | Paradigm |
|---|---|---|
| **knr-ops** | Flux + kustomize + konflate PR renders | Plain YAML, GitOps monorepo |
| **Crossplane** | CRD claims + Compositions + functions | Kubernetes-native control plane |
| **Terraform** | plan/apply lifecycle + state files | Declarative HCL with state |
| **Pulumi (Python)** | preview/stack + native Python | General-purpose language + state |
| **Pulumi (TypeScript)** | preview/stack + native TS | General-purpose language + state |

## Task Archetypes

1. **Comprehend** — read a repo slice, predict delivery behavior
2. **Generate** — author config from a specification
3. **Modify** — evolve existing config safely
4. **Debug** — fix a seeded defect
5. **Review** — audit a change before delivery

## Design

- **One scenario, five stacks**: all stacks implement the same infrastructure spec so results compare tools, not problems.
- **Four-stage validation ladder**: lint → tool-native static check → structural pytest assertions → live e2e (kind + LocalStack)
- **knr-ops cold/warm**: tasks run without docs (cold) and with README slices (warm) to measure documentation-driven generalization vs training-data recall
- **k=3, variance measured rather than assumed**: `temperature=0` is sent only where the adapter's target API accepts it (the OpenAI-compatible adapter's generic and GLM code paths). Anthropic's Claude models never receive an explicit `temperature` — current Claude models reject any value other than the default once extended/adaptive thinking is enabled, so the adapter omits it entirely rather than pass a value some requests would reject. gpt-5+ and kimi/qwen models likewise reject `temperature` and use `reasoning_effort` instead. Since temperature 0 isn't achievable across the whole model matrix, each task runs k=3 times and the **consistency axis** (pass@1 vs pass@3 agreement) reports the actual output variance directly instead of assuming determinism.
- **Reasoning effort pinned and recorded**: `--reasoning-effort` fixes one effort level per model for a full suite (e.g. `low`, `max`); every run's result JSON records the `reasoning_effort` value the adapter used, so cross-model comparisons can confirm effort was held constant within a suite rather than drifting between models or runs.

## Quick Start

```bash
# Set up toolchain
mise install

# Run one task against a model
python -m bench.runner --model anthropic/claude-sonnet-4-20250514 --stack knr-ops --task T1-comprehend -k 3

# Run everything (static stages only)
python -m bench.runner --model anthropic/claude-sonnet-4-20250514 --stacks all -k 3

# Include e2e tier
python -m bench.runner --model anthropic/claude-sonnet-4-20250514 --stacks all -k 3 --e2e

# Score the idiom axis with the rubric judge (extra API calls, off by default)
python -m bench.runner --model anthropic/claude-sonnet-4-20250514 --stacks all -k 3 \
    --judge --judge-model claude-haiku-4-5

# Generate report
python -m bench.report --model anthropic/claude-sonnet-4-20250514

# Compare result sets side by side
python -m bench.report --compare results/claude-opus-5 results/gpt-5.4

# Check this machine has every binary the stacks need (the runner does this
# itself and refuses to start without them)
python -m bench.preflight --stacks all

# Classify a result set valid / partial / rejected before quoting a number
python -m bench.validate results/claude-opus-5 --verbose
```

## Result integrity

Runs that did not measure the model are rejected rather than scored, and a
rejected run gets no number anywhere. The rules, and which chant-bench /
aws-bench mechanism each was ported from, are in
[docs/result-integrity.md](docs/result-integrity.md).

Every result set under `results/` predates these gates and fails validation
today. Their numbers should be re-run rather than quoted.

## Results

Stack × archetype matrix, per-model:
- **Correctness**: stage gates passed, e2e authoritative
- **Completeness**: spec coverage %
- **Idiom**: rubric-scored by an LLM judge on tasks with a `rubric:` block (T1, T5), run under `--judge`; the judge model id and prompt hash are pinned in each result JSON. Unjudged runs score 0.0 on this axis.
- **Safety**: secrets handling, destructive-op detection
- **Consistency**: pass@1 vs pass@3 (agreement across k=3)
- **Efficiency**: tokens, wall time, cost

## Caveats

- e2e uses LocalStack for AWS services; RDS/IAM behaviors may differ from real AWS
- CAPI/CAPA cluster provisioning is covered by reasoning tasks, not e2e (requires real AWS)
- Public repo means results degrade as generalization proxy once scraped

## License

MIT
