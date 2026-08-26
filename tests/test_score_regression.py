"""
Regression tests pinning what the historical result JSONs score.

This file has two jobs, and they pull in opposite directions on purpose.

1. Honest stage gating (spec.yaml `stages.*.enabled`, landed in #56) must NOT
   change any *pre-gating* historical composite. A pre-gating run carries no
   `skipped` key, so every stage recorded there is still counted as
   attempted. Result sets produced by a harness that already honors stage
   gating (e.g. the claude-*-3arm and claude-*-probe sets added for #40/#59)
   legitimately carry `skipped` stages for tasks whose spec disables them —
   those are a different experiment for this check's purposes, not evidence
   of drift, so they are filtered out of `_historical_results()` rather than
   asserted against the pre-gating formula.

2. The vacuous-pass guard DOES change the surviving pre-gating composites,
   and that change is the point. Before it, a stage with nothing to act on
   recorded `passed: True`: "no YAML files in workspace", "no TypeScript
   files in workspace", "static validation passed" (emitted when no
   kustomization/claim/manifest was found), "no semantic tests". A run that
   produced no extractable output therefore collected free passes on lint
   and static, and `completeness` defaulted to 1.0 whenever no assertion was
   evaluated — full marks on the second-heaviest axis for a run nothing had
   checked. The runs that flattered hardest were exactly the most broken
   ones.

   Measured over the pre-gating result JSONs under results/ (1218 of the
   1296 total on disk; 78 carry `skipped` and are out of scope per #1 above):

     - 773 runs carried at least one vacuously-passed stage
     - 127 runs had *every* enabled stage inapplicable — no measurement at
       all; bench.validate rejects these outright
     - 791 composites change, every one of them downward

   Zero composites move up. That is the check worth keeping: removing credit
   that was never earned can only lower a score, so an increase anywhere would
   mean the guard had broken something rather than fixed it.

The pinned values below are the corrected ones. They were captured from
compute_score after the guard landed and are asserted exactly, so a later
change to scoring semantics has to be a deliberate re-pin rather than a silent
drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.score import compute_score, stage_inapplicable

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"


# (path relative to results/, composite before the vacuous-pass guard,
#  composite after). The spread was chosen to cover trivially-passing
# comprehend tasks through runs with real failures, so the assertion
# exercises inapplicable stages, real passes and real failures alike.
SAMPLED_HISTORICAL_JSONS = [
    ("claude-opus-4-8-low/crossplane/warm/T1-comprehend_run0.json",
     0.7777777777777778, 0.2857142857142857),
    ("claude-opus-4-8-low/crossplane/warm/T2-generate_run0.json",
     0.4444444444444444, 0.3888888888888889),
    ("claude-opus-4-8-low/crossplane/warm/T2-generate_run2.json",
     0.3333333333333333, 0.2222222222222222),
    ("claude-opus-4-8-low/crossplane/warm/T3-modify_run1.json",
     0.6666666666666666, 0.2857142857142857),
    ("claude-opus-4-8-low/knr-ops/warm/T1-comprehend_run1.json",
     0.5555555555555556, 0.2857142857142857),
    ("claude-opus-4-8-low/knr-ops/warm/T2-generate_run0.json",
     0.3703703703703704, 0.3703703703703704),
]

# Counts measured over the pre-gating subset of results/ (see module
# docstring #1) after merging in the #59 result sets that already carry
# `skipped` flags. Pinned so a later change to VACUOUS_LOG_MARKERS, or a
# stage runner quietly changing a log body, shows up as a test failure
# rather than as a moved leaderboard.
EXPECTED_TOTAL_RUNS = 1362
EXPECTED_VACUOUS_RUNS = 789
EXPECTED_FULLY_VACUOUS_RUNS = 127
EXPECTED_CHANGED_COMPOSITES = 791


def _old_composite(stages: dict) -> float:
    """The pre-guard formula, kept here as the thing being compared against.

    correctness = passed-stage count over a fixed denominator of 3 (+1 when
    `e2e` is present at all); completeness defaults to 1.0 when no assertion
    ran; idiom and consistency are 0.0 for every historical run.
    """
    stage_pass = sum(
        1 for name in ("lint", "static", "semantic")
        if stages.get(name, {}).get("passed", False)
    )
    total = 3
    if stages.get("e2e"):
        total = 4
        stage_pass += 1 if stages["e2e"].get("passed", False) else 0
    correctness = stage_pass / total if total else 0

    semantic = stages.get("semantic", {})
    passed_count = semantic.get("passed_count", 0)
    total_count = semantic.get("total_count", 0)
    completeness = passed_count / total_count if total_count else 1.0
    safety = 1.0 if semantic.get("safety_pass", True) else 0.0

    return (correctness * 3 + completeness * 2 + 0.0 * 1 + safety * 2 + 0.0 * 1) / 9


def _historical_results():
    """Pre-gating result JSONs only — see module docstring #1.

    A result whose `stages` carry a `skipped` key came from a harness that
    already honors spec-driven stage gating (#56) and is out of scope for
    this file's "gating alone changes nothing" claim; it is not evidence of
    drift, it is a different experiment.
    """
    for json_path in sorted(RESULTS_DIR.rglob("*.json")):
        try:
            result = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        # A run record maps stage name -> stage result. Other JSONs live in
        # results/ too and some carry a `stages` key of their own —
        # regrade_offline's `_regrade_summary.json` lists the stage *names* it
        # recomputed — so presence of the key is not enough to identify a run.
        if not isinstance(result, dict) or not isinstance(result.get("stages"), dict):
            continue
        if any(
            isinstance(sr, dict) and "skipped" in sr
            for sr in result["stages"].values()
        ):
            continue
        yield json_path, result


def test_sampled_historical_composites_match_pinned_corrections():
    for rel_path, old_composite, new_composite in SAMPLED_HISTORICAL_JSONS:
        json_path = RESULTS_DIR / rel_path
        assert json_path.exists(), f"fixture missing: {json_path}"
        result = json.loads(json_path.read_text())

        # Sanity: genuinely pre-gating fixtures, so this exercises the
        # "stage dict present, no skipped flag" backward-compat path.
        for stage_result in result.get("stages", {}).values():
            assert "skipped" not in stage_result, (
                f"{rel_path} unexpectedly carries a `skipped` stage flag; "
                "pick a different historical fixture for this regression test"
            )

        # approx on the old side only: it is recomputed here with a
        # different association order than the original implementation used,
        # and the corrected value below is what is pinned exactly.
        assert _old_composite(result["stages"]) == pytest.approx(old_composite), (
            f"{rel_path}: the recorded pre-guard composite no longer "
            "reproduces — the fixture itself changed"
        )
        assert compute_score(result)["composite"] == new_composite, (
            f"{rel_path}: composite drifted from the pinned corrected value"
        )


def test_stage_gating_alone_changes_nothing():
    """No historical run carries a `skipped` flag, so spec-driven stage gating
    is inert over results/ — every change measured below comes from the
    vacuous-pass guard, not from #56."""
    for json_path, result in _historical_results():
        for stage_result in result["stages"].values():
            assert "skipped" not in stage_result, (
                f"{json_path} carries a `skipped` flag; the delta attribution "
                "in this file's docstring no longer holds"
            )


def test_vacuous_pass_correction_is_the_measured_size_and_only_lowers_scores():
    total = vacuous = fully_vacuous = changed = increased = 0

    for _json_path, result in _historical_results():
        total += 1
        stages = result["stages"]
        inapplicable = [
            s for s in stages.values()
            if isinstance(s, dict) and stage_inapplicable(s)
        ]
        if inapplicable:
            vacuous += 1
        enabled = [
            s for s in stages.values()
            if isinstance(s, dict) and not s.get("skipped")
        ]
        if enabled and all(stage_inapplicable(s) for s in enabled):
            fully_vacuous += 1

        old = _old_composite(stages)
        new = compute_score(result)["composite"]
        if abs(new - old) > 1e-12:
            changed += 1
            if new > old:
                increased += 1

    assert total == EXPECTED_TOTAL_RUNS, (
        f"expected {EXPECTED_TOTAL_RUNS} historical result JSONs, found {total} — "
        "re-pin the counts below if runs were added or removed"
    )
    assert vacuous == EXPECTED_VACUOUS_RUNS
    assert fully_vacuous == EXPECTED_FULLY_VACUOUS_RUNS
    assert changed == EXPECTED_CHANGED_COMPOSITES
    assert increased == 0, (
        f"{increased} historical composite(s) went UP under the vacuous-pass "
        "guard. Withdrawing credit that was never earned can only lower a "
        "score, so an increase means the guard is crediting something new."
    )
