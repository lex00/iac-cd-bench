"""
Score computation and aggregation for benchmark results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bench.validity import run_validity

# Score axes and their weights
AXES = {
    "correctness": 3,
    "completeness": 2,
    "idiom": 1,
    "safety": 2,
    "consistency": 1,
}


def idiom_score(result: dict[str, Any]) -> float:
    """Idiom axis: the rubric judge's weighted verdict, or 0.0 when absent.

    A run only carries `judge` when it was produced with `--judge` on a task
    that has a `rubric:` block; everything else degrades to the pre-judge
    behaviour.
    """
    verdict = result.get("judge")
    if not isinstance(verdict, dict):
        return 0.0
    try:
        return max(0.0, min(1.0, float(verdict.get("idiom", 0.0))))
    except (TypeError, ValueError):
        return 0.0


def judge_metadata(result: dict[str, Any]) -> dict[str, Any] | None:
    """Reproducibility metadata for a judged run: model id + prompt hash."""
    verdict = result.get("judge")
    if not isinstance(verdict, dict):
        return None
    return {
        "judge_model": verdict.get("judge_model"),
        "prompt_sha256": verdict.get("prompt_sha256"),
    }


def compute_score(result: dict[str, Any]) -> dict[str, Any]:
    """Compute per-run scores from stage results."""
    stages = result.get("stages", {})
    scores = {}

    # Correctness: stage gates passed, averaged only over stages that
    # actually ran. A stage the spec disabled (recorded by run_task as
    # {"skipped": True, ...}) is excluded from both numerator and
    # denominator — it must never count as a pass. Historical result JSONs
    # (written before stage gating existed) never carry a `skipped` key, so
    # every stage present there is still treated as attempted, keeping their
    # composites unchanged (see tests/test_score_regression.py).
    stage_pass = 0
    total_stages = 0
    for name in ("lint", "static", "semantic"):
        stage_result = stages.get(name, {})
        if stage_result.get("skipped"):
            continue
        total_stages += 1
        if stage_result.get("passed", False):
            stage_pass += 1
    e2e_result = stages.get("e2e")
    if e2e_result and not e2e_result.get("skipped"):
        total_stages += 1
        if e2e_result.get("passed", False):
            stage_pass += 1
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

    # Idiom: rubric LLM judge verdict, written by the runner under --judge.
    # Tasks without a rubric, and runs scored before the judge existed, keep
    # the historical 0.0 so composites stay comparable across result sets.
    scores["idiom"] = idiom_score(result)

    # Weighted composite
    composite = sum(scores[axis] * AXES[axis] for axis in AXES) / sum(AXES.values())
    scores["composite"] = composite

    return scores


def aggregate_scores(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate scores across runs, stacks, tasks.

    #59: a run the validity gate rejects (tool-narration leak, or a stub too
    short to be a real answer — see bench/validity.py) is excluded from
    every metric here rather than scored as a failure. It is never silently
    dropped, though: `rejected_runs` (and `rejected_reasons`, broken down by
    cause) are always recorded on the aggregate entry, so a report built
    from this can surface "rejected: N" instead of a composite score that
    quietly folded contaminated runs in as ordinary failures.

    Runs with no `content` key at all predate content being recorded (or are
    synthetic test fixtures) and can't be judged by the gate — they are
    treated as valid, unaffected by this change.
    """
    # Group by model × stack × task
    groups: dict[tuple[str, ...], list[dict]] = {}
    for r in results:
        key = (r.get("model", "unknown"), r.get("stack", ""), r.get("task", ""))
        groups.setdefault(key, []).append(r)

    aggregates = {}
    for key, runs in groups.items():
        model, stack, task = key

        valid_runs = [r for r in runs if run_validity(r)["valid"]]
        invalid_runs = [r for r in runs if not run_validity(r)["valid"]]

        # Compute consistency: fraction of (valid) runs producing the same
        # outcome. A rejected run's stage results are gate noise (a run that
        # narrated tool use instead of answering emits no code, so lint/
        # static/semantic trivially fail on nothing) — folding it in would
        # confound consistency with contamination, exactly what #59 flagged.
        outcomes = set()
        for run in valid_runs:
            stages = run.get("stages", {})
            outcome = tuple(
                stages.get(s, {}).get("passed", False) for s in ("lint", "static", "semantic")
            )
            outcomes.add(outcome)
        consistency = (
            (1.0 if len(outcomes) <= 1 else 1.0 - (len(outcomes) - 1) / len(valid_runs))
            if valid_runs else 0.0
        )

        # Update consistency scores in each valid run
        for run in valid_runs:
            score = run.setdefault("score", {})
            score["consistency"] = consistency

        # Pass@1: fraction of single (valid) runs passing all stages
        pass_at_1 = (
            sum(
                1 for run in valid_runs
                if all(run.get("stages", {}).get(s, {}).get("passed", False) for s in ("lint", "static"))
            ) / len(valid_runs)
            if valid_runs else 0.0
        )

        # Pass@k: at least one valid run passing
        pass_at_k = (
            1
            if any(
                all(run.get("stages", {}).get(s, {}).get("passed", False) for s in ("lint", "static"))
                for run in valid_runs
            )
            else 0
        )

        # Average composite
        composites = [run.get("score", {}).get("composite", 0) for run in valid_runs]
        avg_composite = sum(composites) / len(composites) if composites else 0

        # Idiom coverage: which runs carried a judge verdict, and under which
        # judge model / prompt version (pinned for reproducibility).
        judged = [r for r in valid_runs if judge_metadata(r)]
        idioms = [r.get("score", {}).get("idiom", 0.0) for r in judged]

        rejected_reasons: dict[str, int] = {}
        for r in invalid_runs:
            reason = run_validity(r)["reason"] or "unknown"
            rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1

        entry = {
            "pass_at_1": pass_at_1,
            "pass_at_k": pass_at_k,
            "consistency": consistency,
            "avg_composite": avg_composite,
            "num_runs": len(valid_runs),
            "rejected_runs": len(invalid_runs),
        }
        if rejected_reasons:
            entry["rejected_reasons"] = rejected_reasons
        if judged:
            entry["judged_runs"] = len(judged)
            entry["avg_idiom"] = sum(idioms) / len(idioms)
            entry["judge_models"] = sorted(
                {m["judge_model"] for r in judged if (m := judge_metadata(r)) and m["judge_model"]}
            )
            entry["judge_prompts"] = sorted(
                {m["prompt_sha256"] for r in judged if (m := judge_metadata(r)) and m["prompt_sha256"]}
            )
        aggregates[f"{model}/{stack}/{task}"] = entry

    return aggregates


def load_result_set(model_dir: Path) -> list[dict[str, Any]]:
    """Load and score every run JSON under one result-set directory."""
    if not model_dir.is_dir():
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


def load_results(results_dir: Path, model: str) -> list[dict[str, Any]]:
    """Load all result JSON files for a model."""
    return load_result_set(results_dir / model.replace("/", "-"))


def save_aggregate(results: list[dict[str, Any]], out_path: Path) -> None:
    """Save aggregated scores to JSON."""
    aggregates = aggregate_scores(results)
    with open(out_path, "w") as f:
        json.dump(aggregates, f, indent=2)
