"""
Regression tests for the harness-invalid / model-failure split (#69).

The bug: `bench/validity.py` rejected two unrelated things under one verdict
and `bench/score.py` excluded both from the denominator. Excluding a model's
own empty answers drops its worst runs from its own average — the same
perverse incentive as the vacuous passes #56/#59 removed, arriving through the
other door. The rescore proved it empirically: `qwen 3.8 - local` held rank #1
of 13 under blanket exclusion because 44 of its 90 mostly-empty runs were
dropped rather than counted; zero-filled it is #12.

The invariant these tests exist to pin is at the bottom:
`test_a_model_cannot_improve_its_average_by_emitting_nothing`. Everything
above it is the machinery that has to hold for that invariant to hold.

No network, no subprocess, no result JSONs: every fixture is constructed here
so the arithmetic is checkable by hand.
"""

from __future__ import annotations

import pytest

from bench import validate, validity
from bench.report import generate_report, model_failures, partition_by_validity
from bench.score import (
    aggregate_scores,
    apply_validity,
    compute_score,
    partition_by_category,
    run_category,
    score_run,
)
from bench.validity import HARNESS_INVALID, MODEL_FAILURE

# ══════════════════════════════════════════════════════════════════════════
# Fixtures: completions and stage shapes
# ══════════════════════════════════════════════════════════════════════════

# A substantive answer that also produces the artifact the task asked for —
# without the fenced block it would (correctly) trip `no_extractable_output`
# and be a model failure itself.
REAL_ANSWER = (
    "## Analysis\n\n"
    + ("A substantive paragraph of real analysis. " * 60)
    + '\n```hcl\nresource "aws_s3_bucket" "a" {\n  bucket = "b"\n}\n```\n'
)

# Claude Code's own tool-call machinery in what should have been a completion:
# the harness captured a transcript, not an answer.
HARNESS_LEAK = REAL_ANSWER + (
    '\n<invoke name="Bash">\n<parameter name="command">ls -la</parameter>\n</invoke>\n'
)

# Stage shapes, chosen so every composite below is checkable by hand.
# Axis weights: correctness 3, completeness 2, idiom 1, safety 2, consistency 1.
MEDIOCRE_STAGES = {  # 1 of 3 stages pass, 1 of 2 assertions, safe -> 4/9
    "lint": {"passed": True, "logs": "ok"},
    "static": {"passed": False, "logs": "plan failed"},
    "semantic": {"passed": False, "passed_count": 1, "total_count": 2, "safety_pass": True},
}
WEAK_STAGES = {  # 0 of 3 stages pass, 0 of 2 assertions, safe -> 2/9
    "lint": {"passed": False, "logs": "8 errors"},
    "static": {"passed": False, "logs": "plan failed"},
    "semantic": {"passed": False, "passed_count": 0, "total_count": 2, "safety_pass": True},
}
# What an empty completion actually records: nothing to lint, nothing to
# build, so both stages "pass" vacuously. This is why an empty answer must be
# zeroed by category rather than trusted to score badly on its own.
VACUOUS_STAGES = {
    "lint": {"passed": True, "logs": "no YAML files in workspace"},
    "static": {"passed": True, "logs": "static validation passed"},
    "semantic": {"passed": False, "passed_count": 0, "total_count": 2, "safety_pass": True},
}

MEDIOCRE = pytest.approx(4 / 9)
WEAK = pytest.approx(2 / 9)


def _run(content, stages=None, run=0, **extra):
    r = {
        "model": "m", "stack": "terraform", "task": "T2-generate", "run": run,
        "condition": "warm", "content": content,
        "stages": dict(stages if stages is not None else MEDIOCRE_STAGES),
        **extra,
    }
    r["score"] = compute_score(r)
    return r


# ══════════════════════════════════════════════════════════════════════════
# The taxonomy itself
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("reason", [
    "tool_invocation_markup",
    "claude_code_ui_marker",
    "leaked_host_worktree_path",
    "agent_transcript",
    "runner_error",
    "adapter_error",
    "timeout",
    "unreadable_json",
    "tool_missing_scored_as_pass",
])
def test_harness_reasons_categorise_as_harness_invalid(reason):
    assert validity.categorize_reason(reason) == HARNESS_INVALID


