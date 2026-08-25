"""
Results validator: classify every run in a result directory before anything
quotes a number from it.

Ported from chant-bench's `scripts/validate_results.py` and aws-bench's
`audit.py`. The rule both of them settled on, after publishing a run that had
lost 22 of its 24 trials and still printed 1.000, is that a run which did not
measure the model is not a low score — it is not a measurement, and it has to
happen again. So this classifies rather than averages, and bench.report gives
a rejected run no number at all.

Usage:
    python3 -m bench.validate results/claude-opus-5
    python3 -m bench.validate results/*            # every set
    python3 -m bench.validate results/x --json     # machine-readable

Exit codes: 0 when every set is publishable, 1 when any set is refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from bench import validity
from bench.provenance import toolchain_fingerprint
from bench.score import stage_attempted, stage_inapplicable

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"

# Share of a set's runs that may have died in the harness before the set stops
# describing the model. chant-bench's CRASH_LIMIT, same value and same
# reasoning: at 1 in 24 the denominator barely moves, at 1 in 6 a rate over
# the survivors is not a rate over the run. One constant, not two — aws-bench
# carries this number twice and the copies can drift.
#
# This counts `runner_error` only — an adapter/API failure, which is the
# harness dying. It deliberately does NOT count a model that answered nothing:
# see MODEL_FAILURE_LIMIT below.
CRASH_LIMIT = 0.10

# Share of a set's runs the HARNESS-invalidity gates may reject before the set
# as a whole is unpublishable. Deliberately the same 10%: a couple of
# uncapturable completions in a 90-run suite is noise, a third of them is a
# broken harness wearing a score.
#
# Scoped to harness-invalid runs only since #69. Model failures — empty
# answers, stubs, prose where a file was needed — are a measurement, not a
# malfunction, and a set full of them is a publishable result about a weak
# model. Refusing such a set would mean the benchmark could only report on
# models good enough to answer, which is the survivorship bias #69 exists to
# remove, applied to whole result sets instead of individual runs.
REJECT_LIMIT = 0.10

# There is deliberately no upper limit on model failures. A set where the
# model answered nothing 90 times out of 90 scores 0.000 and publishes; that
# is the correct report of what happened. This constant exists to be found by
# anyone looking for the limit that is not here.
MODEL_FAILURE_LIMIT = None

STAGE_NAMES = ("lint", "static", "semantic", "e2e")


# ──────────────────────────────────────────────────────────────────────────
# Per-run classification
# ──────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _load_spec(stack: str, task: str) -> dict[str, Any] | None:
    """Cached: classifying 1140 runs otherwise re-reads ~40 specs 1140 times."""
    spec_path = TASKS_DIR / stack / task / "spec.yaml"
    if not spec_path.exists():
        return None
    try:
        return yaml.safe_load(spec_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return None


def _spec_for(result: dict[str, Any]) -> dict[str, Any] | None:
    stack, task = result.get("stack"), result.get("task")
    if not stack or not task:
        return None
    return _load_spec(str(stack), str(task))


def classify_run(result: dict[str, Any], spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify one run as valid / partial / model-failure / invalid.

    Four states, because "the run produced no number" has two causes that must
    not be averaged the same way (#69):

    - `invalid` — HARNESS-rejected. The harness failed to capture a completion
      (tool markup leaked into the answer, the adapter errored, a stage's
      binary was missing), so no measurement of the model exists. The run must
      not contribute a number anywhere, and a set full of these is broken.
    - `model-failure` — the harness worked and the model produced nothing
      usable. This IS a measurement: the run scores 0 and stays in the
      denominator. A set full of these is a real result about the model.
    - `partial` — usable, but its provenance is incomplete, so it cannot be
      compared against another set.
    - `valid`.

    Both failure lists are returned separately (`invalid_reasons`,
    `model_failure_reasons`) rather than merged, because collapsing them is
    exactly the bug this split fixes. `invalid_reasons` keeps its original
    meaning — "reasons this run is excluded" — so callers that only knew about
    exclusion stay correct.
    """
    invalid: list[str] = []
    model_failure: list[str] = []
    partial: list[str] = []

    def _file(reason: str) -> None:
        (
            model_failure
            if validity.categorize_reason(reason) == validity.MODEL_FAILURE
            else invalid
        ).append(reason)

    stages = result.get("stages") or {}

    # 1. The harness itself failed: the adapter raised, the API errored, the
    #    request timed out. Nothing about the model was captured.
    if result.get("error"):
        invalid.append(f"runner_error: {str(result['error'])[:160]}")

    # 2. Content shape (#59). Re-derived rather than trusted, so a result
    #    written before the gate existed gets the same verdict a fresh run
    #    would — the point of making the gate pure text classification.
    recorded = result.get("validity")
    if isinstance(recorded, dict) and recorded.get("reasons") is not None:
        verdict = recorded
    else:
        if spec is None:
            spec = _spec_for(result)
        verdict = validity.check_result(result, spec)
    if verdict.get("verdict") == "invalid":
        for reason in verdict.get("reasons", []):
            _file(reason)

    # 3. A stage that recorded a pass while saying its binary was absent is
    #    the #56 lie in stored form. Fixed at run time; still on disk in every
    #    result written before the fix, so it is caught here too.
    for name in STAGE_NAMES:
        stage = stages.get(name)
        if not isinstance(stage, dict):
            continue
        if stage.get("passed") and "NOT FOUND:" in (stage.get("logs") or ""):
            missing = [
                line.split("NOT FOUND:", 1)[1].strip()
                for line in (stage.get("logs") or "").splitlines()
                if "NOT FOUND:" in line
            ]
            invalid.append(
                f"tool_missing_scored_as_pass: stage `{name}` recorded a pass "
                f"with its binary absent ({', '.join(missing) or 'unknown'}) — "
                "nothing was checked (#56)"
            )

    # 4. Every stage the spec enabled had nothing to act on. The run produced
    #    no artifact any gate could look at, so there is no measurement here
    #    however the individual stages were recorded (#3, the vacuous pass).
    present = [stages.get(n) for n in STAGE_NAMES if isinstance(stages.get(n), dict)]
    enabled = [s for s in present if not s.get("skipped")]
    if enabled and all(stage_inapplicable(s) for s in enabled):
        _file(
            "all_stages_inapplicable: every enabled stage had nothing to act "
            "on — the run produced no output any gate could check"
        )
    if present and not enabled:
        partial.append(
            "no_stage_ran: every stage was disabled by spec; this run scores "
            "on the rubric judge alone"
        )

    # 5. Provenance. Without it a re-run after any harness change is silently
    #    a different experiment (chant-bench's comparability rule).
    prov = result.get("provenance")
    if not isinstance(prov, dict):
        partial.append(
            "no_provenance: run predates the provenance stamp — harness "
            "commit, prompt hash and toolchain versions are unrecoverable, so "
            "it cannot be compared against another set"
        )
    else:
        if not (prov.get("harness") or {}).get("commit"):
            partial.append("no_harness_commit: harness git state was not recorded")
        elif (prov.get("harness") or {}).get("dirty"):
            partial.append(
                "dirty_harness: produced from a working tree with uncommitted "
                "changes, so the recorded commit does not describe the code that ran"
            )
        if not prov.get("toolchain"):
            partial.append("no_toolchain: binary versions were not recorded")
        if prov.get("partial"):
            partial.append(
                "partial_toolchain: run set was started with --allow-missing-tools"
            )
        if not (prov.get("task") or {}).get("prompt_sha256"):
            partial.append("no_prompt_hash: the task prompt was not fingerprinted")

    # Harness invalidity outranks model failure: if the harness failed to
    # capture the completion, whatever the completion looks like is not
    # evidence about the model.
    if invalid:
        state = "invalid"
    elif model_failure:
        state = "model-failure"
    elif partial:
        state = "partial"
    else:
        state = "valid"

    return {
        "verdict": state,
        "invalid_reasons": invalid,
        "model_failure_reasons": model_failure,
        "partial_reasons": partial,
        "attempted_stages": sum(1 for s in present if stage_attempted(s)),
    }


