"""
Rescore the 13 historical result sets under the corrected scorer, without
rerunning any model.

Context: docs/historical-results-audit.md found that the published leaderboard
(computed by `main`'s pre-fix `bench/score.py`) over-credited runs in three
ways — vacuous passes (a stage says "passed" when it found nothing to check),
missing-binary passes (a stage says "passed" when its own tool wasn't
installed), and disabled-stage passes (a stage that `spec.yaml` says should
never have run at all still ran, against debris in the workspace, and its
result — pass or fail — was counted anyway). `bench/score.py` on this branch
already fixes vacuous passes retroactively (`VACUOUS_LOG_MARKERS`, matched
against historical log bodies) and honors a `skipped` flag for disabled
stages — but only on runs that carry that flag, which no historical run does,
because `main`'s runner never wrote it. `bench/validate.py` independently
classifies a run `invalid` when a stage recorded a pass with its binary
absent (`tool_missing_scored_as_pass`), which is how the missing-binary bug is
corrected here: not by flipping the stage to `failed` in place, but by
excluding the whole run from every aggregate, mirroring exactly how
`bench/report.py` already treats a fresh run that trips the same gate.

What this script adds on top of what `bench/score.py` already does on its
own: for every stage `spec.yaml` disables, it replaces that stage's dict with
a clean `{"skipped": True, ...}` stub — matching what the corrected runner
would have written had it never run the check at all — *before* handing the
run to `compute_score` and `classify_run`. Without that replacement, a
disabled stage's leftover real (and sometimes accidentally missing-binary,
sometimes genuinely failing) result would still poison `classify_run`'s
missing-binary check or the correctness axis.

Two independent scorers run over every one of the 1,140 run JSONs:
  - `published_compute_score`: a byte-for-byte port of `main`'s (commit
    0f8b215) old `compute_score`, so the "published" column in the ledger
    below is not a re-derivation from memory — it is what actually shipped.
  - `bench.score.compute_score` (imported, not reimplemented) on the
    spec-gated copy: the "corrected" column.

`bench.validate.classify_run` (imported, not reimplemented), also on the
spec-gated copy, decides which runs are excluded from the corrected
aggregates entirely (`invalid`) versus kept with a caveat (`partial`).

No model is re-invoked. No file under results/ is modified — every write
goes to results-rescored/, a parallel tree.

Usage:
    python3 tools/rescore_historical.py
    python3 tools/rescore_historical.py --set claude-opus-5   # one set only
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench import validate as validate_mod  # noqa: E402
from bench.report import archetype_of  # noqa: E402
from bench.score import AXES, apply_validity, compute_score  # noqa: E402

RESULTS_DIR = ROOT / "results"
RESCORED_DIR = ROOT / "results-rescored"
TASKS_DIR = ROOT / "tasks"

# The 13 historical result sets in scope (per docs/historical-results-audit.md).
# Deliberately excludes claude-haiku-4-5-3arm, claude-haiku-4-5-probe,
# claude-opus-5-3arm, claude-opus-5-probe — those are separate calibration/
# probe sets, not part of the published 13-set leaderboard the audit covers.
HISTORICAL_SETS = [
    "claude-opus-5",
    "claude-opus-5-low",
    "claude-opus-4-8",
    "claude-opus-4-8-low",
    "gpt-5.4",
    "gpt-5.4-low",
    "gpt-5.6-sol-low",
    "glm-5.3",
    "glm-5.3-low",
    "kimi-k3",
    "qwen 3.8 - local",
    "qwen 3.8 - local-low",
    "qwen36-local",
]

STAGE_NAMES = ("lint", "static", "semantic", "e2e")

STACKS = ["knr-ops", "crossplane", "terraform", "pulumi-python", "pulumi-typescript"]


# ─────────────────────────────────────────────────────────────────────────
# The published formula, vendored verbatim from `git show origin/main:bench/
# score.py` (commit 0f8b215, the commit the audit scoped to and the commit
# `main` is at as of this rescore). This is what produced the leaderboard
# that shipped. Kept as a literal port rather than "the old behavior,
# approximately" so the "published" column is reproducible from this file
# alone, without needing a second git checkout.
# ─────────────────────────────────────────────────────────────────────────

def published_compute_score(result: dict[str, Any]) -> dict[str, Any]:
    stages = result.get("stages", {})
    scores: dict[str, Any] = {}

    stage_pass = sum(
        1 for name in ("lint", "static", "semantic")
        if stages.get(name, {}).get("passed", False)
    )
    total_stages = 3
    if stages.get("e2e"):
        total_stages = 4
        stage_pass += 1 if stages["e2e"].get("passed", False) else 0
    scores["correctness"] = stage_pass / total_stages if total_stages else 0

    semantic = stages.get("semantic", {})
    passed_count = semantic.get("passed_count", 0)
    total_count = semantic.get("total_count", 0)
    scores["completeness"] = passed_count / total_count if total_count else 1.0

    scores["safety"] = 1.0 if semantic.get("safety_pass", True) else 0.0
    scores["consistency"] = 0.0
    scores["idiom"] = 0.0

    composite = sum(scores[axis] * AXES[axis] for axis in AXES) / sum(AXES.values())
    scores["composite"] = composite
    return scores


# ─────────────────────────────────────────────────────────────────────────
# Spec-informed stage gating: what bench/runner.py would have written for a
# disabled stage, applied retroactively.
# ─────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def load_spec(stack: str, task: str) -> dict[str, Any] | None:
    spec_path = TASKS_DIR / stack / task / "spec.yaml"
    if not spec_path.exists():
        return None
    try:
        return yaml.safe_load(spec_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return None


def stage_enabled(spec: dict[str, Any] | None, name: str) -> bool:
    """Mirrors bench.runner._stage_enabled's default-True semantics."""
    if not spec:
        return True
    stage_spec = (spec.get("stages") or {}).get(name) or {}
    return bool(stage_spec.get("enabled", True))