@pytest.mark.parametrize("reason", [
    "empty_or_near_empty",
    "short_stub",
    "empty_completion",
    "content_too_short",
    "no_extractable_output",
    "all_stages_inapplicable",
])
def test_model_reasons_categorise_as_model_failure(reason):
    assert validity.categorize_reason(reason) == MODEL_FAILURE


def test_reason_detail_after_a_colon_does_not_change_the_category():
    """Reasons are recorded as `key: prose`. The key is what categorises."""
    assert validity.categorize_reason(
        "empty_completion: the provider returned no text at all"
    ) == MODEL_FAILURE
    assert validity.categorize_reason(
        "runner_error: HTTPSConnectionPool read timed out"
    ) == HARNESS_INVALID


def test_an_unrecognised_reason_is_treated_as_harness_invalid():
    """The conservative direction: exclude, don't accuse.

    Charging a model for a failure mode nobody has classified is the
    false-accusation error; excluding an unknown costs one data point.
    """
    assert validity.categorize_reason("some_future_reason") == HARNESS_INVALID


def test_harness_invalidity_wins_when_a_run_shows_both():
    """If the harness failed, the text is not evidence about the model.

    A completion can be both short and full of leaked tool markup. The markup
    means the harness produced the text, so nothing in it can be charged to
    the model.
    """
    assert validity.merge_categories(MODEL_FAILURE, HARNESS_INVALID) == HARNESS_INVALID
    assert validity.merge_categories(MODEL_FAILURE, MODEL_FAILURE) == MODEL_FAILURE
    assert validity.merge_categories(None, None) is None


def test_sub_reasons_are_unchanged_so_nothing_on_disk_loses_meaning():
    """The category is a new axis over the old reason strings, not a rename."""
    assert validity.check_validity(HARNESS_LEAK)["reason"] == "tool_invocation_markup"
    assert validity.check_validity("")["reason"] == "empty_or_near_empty"
    stub = (
        "I don't see the actual PR diff in your message. Could you provide "
        "the diff content or a link to the PR?"
    )
    assert validity.check_validity(stub)["reason"] == "short_stub"


def test_a_harness_marker_beats_the_length_floor():
    """Ordering fix: markup is tested before emptiness.

    A 40-character completion that is nothing but leaked tool-call markup used
    to be filed `empty_or_near_empty` — a model failure — when it is the
    clearest possible proof the harness, not the model, produced the text.
    """
    tiny_leak = '<invoke name="Bash">ls</invoke>'
    assert len(tiny_leak) < validity.ABSOLUTE_FLOOR
    verdict = validity.check_validity(tiny_leak)
    assert verdict["reason"] == "tool_invocation_markup"
    assert verdict["category"] == HARNESS_INVALID


def test_a_pre_69_validity_block_gets_its_category_derived_not_defaulted():
    """Historical result JSONs carry reasons but no `category`."""
    old = {"content": "x", "validity": {"valid": False, "reason": "empty_or_near_empty",
                                        "content_length": 1}}
    assert validity.run_validity(old)["category"] == MODEL_FAILURE
    old_harness = {"content": "x", "validity": {"valid": False,
                                                "reason": "tool_invocation_markup",
                                                "content_length": 1}}
    assert validity.run_validity(old_harness)["category"] == HARNESS_INVALID


# ══════════════════════════════════════════════════════════════════════════
# The ambiguous case: empty because the model spent its budget on reasoning
# ══════════════════════════════════════════════════════════════════════════

# The real shape: all 31 empty claude-opus-5 completions in the historical
# 90-run set billed exactly max_tokens (16,384) of output and returned no text.
EXHAUSTED = {"content": "", "tokens": {"input": 1101, "output": 16384}}


def test_reasoning_exhaustion_is_detected_from_billed_output_tokens():
    assert validity.is_reasoning_exhausted(EXHAUSTED)


def test_a_genuinely_terse_stub_is_not_reasoning_exhaustion():
    """`qwen 3.8 - local`'s stubs bill 43-200 output tokens, matching their
    visible length. Nothing invisible was produced, so this is an ordinary
    short answer, not a budget burned on thinking."""
    assert not validity.is_reasoning_exhausted({"content": "no.", "tokens": {"output": 43}})


