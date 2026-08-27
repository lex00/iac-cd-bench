"""#110: an abstention the harness caused must not silently raise a score.

`correctness = stages passed / stages attempted`, and an `inapplicable` stage
leaves the denominator. So a gate that cannot run *raises* the arm's score, and
nothing in the stored result said so. That is not hypothetical — it is the
whole of crossplane outranking knr-ops in every published table, reproduced
below from real coverage-v3 shapes.

The fix is deliberately NOT "fail the abstained stage". #99 removed that and
was right to: punishing an arm for an axis the harness failed to measure is
worse than dropping it. The honest position is that such a run is not
comparable, so the count travels with the score.
"""

from __future__ import annotations

from bench.score import compute_score, stage_gate_defect


def _run(stages: dict) -> dict:
    return {"stages": stages, "task": "T3-modify", "stack": "x"}


PASS = {"passed": True, "logs": "ok"}
FAIL = {"passed": False, "logs": "boom"}


def _abstain(reason: str | None) -> dict:
    s: dict = {"inapplicable": True, "reason": "nothing to do", "logs": "nothing to do"}
    if reason is not None:
        s["inapplicable_reason"] = reason
    return s


# --- the inversion this issue is about ------------------------------------


def test_a_broken_gate_still_outscores_a_working_one_on_correctness_alone():
    """Reproduces the coverage-v3 cell, and pins WHY it happens.

    crossplane attempted one stage and passed it. knr-ops attempted three and
    failed two. The arithmetic is correct; the comparison is not.
    """
    broken = compute_score(_run({
        "lint": PASS,
        "static": _abstain("gate_defect"),
        "semantic": _abstain("gate_defect"),
    }))
    working = compute_score(_run({"lint": PASS, "static": FAIL, "semantic": FAIL}))

    assert broken["correctness"] == 1.0
    assert working["correctness"] < 0.5
    assert broken["attempted_stages"] == 1
    assert working["attempted_stages"] == 3


def test_the_broken_run_is_marked_so_the_comparison_can_be_refused():
    """The part that was missing. The score above is unchanged -- what changes
    is that a reader can now tell it apart from a real measurement."""
    broken = compute_score(_run({
        "lint": PASS,
        "static": _abstain("gate_defect"),
        "semantic": _abstain("gate_defect"),
    }))
    working = compute_score(_run({"lint": PASS, "static": FAIL, "semantic": FAIL}))

    assert broken["gate_defects"] == 2
    assert working["gate_defects"] == 0


# --- the three reasons are not interchangeable ----------------------------


def test_by_spec_abstention_is_not_a_gate_defect():
    """T1-comprehend declares no build stage. Dropping it is correct, and it
    must not be confused with a gate that could not run."""
    s = compute_score(_run({"lint": PASS, "static": _abstain("by_spec")}))
    assert s["gate_defects"] == 0
    assert s["attempted_stages"] == 1


def test_no_artifact_is_not_a_gate_defect():
    """A model that produced nothing is a result about the MODEL, not about
    the harness. It still leaves the denominator, but it is not a defect."""
    s = compute_score(_run({"lint": PASS, "static": _abstain("no_artifact")}))
    assert s["gate_defects"] == 0


def test_unclassified_abstentions_are_not_retroactively_blamed():
    """Every result written before the contract carries `inapplicable` with no
    reason. Treating those as gate defects would rewrite the history of runs
    whose reason nobody recorded — the counts must widen the record, not
    reinterpret it."""
    s = compute_score(_run({"lint": PASS, "static": _abstain(None)}))
    assert s["gate_defects"] == 0
    assert s["attempted_stages"] == 1


# --- the helper itself -----------------------------------------------------


def test_stage_gate_defect_reads_the_reason_code():
    assert stage_gate_defect({"inapplicable": True, "inapplicable_reason": "gate_defect"})
    assert not stage_gate_defect({"inapplicable": True, "inapplicable_reason": "by_spec"})
    assert not stage_gate_defect({"inapplicable": True})
    assert not stage_gate_defect(PASS)
    assert not stage_gate_defect(None)


def test_a_gate_defect_does_not_change_the_composite():
    """Explicitly pinned, because the tempting fix is to fail the stage and
    that would re-create #99: an arm punished for an axis the harness never
    measured. The composite is identical with and without the marker; only the
    disclosure differs."""
    stages_marked = {"lint": PASS, "static": _abstain("gate_defect")}
    stages_plain = {"lint": PASS, "static": _abstain(None)}
    assert (compute_score(_run(stages_marked))["composite"]
            == compute_score(_run(stages_plain))["composite"])


def test_e2e_gate_defects_are_counted_too():
    s = compute_score(_run({
        "lint": PASS, "static": PASS, "semantic": PASS,
        "e2e": _abstain("gate_defect"),
    }))
    assert s["gate_defects"] == 1
