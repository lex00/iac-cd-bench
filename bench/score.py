"""
Score computation and aggregation for benchmark results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Score axes and their weights
AXES = {
    "correctness": 3,
    "completeness": 2,
    "idiom": 1,
    "safety": 2,
    "consistency": 1,
}


def compute_score(result: dict[str, Any]) -> dict[str, Any]:
    """Compute per-run scores from stage results."""
    stages = result.get("stages", {})
    scores = {}

    # Correctness: stage gates passed
    stage_pass = sum(
        1 for name in ("lint", "static", "semantic")
        if stages.get(name, {}).get("passed", False)
    )
    total_stages = 3
    if stages.get("e2e"):
        total_stages = 4
        stage_pass += 1 if stages["e2e"].get("passed", False) else 0
    scores["correctness"] = stage_pass / total_stages if total_stages else 0

    # Completeness: semantic assertion coverage
    semantic = stages.get("semantic", {})
    passed_count = semantic.get("passed_count", 0)
    total_count = semantic.get("total_count", 0)
    scores["completeness"] = passed_count / total_count if total_count else 1.0

    # Safety: binary flag from semantic tests
    # (in full implementation, derived from secret-handling and destructive-op checks)
    scores["safety"] = 1.0 if semantic.get("safety_pass", True) else 0.0

    # Consistency: placeholder, computed across runs in aggregate
    scores["consistency"] = 0.0  # computed at aggregate level

    # Idiom: placeholder, filled by LLM judge
    scores["idiom"] = 0.0  # filled by rubric grader

    # Weighted composite
    composite = sum(scores[axis] * AXES[axis] for axis in AXES) / sum(AXES.values())
    scores["composite"] = composite

    return scores


def aggregate_scores(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate scores across runs, stacks, tasks."""
    # Group by model × stack × task
    groups: dict[tuple[str, ...], list[dict]] = {}
    for r in results:
        key = (r.get("model", "unknown"), r.get("stack", ""), r.get("task", ""))
        groups.setdefault(key, []).append(r)

    aggregates = {}
    for key, runs in groups.items():
        model, stack, task = key

        # Compute consistency: fraction of runs producing same outcome
        outcomes = set()
        for run in runs:
            stages = run.get("stages", {})
            outcome = tuple(
                stages.get(s, {}).get("passed", False) for s in ("lint", "static", "semantic")
            )
            outcomes.add(outcome)
        consistency = 1.0 if len(outcomes) == 1 else 1.0 - (len(outcomes) - 1) / len(runs)

        # Update consistency scores in each run
        for run in runs:
            score = run.setdefault("score", {})
            score["consistency"] = consistency

        # Pass@1: fraction of single runs passing all stages
        pass_at_1 = sum(
            1 for run in runs
            if all(run.get("stages", {}).get(s, {}).get("passed", False) for s in ("lint", "static"))
        ) / len(runs)

        # Pass@k: at least one run passing
        pass_at_k = (
            1
            if any(
                all(run.get("stages", {}).get(s, {}).get("passed", False) for s in ("lint", "static"))
                for run in runs
            )
            else 0
        )

        # Average composite
        composites = [run.get("score", {}).get("composite", 0) for run in runs]
        avg_composite = sum(composites) / len(composites) if composites else 0

        aggregates[f"{model}/{stack}/{task}"] = {
            "pass_at_1": pass_at_1,
            "pass_at_k": pass_at_k,
            "consistency": consistency,
            "avg_composite": avg_composite,
            "num_runs": len(runs),
        }

    return aggregates


def load_results(results_dir: Path, model: str) -> list[dict[str, Any]]:
    """Load all result JSON files for a model."""
    model_name = model.replace("/", "-")
    model_dir = results_dir / model_name
    if not model_dir.exists():
        return []

    results = []
    for f in sorted(model_dir.rglob("*.json")):
        if "run" in f.stem:
            with open(f) as fp:
                result = json.load(fp)
                # Compute scores
                result["score"] = compute_score(result)
                results.append(result)

    return results


def save_aggregate(results: list[dict[str, Any]], out_path: Path) -> None:
    """Save aggregated scores to JSON."""
    aggregates = aggregate_scores(results)
    with open(out_path, "w") as f:
        json.dump(aggregates, f, indent=2)