def test_an_errored_run_is_not_reasoning_exhaustion():
    """A run that died in the adapter is harness-invalid with its own reason."""
    assert not validity.is_reasoning_exhausted(
        {"content": "", "error": "read timeout", "tokens": {"output": 16384}}
    )


def test_reasoning_exhaustion_defaults_to_model_failure(monkeypatch):
    """The documented call: a model that thinks past its own output allowance
    has failed the task. The user gets nothing either way, and calling it
    'not a measurement' would let a model raise its average by thinking
    longer — precisely the incentive #69 closes."""
    monkeypatch.delenv(validity.REASONING_EXHAUSTION_ENV, raising=False)
    verdict = validity.check_run_validity(EXHAUSTED)
    assert verdict["reason"] == "empty_reasoning_exhausted"
    assert verdict["category"] == MODEL_FAILURE


def test_reasoning_exhaustion_is_configurable(monkeypatch):
    """The counter-argument — the budget is a harness parameter — is real, so
    the call is reversible without a re-run."""
    monkeypatch.setenv(validity.REASONING_EXHAUSTION_ENV, HARNESS_INVALID)
    assert validity.check_run_validity(EXHAUSTED)["category"] == HARNESS_INVALID
    monkeypatch.setenv(validity.REASONING_EXHAUSTION_ENV, MODEL_FAILURE)
    assert validity.check_run_validity(EXHAUSTED)["category"] == MODEL_FAILURE


def test_a_nonsense_override_falls_back_rather_than_inventing_a_category(monkeypatch):
    monkeypatch.setenv(validity.REASONING_EXHAUSTION_ENV, "whatever")
    assert validity.reasoning_exhaustion_category() == validity.REASONING_EXHAUSTION_DEFAULT


def test_reasoning_exhaustion_keeps_its_own_sub_reason_either_way(monkeypatch):
    """Whichever way it is scored, the data says which case this was, so the
    choice is visible and reversible."""
    monkeypatch.setenv(validity.REASONING_EXHAUSTION_ENV, HARNESS_INVALID)
    verdict = validity.check_result(EXHAUSTED, spec=None)
    assert any(r.startswith("empty_reasoning_exhausted") for r in verdict["reasons"])
    assert "16384 output tokens" in " ".join(verdict["reasons"])


# ══════════════════════════════════════════════════════════════════════════
# Scoring: harness-invalid excluded, model-failure scored 0 in-denominator
# ══════════════════════════════════════════════════════════════════════════

def test_a_harness_marker_run_is_excluded_from_the_denominator():
    runs = [_run(REAL_ANSWER, run=0), _run(HARNESS_LEAK, run=1)]
    agg = aggregate_scores(runs)["m/terraform/T2-generate"]

    assert agg["harness_rejected_runs"] == 1
    assert agg["model_failure_runs"] == 0
    assert agg["num_runs"] == 1, "the harness-rejected run must leave the denominator"
    assert agg["harness_rejected_reasons"] == {"tool_invocation_markup": 1}
    # The surviving run's own number is untouched by its neighbour's exclusion.
    assert agg["avg_composite"] == MEDIOCRE


def test_an_empty_answer_run_scores_zero_and_stays_in_the_denominator():
    runs = [_run(REAL_ANSWER, run=0), _run("", VACUOUS_STAGES, run=1)]
    agg = aggregate_scores(runs)["m/terraform/T2-generate"]

    assert agg["model_failure_runs"] == 1
    assert agg["harness_rejected_runs"] == 0
    assert agg["num_runs"] == 2, "the empty answer must stay in the denominator"
    assert agg["model_failure_reasons"] == {"empty_or_near_empty": 1}
    # (4/9 + 0) / 2, not 4/9.
    assert agg["avg_composite"] == pytest.approx(2 / 9)
    assert runs[1]["score"]["composite"] == 0.0
    assert runs[1]["score"]["model_failure"] is True


