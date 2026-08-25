"""
Regression tests: honest stage gating (spec.yaml stages.*.enabled, plus
score.py's correctness axis only averaging over stages that actually ran)
must not change the scores computed for result JSONs written *before* stage
gating existed.

Historical run JSONs never carry a `skipped` key on any stage — every task
(gated or not, per its spec) unconditionally ran lint/static/semantic before
this fix landed, and the value written under `stages.<name>.passed` reflects
what that unconditional run produced (including tasks like T1-comprehend,
whose spec disables all four stages, where lint/static trivially "passed"
because there was no code to lint). score.py's compute_score must reproduce
the exact same composite for those files: a stage dict with no `skipped` key
is still counted as "attempted", so nothing changes for stages that were
actually recorded.

Samples below were chosen to cover a spread of composite values (1.0 down to
~0.33), not just the trivial all-disabled comprehend case, so the assertion
exercises stages with real passes and real failures, not only skips.
"""

from __future__ import annotations

import json
from pathlib import Path

from bench.score import compute_score

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"


# (path relative to results/, expected composite as computed by the current
# compute_score). Expected values were captured from the pre-gating
# compute_score implementation and cross-checked against all 1140 result
# JSONs under results/ before this fix landed (zero diffs).
SAMPLED_HISTORICAL_JSONS = [
    ("claude-opus-4-8-low/crossplane/warm/T1-comprehend_run0.json", 0.7777777777777778),
    ("claude-opus-4-8-low/crossplane/warm/T2-generate_run0.json", 0.4444444444444444),
    ("claude-opus-4-8-low/crossplane/warm/T2-generate_run2.json", 0.3333333333333333),
    ("claude-opus-4-8-low/crossplane/warm/T3-modify_run1.json", 0.6666666666666666),
    ("claude-opus-4-8-low/knr-ops/warm/T1-comprehend_run1.json", 0.5555555555555556),
    ("claude-opus-4-8-low/knr-ops/warm/T2-generate_run0.json", 0.3703703703703704),
]


def test_historical_composites_unchanged_by_stage_gating():
    for rel_path, expected_composite in SAMPLED_HISTORICAL_JSONS:
        json_path = RESULTS_DIR / rel_path
        assert json_path.exists(), f"fixture missing: {json_path}"
        result = json.loads(json_path.read_text())

        # Sanity: these are genuinely pre-gating fixtures (no `skipped` key
        # anywhere in `stages`), so the test is exercising the "stage dict
        # present, no skipped flag" backward-compat path, not a no-op.
        for stage_result in result.get("stages", {}).values():
            assert "skipped" not in stage_result, (
                f"{rel_path} unexpectedly carries a `skipped` stage flag; "
                "pick a different historical fixture for this regression test"
            )

        composite = compute_score(result)["composite"]
        assert composite == expected_composite, (
            f"{rel_path}: composite changed from {expected_composite} to "
            f"{composite} — honest stage gating must not alter historical "
            "scoring semantics"
        )


def test_all_historical_result_jsons_unaffected():
    """Broader sweep: every JSON under results/ with a `stages` key must
    score identically to the pre-gating formula (correctness = passed-stage
    count over a fixed denominator of 3, +1 if `e2e` is present at all),
    since none of them carry a `skipped` flag."""

    def old_correctness(stages: dict) -> float:
        stage_pass = sum(
            1 for name in ("lint", "static", "semantic")
            if stages.get(name, {}).get("passed", False)
        )
        total_stages = 3
        if stages.get("e2e"):
            total_stages = 4
            stage_pass += 1 if stages["e2e"].get("passed", False) else 0
        return stage_pass / total_stages if total_stages else 0

    checked = 0
    for json_path in RESULTS_DIR.rglob("*.json"):
        try:
            result = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(result, dict) or "stages" not in result:
            continue
        checked += 1
        expected = old_correctness(result["stages"])
        actual = compute_score(result)["correctness"]
        assert actual == expected, f"{json_path}: correctness {actual} != {expected}"

    assert checked > 1000, f"expected >1000 historical result JSONs, found {checked}"
