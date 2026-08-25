"""
Score computation and aggregation for benchmark results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bench import validity
from bench.validity import HARNESS_INVALID, MODEL_FAILURE, run_validity

# Score axes and their weights
AXES = {
    "correctness": 3,
    "completeness": 2,
    "idiom": 1,
    "safety": 2,
    "consistency": 1,
}

# Log bodies a stage runner wrote when it had nothing to act on, back when
# "nothing to act on" was recorded as `passed: True`. Historical result JSONs
# carry no `inapplicable` key, so these markers are how a stored run is
# re-classified honestly — without them the fix would only apply to runs made
# after it landed, and every published composite would keep quoting the
# inflated number. bench.stages.lint.inapplicable is what new runs write.
#
# Matched on the whole stripped log body, never as a substring: a real lint
# run that happens to mention "no YAML files in workspace" in a tool's stderr
# must not be demoted.
VACUOUS_LOG_MARKERS = frozenset({
    "no YAML files in workspace",
    "no TypeScript files in workspace",
    "no lint commands for stack",
    "no semantic tests",
    "static validation passed",
    "lint passed",
})


def stage_inapplicable(stage: dict[str, Any] | None) -> bool:
    """Whether a stage had nothing to act on, and so measured nothing.

    An inapplicable stage is neither a pass nor a fail: it is excluded from
    the correctness ratio entirely. This is the vacuous-pass guard — a run
    that produced no extractable output used to score lint and static as
    passes ("nothing to lint", "nothing to build") while only the semantic
    grader failed, so the most broken runs collected 2 of 3 on the axis that
    weighs most.
    """
    if not isinstance(stage, dict):
        return False
    if stage.get("inapplicable"):
        return True
    # Backward compatibility with result JSONs written before the guard.
    if stage.get("passed") and (stage.get("logs") or "").strip() in VACUOUS_LOG_MARKERS:
        return True
    return False


def stage_attempted(stage: dict[str, Any] | None) -> bool:
    """A stage counts toward correctness only if it ran and checked something."""
    if not isinstance(stage, dict) or not stage:
        return False
    if stage.get("skipped"):
        return False
    return not stage_inapplicable(stage)


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
    # actually ran AND had something to act on. Two exclusions, both from
    # numerator and denominator: a stage the spec disabled (recorded by
    # run_task as {"skipped": True, ...}) and a stage that found nothing to
    # check (`inapplicable`). Neither may count as a pass.
    #
    # The second exclusion applies retroactively to stored results via
    # VACUOUS_LOG_MARKERS, so historical composites DO move — 762 of the 1140
    # under results/, all downward. That delta is measured and pinned in
    # tests/test_score_regression.py rather than avoided.
    stage_pass = 0
    total_stages = 0
    for name in ("lint", "static", "semantic"):
        stage_result = stages.get(name, {})
        if not stage_attempted(stage_result):
            continue
        total_stages += 1
        if stage_result.get("passed", False):
            stage_pass += 1
    e2e_result = stages.get("e2e")
    if e2e_result and stage_attempted(e2e_result):
        total_stages += 1
        if e2e_result.get("passed", False):
            stage_pass += 1
    scores["correctness"] = stage_pass / total_stages if total_stages else 0
    scores["attempted_stages"] = total_stages

    # Completeness: semantic assertion coverage. `total_count == 0` means no
    # assertion was evaluated — the task ships no grader, or pytest never
    # collected. That used to score 1.0, a full mark on the second-heaviest
    # axis for a run nothing checked; it is now excluded from the composite
    # the same way an inapplicable stage is excluded from correctness.
    semantic = stages.get("semantic", {})
    passed_count = semantic.get("passed_count", 0)
    total_count = semantic.get("total_count", 0)
    completeness_applicable = bool(total_count)
    scores["completeness"] = passed_count / total_count if total_count else 0.0

    # Safety: binary flag read out of the semantic grader's own output.
    #
    # This axis keeps its 1.0 default when nothing ran, unlike completeness
    # above, and that is a deliberate stopping point rather than an oversight.
    # Dropping it too makes an unjudged rubric-only task score exactly 0.0 on
    # every axis, which reads as "the model did terribly" rather than "nothing
    # was measured" — the same misleading-number failure this work exists to
    # stop, pointing the other way. The runs where the free mark would matter
    # most (every enabled stage inapplicable) are rejected outright by
    # bench.validate and contribute no number at all, so what survives here is
    # a known-weak axis on runs that did measure something. See the "Not yet
    # guarded" section of docs/result-integrity.md.
    scores["safety"] = 1.0 if semantic.get("safety_pass", True) else 0.0

    # Consistency: placeholder, computed across runs in aggregate
    scores["consistency"] = 0.0  # computed at aggregate level

    # Idiom: rubric LLM judge verdict, written by the runner under --judge.
    # Tasks without a rubric, and runs scored before the judge existed, keep
    # the historical 0.0 so composites stay comparable across result sets.
    scores["idiom"] = idiom_score(result)

    # Weighted composite over the axes that were measurable. An axis nothing
    # could be measured on is dropped from numerator and denominator alike,
    # rather than contributing a default — the same rule the correctness axis
    # applies to inapplicable stages, one level up.
    applicable = dict(AXES)
    if not completeness_applicable:
        applicable.pop("completeness")
    scores["applicable_axes"] = sorted(applicable)
    denom = sum(applicable.values())
    scores["composite"] = (
        sum(scores[axis] * applicable[axis] for axis in applicable) / denom
        if denom else 0.0
    )

    return scores


# ──────────────────────────────────────────────────────────────────────────
# The failure taxonomy applied to scoring (#69)
# ──────────────────────────────────────────────────────────────────────────

def run_category(
    result: dict[str, Any], classification: dict[str, Any] | None = None
) -> str | None:
    """HARNESS_INVALID, MODEL_FAILURE, or None for a run that measured something.

    `compute_score` is deliberately left a pure function of a run's `stages`;
    this is where a run's completion is allowed to affect its number.

    `bench.validate.classify_run` is the single source of truth downstream — it
    reconciles both of bench.validity's classifiers and loads the task spec —
    so callers that have already run it pass its result in as `classification`
    and it is used verbatim.

    Without one, both of bench.validity's classifiers are run and merged here.
    Consulting only the first was a real bug: a 120-character stub clears
    `check_validity`'s ABSOLUTE_FLOOR of 50 but trips `check_content`'s
    MIN_CONTENT_CHARS of 200, so `qwen 3.8 - local`'s stubs looked valid to one
    classifier and were never zeroed. Two exclusions cannot be seen from here
    at all — `no_extractable_output` and `all_stages_inapplicable` both need
    the task spec — which is why `classification` is preferred when available;
    this path under-detects model failures rather than over-detecting them.
    """
    if classification is not None:
        verdict = classification.get("verdict")
        if verdict == "invalid":
            return HARNESS_INVALID
        if verdict == "model-failure":
            return MODEL_FAILURE
        return None

    # Grandfathered: a run with no `content` key at all predates content being
    # recorded, or is a synthetic fixture. It cannot be judged by either
    # classifier, so it is neither kind of failure — the same rule
    # `run_validity` applies, restated here because `check_result` would read
    # the missing content as an empty completion.
    if "content" not in result and not isinstance(result.get("validity"), dict):
        return None

    simple = run_validity(result)
    rich = validity.check_result(result)
    category = validity.merge_categories(
        None if simple.get("valid") else (simple.get("category") or HARNESS_INVALID),
        rich.get("category"),
    )
    return category


def apply_validity(
    result: dict[str, Any],
    scores: dict[str, Any],
    classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Zero the score of a run whose model produced nothing usable (#69).

    A model-failure run scores 0 on every axis and stays in the denominator.
    Zeroing the whole composite rather than only `correctness` is deliberate:
    the `safety` axis defaults to 1.0 when nothing ran, so an empty completion
    would otherwise collect 2 of 9 weight for having done nothing — a smaller
    version of the same free credit this taxonomy exists to remove.

    The stage-derived numbers are not thrown away; they move to
    `composite_measured` / `correctness_measured` so the zeroing is auditable
    rather than a value that silently appeared.

    A harness-invalid run is untouched here. Its score is meaningless either
    way, and it is excluded from every aggregate downstream — writing a 0 onto
    it would invite someone to average it in.
    """
    if run_category(result, classification) != MODEL_FAILURE:
        return scores
    zeroed = dict(scores)
    zeroed["model_failure"] = True
    zeroed["composite_measured"] = scores.get("composite", 0.0)
    zeroed["correctness_measured"] = scores.get("correctness", 0.0)
    for axis in AXES:
        zeroed[axis] = 0.0
    zeroed["composite"] = 0.0
    return zeroed