# ──────────────────────────────────────────────────────────────────────────
# Set-level validation
# ──────────────────────────────────────────────────────────────────────────

def _load_runs(result_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    runs: list[tuple[Path, dict[str, Any]]] = []
    for f in sorted(result_dir.rglob("*.json")):
        if "run" not in f.stem:
            continue
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError) as e:
            runs.append((f, {"_unreadable": str(e)}))
            continue
        if isinstance(data, dict) and "stages" in data:
            runs.append((f, data))
    return runs


def validate_result_set(result_dir: Path) -> dict[str, Any]:
    """Classify every run in one result-set directory and judge the set."""
    runs = _load_runs(result_dir)
    report: dict[str, Any] = {
        "path": str(result_dir),
        "label": result_dir.name,
        "total": len(runs),
        "runs": [],
        "counts": Counter(),
        "reasons": Counter(),
        "model_failure_reasons": Counter(),
        "problems": [],
    }

    if not runs:
        report["verdict"] = "empty"
        report["problems"].append("no run JSONs found")
        return report

    per_task: Counter[tuple[str, str]] = Counter()
    harness_commits: set[str] = set()
    toolchains: set[str] = set()
    providers: set[str] = set()
    efforts: set[str] = set()

    for path, data in runs:
        if "_unreadable" in data:
            entry = {
                "file": str(path), "verdict": "invalid",
                "invalid_reasons": [f"unreadable_json: {data['_unreadable']}"],
                "model_failure_reasons": [],
                "partial_reasons": [],
            }
        else:
            entry = {"file": str(path), **classify_run(data)}
            per_task[(data.get("stack", "?"), data.get("task", "?"))] += 1
            prov = data.get("provenance")
            if isinstance(prov, dict):
                commit = (prov.get("harness") or {}).get("commit")
                if commit:
                    harness_commits.add(
                        f"{commit}-dirty" if (prov.get("harness") or {}).get("dirty") else commit
                    )
                fp = toolchain_fingerprint(prov.get("toolchain") or {})
                if fp:
                    toolchains.add(fp)
                if prov.get("provider"):
                    providers.add(str(prov["provider"]))
                efforts.add(str(prov.get("reasoning_effort")))
            else:
                efforts.add(str(data.get("reasoning_effort")))
        report["runs"].append(entry)
        report["counts"][entry["verdict"]] += 1
        for reason in entry["invalid_reasons"] + entry["partial_reasons"]:
            report["reasons"][reason.split(":", 1)[0]] += 1
        for reason in entry.get("model_failure_reasons") or []:
            report["model_failure_reasons"][reason.split(":", 1)[0]] += 1

    total = len(runs)
    rejected = report["counts"]["invalid"]
    model_failures = report["counts"]["model-failure"]
    errored = report["reasons"].get("runner_error", 0)

    report["rejected"] = rejected
    report["reject_share"] = rejected / total
    report["model_failures"] = model_failures
    report["model_failure_share"] = model_failures / total
    report["errored"] = errored
    report["error_share"] = errored / total
    report["harness_commits"] = sorted(harness_commits)
    report["toolchains"] = sorted(toolchains)
    report["providers"] = sorted(providers)
    report["efforts"] = sorted(efforts)

    if report["error_share"] > CRASH_LIMIT:
        report["problems"].append(
            f"{errored} of {total} runs died in the harness "
            f"({report['error_share']:.0%} > {CRASH_LIMIT:.0%}) — a rate over "
            "the survivors is not a rate over the run set"
        )
    if report["reject_share"] > REJECT_LIMIT:
        report["problems"].append(
            f"{rejected} of {total} runs were harness-rejected "
            f"({report['reject_share']:.0%} > {REJECT_LIMIT:.0%}) — the harness "
            "failed to capture a completion this often, so the set describes "
            "the harness, not the model; re-run it, do not publish it"
        )
    # Model failures are never a problem entry. They are the result.
    if model_failures:
        report["notes"] = report.get("notes", []) + [
            f"{model_failures} of {total} runs are model failures "
            f"({report['model_failure_share']:.0%}) — the model produced nothing "
            "usable. These score 0 and stay in the denominator; they do not "
            "make the set unpublishable (#69)."
        ]

    # Run-count homogeneity, ported from chant-bench's trial-count check: a
    # task run 1 time sitting beside tasks run 3 times is not the same
    # experiment, and averaging them hides it.
    if per_task:
        usual = Counter(per_task.values()).most_common(1)[0][0]
        odd = {f"{s}/{t}": n for (s, t), n in sorted(per_task.items()) if n != usual}
        report["runs_per_task"] = usual
        if odd:
            report["problems"].append(
                f"uneven k: {odd} where every other task ran {usual} time(s) — "
                "not the same experiment, so they cannot be averaged together"
            )

    # Internal provenance consistency: one set must be one experiment.
    if len(harness_commits) > 1:
        report["problems"].append(
            f"mixed harness commits within one set: {', '.join(sorted(harness_commits))}"
        )
    if len(toolchains) > 1:
        report["problems"].append(
            f"mixed toolchain versions within one set ({len(toolchains)} distinct "
            "fingerprints) — the runs were produced against different binaries"
        )
    if len(providers) > 1:
        report["problems"].append(
            f"mixed providers within one set: {', '.join(sorted(providers))}"
        )

    # A set full of model failures is publishable — it is a real result about
    # a weak model — so `model-failure` runs never push the set verdict past
    # `partial`. Only harness problems refuse a set.
    report["verdict"] = (
        "refused" if report["problems"]
        else "partial" if report["counts"]["partial"]
        else "valid"
    )
    return report