def gate_disabled_stages(
    stages: dict[str, Any], spec: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Replace every spec-disabled stage with a clean skipped stub.

    Returns (corrected_stages, retroactively_skipped_stage_names). A stage is
    "retroactively skipped" when spec.yaml disables it but the historical
    result recorded a real stage dict anyway (main's runner ran every stage
    regardless of spec.yaml) — the disabled-stage-pass bug (#3 in the audit).
    """
    corrected: dict[str, Any] = {}
    retro: list[str] = []
    for name in STAGE_NAMES:
        original = stages.get(name)
        if not stage_enabled(spec, name):
            if isinstance(original, dict) and original and not original.get("skipped"):
                retro.append(name)
            corrected[name] = {
                "skipped": True,
                "reason": "disabled by spec.yaml (retroactively applied by rescore; "
                          "the historical run executed this stage anyway because "
                          "main's runner did not honor spec.yaml stage gating)",
            }
        elif original is not None:
            corrected[name] = copy.deepcopy(original)
    return corrected, retro


# ─────────────────────────────────────────────────────────────────────────
# Composite recomputed over a subset of axes (for the "with/without idiom"
# comparison — compute_score always includes idiom at its historical-default
# 0.0, by design, so this is computed separately rather than by a flag on
# compute_score itself).
# ─────────────────────────────────────────────────────────────────────────

def composite_over(score: dict[str, Any], axes: dict[str, int]) -> float:
    denom = sum(axes.values())
    if not denom:
        return 0.0
    return sum(score.get(axis, 0.0) * weight for axis, weight in axes.items()) / denom


def corrected_axes(score: dict[str, Any], drop: frozenset[str] = frozenset()) -> dict[str, int]:
    names = score.get("applicable_axes") or list(AXES)
    return {a: AXES[a] for a in names if a in AXES and a not in drop}


def published_axes(drop: frozenset[str] = frozenset()) -> dict[str, int]:
    # The published formula never excludes an axis (completeness defaults to
    # 1.0 rather than being dropped), so all 5 axes are always "applicable".
    return {a: w for a, w in AXES.items() if a not in drop}


# ─────────────────────────────────────────────────────────────────────────
# Per-run rescoring
# ─────────────────────────────────────────────────────────────────────────

def rescore_run(raw: dict[str, Any], rel_path: str) -> dict[str, Any]:
    stack, task = raw.get("stack"), raw.get("task")
    spec = load_spec(str(stack), str(task)) if stack and task else None

    published_score = published_compute_score(raw)

    corrected = copy.deepcopy(raw)
    corrected_stages, retro_skipped = gate_disabled_stages(raw.get("stages") or {}, spec)
    corrected["stages"] = corrected_stages

    # Classify first, then score: #69's `apply_validity` zeroes a run whose
    # model produced nothing usable, and it needs classify_run's verdict to do
    # it — the spec-aware exclusions (`no_extractable_output`,
    # `all_stages_inapplicable`) are invisible to the content classifiers on
    # their own. Without this a rescore would keep handing empty completions
    # the vacuous lint/static passes they recorded ("no YAML files in
    # workspace").
    classification = validate_mod.classify_run(corrected, spec)
    corrected["score"] = apply_validity(
        corrected, compute_score(corrected), classification
    )

    corrected_no_idiom = composite_over(
        corrected["score"], corrected_axes(corrected["score"], frozenset({"idiom"}))
    )
    published_no_idiom = composite_over(
        published_score, published_axes(frozenset({"idiom"}))
    )

    corrected["_rescore"] = {
        "method": "recomputation of an already-published run under the corrected "
                  "scorer (bench/score.py, bench/validate.py, bench/validity.py "
                  "on branch bench/historical-rescore) — no model was re-invoked "
                  "and no original result JSON was modified",
        "source_file": rel_path,
        "published_score": published_score,
        "published_composite_no_idiom": published_no_idiom,
        "corrected_score": corrected["score"],
        "corrected_composite_no_idiom": corrected_no_idiom,
        "validity_verdict": classification["verdict"],
        "invalid_reasons": classification["invalid_reasons"],
        "model_failure_reasons": classification.get("model_failure_reasons", []),
        "partial_reasons": classification["partial_reasons"],
        "retroactively_skipped_stages": retro_skipped,
    }
    return corrected


# ─────────────────────────────────────────────────────────────────────────
# Driving the rescore across all 13 sets
# ─────────────────────────────────────────────────────────────────────────

def load_set_runs(set_name: str) -> list[tuple[Path, dict[str, Any]]]:
    set_dir = RESULTS_DIR / set_name
    runs = []
    for f in sorted(set_dir.rglob("*.json")):
        if "run" not in f.stem:
            continue
        with open(f) as fp:
            runs.append((f, json.load(fp)))
    return runs


def summarize_set(set_name: str, rescored: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rescored)
    invalid = [r for r in rescored if r["_rescore"]["validity_verdict"] == "invalid"]
    partial = [r for r in rescored if r["_rescore"]["validity_verdict"] == "partial"]
    valid = [r for r in rescored if r["_rescore"]["validity_verdict"] == "valid"]
    # #69: a model-failure run is scored (at 0.0), not excluded. Only
    # harness-invalid runs leave the denominator.
    failures = [r for r in rescored if r["_rescore"]["validity_verdict"] == "model-failure"]
    scored = [r for r in rescored if r["_rescore"]["validity_verdict"] != "invalid"]

    published_composites = [r["_rescore"]["published_score"]["composite"] for r in rescored]
    corrected_composites = [r["_rescore"]["corrected_score"]["composite"] for r in scored]
    corrected_no_idiom = [r["_rescore"]["corrected_composite_no_idiom"] for r in scored]

    # The two views PR #68 published, kept so this rescore can be compared
    # against it line for line. Both predate the #69 taxonomy and treat every
    # gate rejection alike.
    #
    #   exclude_all  — PR #68's "corrected" column: drop every gate-rejected
    #                  run, harness failure and empty answer together, and
    #                  average the survivors. This is the view that let
    #                  `qwen 3.8 - local` hold rank #1 on 46 surviving runs
    #                  of 90.
    #   zero_fill_all — PR #68's robustness column: keep every run and score
    #                  every rejection 0.0, including the ones the harness
    #                  lost. Under this view the same set falls to #12.
    #
    # PR #68 reported both and declined to pick, because the choice turned on
    # whether unusable model output is "no data" or "a failure" — a question
    # it could not answer without splitting the two causes apart. #69 splits
    # them: the answer is "no data" for a harness failure and "a failure" for
    # an empty answer, which is neither of these views.
    def _measured(r: dict[str, Any]) -> float:
        score = r["_rescore"]["corrected_score"]
        return score.get("composite_measured", score["composite"])

    exclude_all = [
        _measured(r) for r in rescored
        if r["_rescore"]["validity_verdict"] in ("valid", "partial")
    ]
    zero_fill_all = [
        (_measured(r) if r["_rescore"]["validity_verdict"] in ("valid", "partial") else 0.0)
        for r in rescored
    ]

    reject_reasons: Counter[str] = Counter()
    for r in invalid:
        for reason in r["_rescore"]["invalid_reasons"]:
            reject_reasons[reason.split(":", 1)[0]] += 1

    failure_reasons: Counter[str] = Counter()
    for r in failures:
        for reason in r["_rescore"]["model_failure_reasons"]:
            failure_reasons[reason.split(":", 1)[0]] += 1

    retro_skip_reasons: Counter[str] = Counter()
    for r in rescored:
        for name in r["_rescore"]["retroactively_skipped_stages"]:
            retro_skip_reasons[name] += 1

    by_stack_published: dict[str, list[float]] = {s: [] for s in STACKS}
    by_stack_corrected: dict[str, list[float]] = {s: [] for s in STACKS}
    for r in rescored:
        stack = r.get("stack", "")
        if stack in by_stack_published:
            by_stack_published[stack].append(r["_rescore"]["published_score"]["composite"])
    for r in scored:
        stack = r.get("stack", "")
        if stack in by_stack_corrected:
            by_stack_corrected[stack].append(r["_rescore"]["corrected_score"]["composite"])

    # Per-run monotonicity check: does the corrected composite ever exceed
    # the published composite for the *same* run? (Only meaningful for runs
    # that survive into the corrected aggregate — an excluded run has no
    # corrected composite to compare.)
    increases = []
    for r in scored:
        pub = r["_rescore"]["published_score"]["composite"]
        cor = r["_rescore"]["corrected_score"]["composite"]
        if cor > pub + 1e-9:
            increases.append({
                "source_file": r["_rescore"]["source_file"],
                "published": pub,
                "corrected": cor,
                "delta": cor - pub,
            })

    return {
        "set": set_name,
        "total": total,
        "num_valid": len(valid),
        "num_partial": len(partial),
        "num_invalid": len(invalid),
        "num_model_failure": len(failures),
        "num_scored": len(scored),
        "reject_reasons": dict(reject_reasons),
        "model_failure_reasons": dict(failure_reasons),
        "retroactively_skipped_stage_counts": dict(retro_skip_reasons),
        "avg_published_composite": (
            sum(published_composites) / len(published_composites) if published_composites else 0.0
        ),
        "avg_corrected_composite": (
            sum(corrected_composites) / len(corrected_composites) if corrected_composites else 0.0
        ),
        "avg_corrected_composite_no_idiom": (
            sum(corrected_no_idiom) / len(corrected_no_idiom) if corrected_no_idiom else 0.0
        ),
        # PR #68's two views, for line-for-line comparison.
        "avg_pr68_exclude_all": (
            sum(exclude_all) / len(exclude_all) if exclude_all else 0.0
        ),
        "avg_pr68_zero_fill_all": (
            sum(zero_fill_all) / len(zero_fill_all) if zero_fill_all else 0.0
        ),
        "num_pr68_excluded": len(rescored) - len(exclude_all),
        "by_stack_avg_published": {
            s: (sum(v) / len(v) if v else None) for s, v in by_stack_published.items()
        },
        "by_stack_avg_corrected": {
            s: (sum(v) / len(v) if v else None) for s, v in by_stack_corrected.items()
        },
        "per_run_composite_increases": increases,
    }


# ─────────────────────────────────────────────────────────────────────────
# LEADERBOARD.md
# ─────────────────────────────────────────────────────────────────────────

def _rank(items: list[tuple[str, float]]) -> dict[str, int]:
    ordered = sorted(items, key=lambda kv: -kv[1])
    return {name: i + 1 for i, (name, _val) in enumerate(ordered)}


def build_leaderboard_md(summaries: list[dict[str, Any]]) -> str:
    pub_rank = _rank([(s["set"], s["avg_published_composite"]) for s in summaries])
    cor_rank = _rank([(s["set"], s["avg_corrected_composite"]) for s in summaries])
    cor_no_idiom_rank = _rank(
        [(s["set"], s["avg_corrected_composite_no_idiom"]) for s in summaries]
    )

    lines: list[str] = []
    lines.append("# Historical Results — Rescored Leaderboard")
    lines.append("")
    lines.append(
        "Every run below is an existing, previously published run recomputed "
        "under the corrected scorer on `bench/historical-rescore` "
        "(`bench/score.py` + `bench/validate.py` + `bench/validity.py`). No "
        "model was re-invoked. See `results-rescored/README.md` for method, "
        "and `docs/historical-results-audit.md` for the audit that motivated "
        "this rescore."
    )
    lines.append("")

    # Assert the required invariant now, in this document, rather than only
    # in a test: no result set's corrected average composite exceeds its
    # published average composite.
    violations = [
        s["set"] for s in summaries
        if s["avg_corrected_composite"] > s["avg_published_composite"] + 1e-9
    ]
    assert not violations, (
        f"invariant violated: corrected average composite exceeds published "
        f"for {violations} — the corrected scorer must never award more "
        f"credit than the published one, only less or equal"
    )

    lines.append(
        "**Sanity check (asserted, not just reported): no result set's "
        "corrected average composite exceeds its published average "
        "composite.** Verified for all 13 sets below."
    )
    lines.append("")

    any_per_run_increase = any(s["per_run_composite_increases"] for s in summaries)
    if any_per_run_increase:
        lines.append(
            "**Note:** a small number of *individual* runs (not set averages) "
            "show a higher corrected composite than published — see "
            "\"Per-run composite increases\" below for the full list and why."
        )
        lines.append("")

    lines.append("## Leaderboard: published vs. corrected")
    lines.append("")
    lines.append(
        "`Harness-rejected` runs are excluded from the corrected average; "
        "`empty answers` score 0.0 and stay in its denominator (#69). The two "
        "columns are never summed — which of them a run lands in is what "
        "decides whether it lowers the model's score or leaves it alone."
    )
    lines.append("")
    lines.append(
        "| # pub | Result set | Published | # corr | Corrected | Δ | "
        "Harness-rejected | Empty answers | Harness reasons | Empty-answer reasons |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in sorted(summaries, key=lambda s: pub_rank[s["set"]]):
        name = s["set"]
        delta = s["avg_corrected_composite"] - s["avg_published_composite"]
        reasons = ", ".join(f"{v}× `{k}`" for k, v in sorted(
            s["reject_reasons"].items(), key=lambda kv: -kv[1]
        )) or "—"
        failure_reasons = ", ".join(f"{v}× `{k}`" for k, v in sorted(
            s["model_failure_reasons"].items(), key=lambda kv: -kv[1]
        )) or "—"
        lines.append(
            f"| {pub_rank[name]} | {name} | {s['avg_published_composite']:.3f} | "
            f"{cor_rank[name]} | {s['avg_corrected_composite']:.3f} | {delta:+.3f} | "
            f"{s['num_invalid']}/{s['total']} | {s['num_model_failure']}/{s['total']} | "
            f"{reasons} | {failure_reasons} |"
        )
    lines.append("")

    lines.append("## Same leaderboard, corrected composite excluding the idiom axis")
    lines.append("")
    lines.append(
        "Idiom (weight 1 of 9, or 1 of 8 on a run where completeness is also "
        "inapplicable) carries a rubric-judge verdict — `bench.score.idiom_score` "
        "— and **every one of the 1,140 historical runs has none** (no run "
        "carries a `judge` field; the rubric judge did not exist yet when "
        "these sets were produced). Idiom scores 0.0 on literally every run "
        "in every one of the 13 sets, so it is not a measured axis for this "
        "dataset at all — it is a fixed penalty applied uniformly. This view "
        "drops it and renormalizes over the remaining applicable axes."
    )
    lines.append("")
    lines.append("| # pub | Result set | Corrected (w/ idiom) | # (no idiom) | Corrected (no idiom) | Rank moves? |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for s in sorted(summaries, key=lambda s: pub_rank[s["set"]]):
        name = s["set"]
        moved = "no" if cor_rank[name] == cor_no_idiom_rank[name] else (
            f"yes ({cor_rank[name]} -> {cor_no_idiom_rank[name]})"
        )
        lines.append(
            f"| {pub_rank[name]} | {name} | {s['avg_corrected_composite']:.3f} | "
            f"{cor_no_idiom_rank[name]} | {s['avg_corrected_composite_no_idiom']:.3f} | {moved} |"
        )
    lines.append("")
    stable = all(cor_rank[s["set"]] == cor_no_idiom_rank[s["set"]] for s in summaries)
    lines.append(
        f"**Ordering is {'stable' if stable else 'NOT stable'} once idiom is "
        "dropped.** Since idiom is a uniform 0.0 across every run in every "
        "set, this isolates whether idiom's fixed weight is doing any of the "
        "reordering work in the corrected leaderboard above, versus the "
        "reordering coming entirely from correctness/completeness/safety, "
        "which the historical runs did genuinely measure."
    )
    lines.append("")

    lines.append("## The three views: PR #68's two, and the #69 taxonomy")
    lines.append("")
    lines.append(
        "PR #68 reported two leaderboards and deliberately picked neither, "
        "because the choice between them turned on a question it could not "
        "answer without splitting the two causes of a rejected run apart:"
    )
    lines.append("")
    lines.append(
        "- **Exclude all** — drop every gate-rejected run, harness failure and "
        "empty answer alike, and average what survives. Principled per run "
        "(\"not a measurement\"), but it lets a model that answers nothing "
        "half the time be judged on the half it answered."
    )
    lines.append(
        "- **Zero-fill all** — keep every run and score every rejection 0.0, "
        "including runs the harness lost. Fixes the survivorship bias by "
        "also charging models for the harness's own failures."
    )
    lines.append(
        "- **#69 taxonomy** — the two causes get different treatment. A "
        "harness failure is excluded (nothing about the model was captured); "
        "an empty answer scores 0.0 and stays in the denominator (the model "
        "was measured, and produced nothing). Neither of PR #68's views, and "
        "not between them either: it is higher than zero-fill for sets whose "
        "losses were the harness's fault, and lower than exclude-all for sets "
        "whose losses were the model's."
    )
    lines.append("")
    ex_rank = _rank([(s["set"], s["avg_pr68_exclude_all"]) for s in summaries])
    zf_rank = _rank([(s["set"], s["avg_pr68_zero_fill_all"]) for s in summaries])
    lines.append(
        "| Result set | #68 exclude-all | rank | #68 zero-fill | rank | "
        "#69 taxonomy | rank | Rank Δ vs exclude-all |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in sorted(summaries, key=lambda s: cor_rank[s["set"]]):
        name = s["set"]
        shift = ex_rank[name] - cor_rank[name]
        lines.append(
            f"| {name} | {s['avg_pr68_exclude_all']:.3f} | {ex_rank[name]} | "
            f"{s['avg_pr68_zero_fill_all']:.3f} | {zf_rank[name]} | "
            f"**{s['avg_corrected_composite']:.3f}** | **{cor_rank[name]}** | "
            f"{shift:+d} |"
        )
    lines.append("")
    same_as_exclude = all(ex_rank[s["set"]] == cor_rank[s["set"]] for s in summaries)
    same_as_zf = all(zf_rank[s["set"]] == cor_rank[s["set"]] for s in summaries)
    lines.append(
        f"The #69 ordering {'matches' if same_as_exclude else 'differs from'} "
        f"PR #68's exclude-all ordering and "
        f"{'matches' if same_as_zf else 'differs from'} its zero-fill ordering."
    )
    lines.append("")

    lines.append("### Where the two causes actually landed")
    lines.append("")
    lines.append(
        "The whole disagreement between PR #68's two views lives in this "
        "table: for each set, how many of the runs it lost were the harness's "
        "fault and how many were the model's."
    )
    lines.append("")
    lines.append(
        "| Result set | #68 excluded | of which harness | of which model | "
        "Share of loss that was the model's |"
    )
    lines.append("| --- | --- | --- | --- | --- |")
    for s in sorted(summaries, key=lambda s: -s["num_pr68_excluded"]):
        lost = s["num_pr68_excluded"]
        share = f"{s['num_model_failure'] / lost:.0%}" if lost else "—"
        lines.append(
            f"| {s['set']} | {lost}/{s['total']} | {s['num_invalid']} | "
            f"{s['num_model_failure']} | {share} |"
        )
    lines.append("")

    return "\n".join(lines)


def build_stack_table(all_runs: list[dict[str, Any]]) -> str:
    """Per-stack published vs corrected, n-weighted over every run in the
    dataset (not averaged-of-averages across sets)."""
    lines = ["## Per-stack composite (n-weighted, all 13 sets combined)", ""]
    lines.append("| Stack | n | Published | n scored | Corrected | Δ |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    pub_total, cor_total = [], []
    for stack in STACKS:
        stack_runs = [r for r in all_runs if r.get("stack") == stack]
        pub_vals = [r["_rescore"]["published_score"]["composite"] for r in stack_runs]
        scored_runs = [r for r in stack_runs if r["_rescore"]["validity_verdict"] != "invalid"]
        cor_vals = [r["_rescore"]["corrected_score"]["composite"] for r in scored_runs]
        pub_avg = sum(pub_vals) / len(pub_vals) if pub_vals else 0.0
        cor_avg = sum(cor_vals) / len(cor_vals) if cor_vals else 0.0
        pub_total += pub_vals
        cor_total += cor_vals
        lines.append(
            f"| {stack} | {len(pub_vals)} | {pub_avg:.3f} | {len(cor_vals)} | "
            f"{cor_avg:.3f} | {cor_avg - pub_avg:+.3f} |"
        )
    pub_overall = sum(pub_total) / len(pub_total) if pub_total else 0.0
    cor_overall = sum(cor_total) / len(cor_total) if cor_total else 0.0
    lines.append(
        f"| **overall** | {len(pub_total)} | {pub_overall:.3f} | {len(cor_total)} | "
        f"{cor_overall:.3f} | {cor_overall - pub_overall:+.3f} |"
    )
    lines.append("")
    return "\n".join(lines)


def build_model_stack_grid(all_runs: list[dict[str, Any]], corrected: bool) -> str:
    """Rows = result sets, columns = stacks, one grid for published, one for corrected."""
    label = "corrected" if corrected else "published"
    lines = [f"### Per-model x stack composite ({label})", ""]
    lines.append("| Result set | " + " | ".join(STACKS) + " |")
    lines.append("| --- | " + " | ".join(["---"] * len(STACKS)) + " |")
    for set_name in HISTORICAL_SETS:
        row = [set_name]
        set_runs = [r for r in all_runs if _set_of(r) == set_name]
        for stack in STACKS:
            stack_runs = [r for r in set_runs if r.get("stack") == stack]
            if corrected:
                vals = [
                    r["_rescore"]["corrected_score"]["composite"]
                    for r in stack_runs
                    if r["_rescore"]["validity_verdict"] != "invalid"
                ]
            else:
                vals = [r["_rescore"]["published_score"]["composite"] for r in stack_runs]
            row.append(f"{sum(vals)/len(vals):.2f}" if vals else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def _set_of(run: dict[str, Any]) -> str:
    src = run["_rescore"]["source_file"]
    return src.split("/", 1)[0]


def big_movers_section(summaries: list[dict[str, Any]]) -> str:
    pub_rank = _rank([(s["set"], s["avg_published_composite"]) for s in summaries])
    cor_rank = _rank([(s["set"], s["avg_corrected_composite"]) for s in summaries])
    ex_rank = _rank([(s["set"], s["avg_pr68_exclude_all"]) for s in summaries])
    moves = sorted(
        summaries,
        key=lambda s: -max(
            abs(pub_rank[s["set"]] - cor_rank[s["set"]]),
            abs(ex_rank[s["set"]] - cor_rank[s["set"]]),
        ),
    )
    lines = ["## Biggest rank movers", ""]
    lines.append(
        "Ranked by the larger of |published rank − #69 rank| and |PR #68 "
        "exclude-all rank − #69 rank|. The second is the one #69 is about: a "
        "set moves against exclude-all exactly in proportion to how much of "
        "its lost output was the model's fault rather than the harness's."
    )
    lines.append("")
    lines.append(
        "| Result set | Published rank | #68 exclude-all rank | #69 rank | "
        "Rank Δ vs published | Rank Δ vs exclude-all | Composite Δ vs published | "
        "Harness-rejected | Empty answers |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in moves[:6]:
        name = s["set"]
        lines.append(
            f"| {name} | {pub_rank[name]} | {ex_rank[name]} | {cor_rank[name]} | "
            f"{cor_rank[name] - pub_rank[name]:+d} | "
            f"{cor_rank[name] - ex_rank[name]:+d} | "
            f"{s['avg_corrected_composite'] - s['avg_published_composite']:+.3f} | "
            f"{s['num_invalid']}/{s['total']} | {s['num_model_failure']}/{s['total']} |"
        )
    lines.append("")
    return "\n".join(lines)


def increases_section(summaries: list[dict[str, Any]]) -> str:
    all_inc = [(s["set"], inc) for s in summaries for inc in s["per_run_composite_increases"]]
    if not all_inc:
        return (
            "## Per-run composite increases\n\n"
            "None. Every scored run's corrected composite is less than or "
            "equal to its published composite — the invariant holds at the "
            "individual-run level, not just in aggregate.\n"
        )
    lines = ["## Per-run composite increases", "",
              "Individual runs (not set averages) where the corrected composite "
              "exceeds the published one. This can happen even though the "
              "corrected scorer never awards new credit, because removing a "
              "*disabled* stage's leftover real result can remove a genuine "
              "failure (not just a fake pass) from the correctness denominator "
              "— see README.md for why this is expected, not a bug in this tool.",
              "",
              "| Result set | Run | Published | Corrected | Δ |",
              "| --- | --- | --- | --- | --- |"]
    for set_name, inc in sorted(all_inc, key=lambda x: -x[1]["delta"]):
        lines.append(
            f"| {set_name} | {inc['source_file']} | {inc['published']:.3f} | "
            f"{inc['corrected']:.3f} | {inc['delta']:+.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def coverage_section(summaries: list[dict[str, Any]]) -> str:
    lines = ["## Coverage and exclusions, per set", "",
              "| Result set | Total | Valid | Partial | Empty answers (scored 0) | "
              "Harness-rejected (excluded) | Retroactively-skipped stages |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for s in summaries:
        retro = sum(s["retroactively_skipped_stage_counts"].values())
        lines.append(
            f"| {s['set']} | {s['total']} | {s['num_valid']} | {s['num_partial']} | "
            f"{s['num_model_failure']} | {s['num_invalid']} | {retro} |"
        )
    lines.append("")
    lines.append(
        "> \"Valid\" vs \"partial\": every historical run predates the "
        "provenance stamp (harness commit, toolchain fingerprint, prompt "
        "hash), so `bench.validate.classify_run` marks every non-excluded "
        "run `partial` rather than `valid` — this is expected for the whole "
        "dataset and is not a new finding. Partial runs are still counted in "
        "the corrected composite. Empty answers are counted too, at 0.0. Only "
        "harness-rejected runs are excluded (#69)."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="only_set", default=None,
                         help="Rescore one set only (for iteration/debugging)")
    parser.add_argument("--out-dir", default=str(RESCORED_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    sets = [args.only_set] if args.only_set else HISTORICAL_SETS

    summaries = []
    all_runs: list[dict[str, Any]] = []
    for set_name in sets:
        set_out = out_dir / set_name
        runs = load_set_runs(set_name)
        rescored = []
        for path, raw in runs:
            rel = str(path.relative_to(RESULTS_DIR))
            corrected = rescore_run(raw, rel)
            rescored.append(corrected)
            out_path = set_out / path.relative_to(RESULTS_DIR / set_name)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as fp:
                json.dump(corrected, fp, indent=2)
                fp.write("\n")
        summary = summarize_set(set_name, rescored)
        summaries.append(summary)
        all_runs.extend(rescored)
        print(
            f"{set_name}: {summary['total']} runs, "
            f"published={summary['avg_published_composite']:.3f} "
            f"corrected={summary['avg_corrected_composite']:.3f} "
            f"harness-rejected={summary['num_invalid']} "
            f"empty-answers={summary['num_model_failure']}"
        )

    if args.only_set:
        return 0

    md = build_leaderboard_md(summaries)
    md += "\n" + build_stack_table(all_runs)
    md += "\n" + build_model_stack_grid(all_runs, corrected=False)
    md += "\n" + build_model_stack_grid(all_runs, corrected=True)
    md += "\n" + big_movers_section(summaries)
    md += "\n" + coverage_section(summaries)
    md += "\n" + increases_section(summaries)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "LEADERBOARD.md").write_text(md)
    (out_dir / "rescore-stats.json").write_text(json.dumps(summaries, indent=2))
    print(f"\nWrote {out_dir / 'LEADERBOARD.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