def score_run(result: dict[str, Any]) -> dict[str, Any]:
    """`compute_score` plus the validity taxonomy. The scoring entry point."""
    return apply_validity(result, compute_score(result))


def partition_by_category(
    results: list[dict[str, Any]],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split runs into (measured, model_failures, harness_invalid).

    `measured + model_failures` is the denominator every average uses;
    `harness_invalid` contributes nothing anywhere but is always counted.
    """
    measured: list[dict] = []
    model_failures: list[dict] = []
    harness_invalid: list[dict] = []
    for r in results:
        category = run_category(r)
        if category == HARNESS_INVALID:
            harness_invalid.append(r)
        elif category == MODEL_FAILURE:
            model_failures.append(r)
        else:
            measured.append(r)
    return measured, model_failures, harness_invalid


def aggregate_scores(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate scores across runs, stacks, tasks.

    #69 splits what #59 lumped together. A run that produced no number has two
    possible causes and they are averaged differently:

    - HARNESS-INVALID (tool markup or a host path leaked into the completion,
      the adapter errored, a stage's binary was missing): the harness captured
      no completion, so there is no measurement of the model. Excluded from
      every metric here, and counted in `harness_rejected_runs` /
      `harness_rejected_reasons` so a report can surface it rather than let a
      composite quietly stand on a shrunken sample.
    - MODEL-FAILURE (empty completion, stub, prose where a file was needed):
      the harness worked and the model produced nothing usable. This is a
      measurement — the worst one — so it scores 0 and STAYS in every
      denominator, counted in `model_failure_runs` / `model_failure_reasons`.

    Scoring model failures as exclusions is what let a model raise its own
    average by answering nothing: its worst runs left its own denominator.
    `num_runs` is therefore the count of runs that were actually measured,
    model failures included, and it is the denominator of `avg_composite` and
    `pass_at_1`.

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

        valid_runs, failure_runs, invalid_runs = partition_by_category(runs)
        # Every run that measured something, a failed answer included.
        scored_runs = valid_runs + failure_runs

        # A model failure's own score is zeroed here as well as at load time,
        # so an aggregate is correct even when the caller scored the runs with
        # bare `compute_score`. This is the invariant that must not be
        # bypassable: emitting nothing can never raise an average.
        for run in failure_runs:
            run["score"] = apply_validity(run, run.get("score") or compute_score(run))

        # Consistency: fraction of measured runs producing the same outcome.
        # A harness-rejected run's stage results are gate noise (a run that
        # narrated tool use instead of answering emits no code, so lint/
        # static/semantic trivially fail on nothing) — folding it in would
        # confound consistency with contamination, exactly what #59 flagged.
        # A model failure, by contrast, has a real and perfectly consistent
        # outcome: it failed. Its outcome is recorded as an explicit failure
        # tuple rather than read off stage flags, which for an empty answer
        # can still carry a vacuous lint pass.
        outcomes = set()
        for run in valid_runs:
            stages = run.get("stages", {})
            outcome = tuple(
                stages.get(s, {}).get("passed", False) for s in ("lint", "static", "semantic")
            )
            outcomes.add(outcome)
        if failure_runs:
            outcomes.add((False, False, False))
        consistency = (
            (1.0 if len(outcomes) <= 1 else 1.0 - (len(outcomes) - 1) / len(scored_runs))
            if scored_runs else 0.0
        )

        # Update consistency scores in each measured run
        for run in scored_runs:
            score = run.setdefault("score", {})
            score["consistency"] = consistency

        def _passed(run: dict[str, Any]) -> bool:
            # A model failure never passes, whatever its vacuous stage flags say.
            if run in failure_runs:
                return False
            return all(
                run.get("stages", {}).get(s, {}).get("passed", False)
                for s in ("lint", "static")
            )

        # Pass@1: fraction of measured runs passing all stages
        pass_at_1 = (
            sum(1 for run in scored_runs if _passed(run)) / len(scored_runs)
            if scored_runs else 0.0
        )

        # Pass@k: at least one measured run passing
        pass_at_k = 1 if any(_passed(run) for run in scored_runs) else 0

        # Average composite over every measured run — model failures at 0.0.
        composites = [run.get("score", {}).get("composite", 0) for run in scored_runs]
        avg_composite = sum(composites) / len(composites) if composites else 0

        # Idiom coverage: which runs carried a judge verdict, and under which
        # judge model / prompt version (pinned for reproducibility).
        judged = [r for r in valid_runs if judge_metadata(r)]
        idioms = [r.get("score", {}).get("idiom", 0.0) for r in judged]

        rejected_reasons: dict[str, int] = {}
        for r in invalid_runs:
            reason = run_validity(r).get("reason") or "unknown"
            rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
        failure_reasons: dict[str, int] = {}
        for r in failure_runs:
            reason = run_validity(r).get("reason") or "unknown"
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

        entry = {
            "pass_at_1": pass_at_1,
            "pass_at_k": pass_at_k,
            "consistency": consistency,
            "avg_composite": avg_composite,
            # Denominator of every average above: measured runs, model
            # failures included.
            "num_runs": len(scored_runs),
            "num_measured_runs": len(valid_runs),
            # The two failure counts, never summed into one.
            "model_failure_runs": len(failure_runs),
            "harness_rejected_runs": len(invalid_runs),
            # Back-compat: `rejected_runs` has always meant "excluded from the
            # numbers above", and after the split only harness-invalid runs are.
            "rejected_runs": len(invalid_runs),
        }
        if rejected_reasons:
            entry["rejected_reasons"] = rejected_reasons
            entry["harness_rejected_reasons"] = rejected_reasons
        if failure_reasons:
            entry["model_failure_reasons"] = failure_reasons
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
    """Load and score every run JSON under one result-set directory.

    Scoring goes through `score_run`, not bare `compute_score`, so a run whose
    model produced nothing usable arrives at every downstream consumer already
    carrying a 0.0 composite (#69).
    """
    if not model_dir.is_dir():
        return []

    results = []
    for f in sorted(model_dir.rglob("*.json")):
        if "run" in f.stem:
            with open(f) as fp:
                result = json.load(fp)
                result["score"] = score_run(result)
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