def test_an_empty_answer_never_passes_on_its_vacuous_stage_flags():
    """An empty completion records `lint: passed` ("no YAML files in
    workspace") and `static: passed`. Reading pass@1 off those flags would
    count a model that produced nothing as having passed."""
    empty = _run("", VACUOUS_STAGES)
    assert empty["stages"]["lint"]["passed"] is True
    assert empty["stages"]["static"]["passed"] is True

    agg = aggregate_scores([empty])["m/terraform/T2-generate"]
    assert agg["pass_at_1"] == 0.0
    assert agg["pass_at_k"] == 0
    assert agg["num_runs"] == 1


def test_zeroing_preserves_the_measured_number_for_audit():
    """The stage-derived value is moved aside, not discarded — a zero that
    appeared from nowhere is not checkable."""
    empty = _run("", MEDIOCRE_STAGES)
    scored = apply_validity(empty, empty["score"])
    assert scored["composite"] == 0.0
    assert scored["composite_measured"] == MEDIOCRE


def test_a_harness_invalid_run_is_not_zeroed_only_excluded():
    """Writing a 0 onto an excluded run would invite someone to average it in."""
    leaked = _run(HARNESS_LEAK)
    scored = apply_validity(leaked, leaked["score"])
    assert "model_failure" not in scored
    assert scored["composite"] == MEDIOCRE  # untouched, and never used


def test_score_run_applies_the_taxonomy_but_compute_score_stays_pure():
    """`compute_score` remains a pure function of `stages`, which is what
    tests/test_score_regression.py pins over 1,218 historical JSONs. The
    taxonomy is applied one layer up, in `score_run`."""
    empty = {"content": "", "stages": dict(VACUOUS_STAGES)}
    assert compute_score(empty)["composite"] > 0.0
    assert score_run(empty)["composite"] == 0.0


def test_partition_by_category_separates_all_three():
    runs = [_run(REAL_ANSWER, run=0), _run("", run=1), _run(HARNESS_LEAK, run=2)]
    measured, failures, harness = partition_by_category(runs)
    assert [r["run"] for r in measured] == [0]
    assert [r["run"] for r in failures] == [1]
    assert [r["run"] for r in harness] == [2]


def test_run_category_of_a_clean_run_is_none():
    assert run_category(_run(REAL_ANSWER)) is None


def test_a_stub_between_the_two_floors_is_still_a_model_failure():
    """Regression: the two content classifiers have different floors.

    `check_validity` rejects below 50 chars; `check_content` rejects below 200.
    A 120-character stub is valid to the first and invalid to the second.
    Consulting only the first left `qwen 3.8 - local`'s stubs unzeroed —
    scored on their vacuous lint/static passes — which is the same free credit
    by a different route.
    """
    stub = "Sure, here is the answer: it depends on the cluster configuration. " * 2
    assert validity.ABSOLUTE_FLOOR < len(stub) < validity.MIN_CONTENT_CHARS
    assert validity.check_validity(stub)["valid"] is True

    run = _run(stub, VACUOUS_STAGES)
    assert run_category(run) == MODEL_FAILURE
    assert score_run(run)["composite"] == 0.0


def test_an_explicit_classification_is_used_verbatim():
    """`bench.validate.classify_run` is the downstream source of truth: it
    reconciles both classifiers AND loads the task spec, so the spec-aware
    exclusions are only visible through it."""
    run = _run(REAL_ANSWER)
    assert run_category(run, {"verdict": "model-failure"}) == MODEL_FAILURE
    assert run_category(run, {"verdict": "invalid"}) == HARNESS_INVALID
    assert run_category(run, {"verdict": "partial"}) is None


def test_a_run_with_no_content_key_is_neither_kind_of_failure():
    """Grandfathered: predates content being recorded, or a synthetic fixture.
    It cannot be judged, so it must not be read as an empty completion."""
    assert run_category({"stages": {"lint": {"passed": True}}}) is None


# ══════════════════════════════════════════════════════════════════════════
# validate.py: a weak model is publishable, a broken harness is not
# ══════════════════════════════════════════════════════════════════════════