def format_set_report(report: dict[str, Any], verbose: bool = False) -> str:
    """Render one set's classification.

    The two failure counts get their own lines and are never summed into one
    (#69): `harness-rejected` runs left the set entirely, `empty answers`
    scored 0 inside it. A single "rejected: N" line cannot say which happened,
    and the difference is the whole point.
    """
    label = report["label"]
    counts = report["counts"]
    lines = [
        f"{label}: {report['total']} run(s) — "
        f"{counts.get('valid', 0)} valid, {counts.get('partial', 0)} partial",
        f"    harness-rejected: {counts.get('invalid', 0)}  "
        "(excluded — the harness captured no completion)",
        f"    empty answers:    {counts.get('model-failure', 0)}  "
        "(scored 0, kept in the denominator)",
    ]
    for reason, n in sorted(report["reasons"].items(), key=lambda kv: -kv[1]):
        lines.append(f"    {n:>4}  {reason}")
    for reason, n in sorted(report.get("model_failure_reasons", {}).items(), key=lambda kv: -kv[1]):
        lines.append(f"    {n:>4}  {reason}  [model failure]")
    for problem in report["problems"]:
        lines.append(f"  REFUSED: {problem}")
    for note in report.get("notes", []):
        lines.append(f"  NOTE: {note}")
    if verbose:
        for entry in report["runs"]:
            if entry["verdict"] == "valid":
                continue
            lines.append(f"  [{entry['verdict']}] {entry['file']}")
            for reason in (
                entry["invalid_reasons"]
                + (entry.get("model_failure_reasons") or [])
                + entry["partial_reasons"]
            ):
                lines.append(f"      {reason}")
    lines.append(f"  -> {report['verdict'].upper()}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# Comparability
# ──────────────────────────────────────────────────────────────────────────

def comparability(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Can these result sets sit in one table?

    chant-bench's rule: two runs are comparable when they share a harness
    commit and a briefing SHA — different either, different experiment. Here
    the axes are harness commit, toolchain fingerprint, provider and reasoning
    effort. The model is deliberately not an axis: differing models is what a
    comparison is *for*.

    A set with no provenance at all cannot be shown to differ, which is not
    the same as being shown to match — those are reported as unverifiable
    rather than as agreement.
    """
    axes = {
        "harness commit": "harness_commits",
        "toolchain": "toolchains",
        "provider": "providers",
        "reasoning effort": "efforts",
    }
    conflicts: list[str] = []
    unverifiable: list[str] = []

    for label, key in axes.items():
        observed = {r["label"]: r.get(key) or [] for r in reports}
        missing = [name for name, vals in observed.items() if not vals]
        distinct = {v for vals in observed.values() for v in vals}
        if missing and key != "efforts":
            unverifiable.append(
                f"{label}: not recorded for {', '.join(sorted(missing))}"
            )
        if len(distinct) > 1:
            detail = "; ".join(
                f"{name}={', '.join(vals) or '?'}" for name, vals in sorted(observed.items())
            )
            conflicts.append(f"{label} differs across sets ({detail})")

    return {
        "comparable": not conflicts,
        "conflicts": conflicts,
        "unverifiable": unverifiable,
    }


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate benchmark result sets before anything quotes them",
    )
    parser.add_argument("dirs", nargs="+", metavar="DIR", help="Result-set directories")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="List every non-valid run with its reasons")
    parser.add_argument("--json", action="store_true", help="Emit the reports as JSON")
    parser.add_argument("--allow-rejected", action="store_true",
                        help="Exit 0 even when a set is refused (inspection only)")
    args = parser.parse_args(argv)

    reports = [
        validate_result_set(Path(d)) for d in args.dirs if Path(d).is_dir()
    ]
    if not reports:
        print("no result-set directories found", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(
            [{**r, "counts": dict(r["counts"]), "reasons": dict(r["reasons"])} for r in reports],
            indent=2, default=str,
        ))
    else:
        for report in reports:
            print(format_set_report(report, verbose=args.verbose))
            print()
        if len(reports) > 1:
            comp = comparability(reports)
            print("Comparability across these sets:")
            for note in comp["conflicts"]:
                print(f"  CONFLICT: {note}")
            for note in comp["unverifiable"]:
                print(f"  UNVERIFIABLE: {note}")
            if comp["comparable"] and not comp["unverifiable"]:
                print("  every axis agrees; these sets are the same experiment")
            print()

        ok = sum(1 for r in reports if r["verdict"] != "refused")
        print(f"{ok}/{len(reports)} result set(s) publishable")

    refused = any(r["verdict"] == "refused" for r in reports)
    return 1 if refused and not args.allow_rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