def test_classify_run_splits_the_reason_lists():
    empty = validate.classify_run({"content": "", "stages": dict(VACUOUS_STAGES),
                                   "stack": "terraform", "task": "T2-generate"}, spec={})
    assert empty["verdict"] == "model-failure"
    assert empty["invalid_reasons"] == []
    assert empty["model_failure_reasons"]

    leaked = validate.classify_run({"content": HARNESS_LEAK, "stages": dict(MEDIOCRE_STAGES),
                                    "stack": "terraform", "task": "T2-generate"}, spec={})
    assert leaked["verdict"] == "invalid"
    assert leaked["invalid_reasons"]
    assert leaked["model_failure_reasons"] == []


def test_an_adapter_error_stays_harness_invalid():
    """The adapter records genuine API errors and timeouts separately, and
    those remain excludable infrastructure failures."""
    errored = validate.classify_run(
        {"error": "HTTPSConnectionPool: read timed out", "content": "",
         "stages": {"lint": {"passed": False}},
         "stack": "terraform", "task": "T2-generate"},
        spec={},
    )
    assert errored["verdict"] == "invalid"
    assert any("runner_error" in r for r in errored["invalid_reasons"])


def test_a_missing_binary_pass_stays_harness_invalid():
    """The pulumi binary being off PATH is an infrastructure gap: nothing
    about the model was checked, so the run is excluded, not charged (#56)."""
    run = validate.classify_run(
        {"content": REAL_ANSWER,
         "stages": {"static": {"passed": True, "logs": "NOT FOUND: pulumi"}},
         "stack": "pulumi-python", "task": "T2-generate"},
        spec={},
    )
    assert run["verdict"] == "invalid"
    assert any("tool_missing_scored_as_pass" in r for r in run["invalid_reasons"])


def test_there_is_no_model_failure_limit():
    """Stated as a constant so anyone hunting for the missing limit finds the
    reason rather than assuming an oversight."""
    assert validate.MODEL_FAILURE_LIMIT is None


# ══════════════════════════════════════════════════════════════════════════
# report.py: the two counts are never collapsed
# ══════════════════════════════════════════════════════════════════════════

def test_report_lists_the_two_failure_kinds_as_distinct_lines():
    runs = [_run(REAL_ANSWER, run=0), _run(HARNESS_LEAK, run=1),
            _run("", VACUOUS_STAGES, run=2)]
    report = generate_report("m", runs)
    assert "- **harness-rejected: 1**" in report
    assert "- **empty answers: 1**" in report
    assert "| Harness-rejection reason | Runs |" in report
    assert "| Empty-answer reason | Runs |" in report
    # Never one combined count.
    assert "rejected: 2" not in report


def test_partition_by_validity_keeps_model_failures_in_scored():
    runs = [_run(REAL_ANSWER, run=0), _run("", run=1), _run(HARNESS_LEAK, run=2)]
    scored, rejected = partition_by_validity(runs)
    assert len(scored) == 2 and len(rejected) == 1
    assert len(model_failures(scored)) == 1


# ══════════════════════════════════════════════════════════════════════════
# THE INVARIANT
# ══════════════════════════════════════════════════════════════════════════

def _avg(runs):
    return aggregate_scores(runs)["m/terraform/T2-generate"]["avg_composite"]


def test_a_model_cannot_improve_its_average_by_emitting_nothing():
    """The invariant the whole split exists to enforce.

    Two models, four runs each, answering the same two tasks equally well.
    They differ only in what they did on the other two: one produced weak but
    real answers, the other produced nothing.

        answers_badly:  [mediocre, mediocre, weak,  weak ]
        answers_nothing:[mediocre, mediocre, empty, empty]

    `answers_nothing` did strictly worse. Any scoring rule under which it
    scores higher is broken, and blanket exclusion was exactly such a rule:
    it dropped the two empty runs and averaged the model over the two it
    happened to answer.

    This is `qwen 3.8 - local`'s #1 finish in miniature — 44 of 90 runs
    dropped rather than counted, an average taken over the survivors.
    """
    answers_badly = [
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=0),
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=1),
        _run(REAL_ANSWER, WEAK_STAGES, run=2),
        _run(REAL_ANSWER, WEAK_STAGES, run=3),
    ]
    answers_nothing = [
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=0),
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=1),
        _run("", VACUOUS_STAGES, run=2),
        _run("", VACUOUS_STAGES, run=3),
    ]

    badly = _avg(answers_badly)      # (4/9 + 4/9 + 2/9 + 2/9) / 4 = 3/9
    nothing = _avg(answers_nothing)  # (4/9 + 4/9 +   0 +   0) / 4 = 2/9

    assert badly == pytest.approx(3 / 9)
    assert nothing == pytest.approx(2 / 9)
    assert nothing < badly, (
        "a model that answered nothing twice outscored one that answered "
        "badly twice — emitting nothing is being rewarded"
    )

    # And the denominator is the real one: four runs, not two.
    agg = aggregate_scores(answers_nothing)["m/terraform/T2-generate"]
    assert agg["num_runs"] == 4
    assert agg["model_failure_runs"] == 2
    assert agg["harness_rejected_runs"] == 0


def test_the_old_exclusion_rule_is_what_rewarded_emitting_nothing():
    """The bug, demonstrated rather than asserted about.

    Recomputed here the way the pre-#69 scorer did it — drop every gate-rejected
    run, average the survivors — the model that answered nothing comes out
    AHEAD of the one that answered badly, and ahead of its own honest score.
    That inversion is the thing the split removes.
    """
    answers_badly = [
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=0),
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=1),
        _run(REAL_ANSWER, WEAK_STAGES, run=2),
        _run(REAL_ANSWER, WEAK_STAGES, run=3),
    ]
    answers_nothing = [
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=0),
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=1),
        _run("", VACUOUS_STAGES, run=2),
        _run("", VACUOUS_STAGES, run=3),
    ]

    def old_style_average(runs):
        survivors = [r for r in runs if validity.run_validity(r)["valid"]]
        composites = [compute_score(r)["composite"] for r in survivors]
        return sum(composites) / len(composites) if composites else 0.0

    old_badly = old_style_average(answers_badly)       # 3/9
    old_nothing = old_style_average(answers_nothing)   # 4/9 — averaged over 2 runs

    assert old_nothing > old_badly, "fixture no longer reproduces the bug"
    assert old_nothing > _avg(answers_nothing), (
        "exclusion did not flatter the empty-answer model; fixture is wrong"
    )
    # Under the corrected taxonomy the ordering is right way up again.
    assert _avg(answers_nothing) < _avg(answers_badly)


def test_replacing_any_answer_with_an_empty_one_can_only_lower_the_average():
    """The monotonic form of the invariant, over every run position.

    Whatever a run scored, substituting an empty completion for it must not
    raise the model's average. Checked at each of four positions rather than
    once, so a rule that happens to hold on average but not per-run fails
    here.
    """
    base = [
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=0),
        _run(REAL_ANSWER, MEDIOCRE_STAGES, run=1),
        _run(REAL_ANSWER, WEAK_STAGES, run=2),
        _run(REAL_ANSWER, WEAK_STAGES, run=3),
    ]
    baseline = _avg(base)

    for i in range(4):
        mutated = [
            _run("", VACUOUS_STAGES, run=j) if j == i
            else _run(REAL_ANSWER, MEDIOCRE_STAGES if j < 2 else WEAK_STAGES, run=j)
            for j in range(4)
        ]
        assert _avg(mutated) <= baseline, (
            f"emitting nothing on run {i} raised the average "
            f"({_avg(mutated):.4f} > {baseline:.4f})"
        )


def test_a_harness_failure_is_still_never_charged_to_the_model():
    """The other half of the split, and the reason it is a split rather than
    a blanket zero-fill: a run the harness lost must not lower the model's
    average either. It is not a measurement in the direction of failure any
    more than in the direction of success.
    """
    clean = [_run(REAL_ANSWER, MEDIOCRE_STAGES, run=0),
             _run(REAL_ANSWER, MEDIOCRE_STAGES, run=1)]
    with_harness_loss = clean + [_run(HARNESS_LEAK, WEAK_STAGES, run=2)]

    assert _avg(with_harness_loss) == _avg(clean) == MEDIOCRE
    agg = aggregate_scores(with_harness_loss)["m/terraform/T2-generate"]
    assert agg["num_runs"] == 2
    assert agg["harness_rejected_runs"] == 1
