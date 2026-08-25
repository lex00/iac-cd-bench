"""
Generate markdown report from benchmark results.
Produces a stack x archetype matrix with per-model scores.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from bench import validate as validate_mod
from bench.score import (
    apply_validity,
    compute_score,
    judge_metadata,
    load_result_set,
    load_results,
)

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"

STACKS = ["knr-ops", "crossplane", "terraform", "pulumi-python", "pulumi-typescript", "chant", "bare"]
ARCHETYPES = ["comprehend", "generate", "modify", "debug", "review", "semantics"]
ARCHETYPE_LABELS = {
    "comprehend": "Comprehend",
    "generate": "Generate",
    "modify": "Modify",
    "debug": "Debug",
    "review": "Review",
    "semantics": "Semantics",
}


def partition_by_validity(
    results: list[dict], spec_lookup: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Split runs into (scored, harness_rejected).

    A HARNESS-rejected run gets no number at all — not a low one, not a
    caveated one. That is chant-bench's hardest-won rule: terraform-m1
    published 1.000 next to an `invalid` badge after losing 22 of 24 trials,
    and the badge lost to the number. Averaging such a run in, even flagged,
    reproduces exactly that.

    A model-failure run is NOT rejected (#69). It stays in `scored`, carrying
    the 0.0 composite `bench.score.score_run` gave it, because a model that
    answered nothing was measured — excluding it would let a model shrink its
    own denominator to the runs it happened to answer. Callers separate the
    two with `model_failures()`.
    """
    scored: list[dict] = []
    rejected: list[dict] = []
    for r in results:
        classification = validate_mod.classify_run(r) if spec_lookup else {"verdict": "valid"}
        r["_integrity"] = classification
        (rejected if classification["verdict"] == "invalid" else scored).append(r)
    return scored, rejected


def model_failures(scored: list[dict]) -> list[dict]:
    """The runs inside `scored` where the model produced nothing usable."""
    return [r for r in scored if (r.get("_integrity") or {}).get("verdict") == "model-failure"]


def _zero_model_failures(scored: list[dict]) -> None:
    """Force every model-failure run in `scored` to a 0.0 composite.

    `load_result_set` already does this, but a caller that scored its runs with
    bare `compute_score` (tests, ad-hoc tooling) would otherwise average a
    vacuous stage pass into a cell. Applied here so no path through this module
    can report a model failure as anything but a failure.
    """
    for r in model_failures(scored):
        # `_integrity` is classify_run's verdict, the downstream source of
        # truth — pass it rather than let apply_validity re-derive from the
        # completion alone, which cannot see the task spec.
        r["score"] = apply_validity(r, r.get("score") or compute_score(r), r["_integrity"])
        r["_model_failure"] = True


def _reason_table(runs: list[dict], key: str, header: str) -> list[str]:
    reasons: Counter[str] = Counter()
    for r in runs:
        for reason in r["_integrity"].get(key) or []:
            reasons[reason.split(":", 1)[0]] += 1
    if not reasons:
        return []
    return (
        ["", f"| {header} | Runs |", "| --- | --- |"]
        + [f"| `{k}` | {v} |" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])]
    )


def integrity_section(label: str, scored: list[dict], rejected: list[dict]) -> list[str]:
    """The failure block every report opens with.

    `harness-rejected` and `empty answers` are separate lines with separate
    reason tables and are never added together (#69). One means the harness
    lost the completion and the run left the denominator; the other means the
    model produced nothing and scored 0 inside it. Collapsing them into a
    single "rejected: N" is the bug — it makes a model that answers nothing
    look like a model with a flaky harness, and hands it a smaller denominator
    as a reward.
    """
    failures = model_failures(scored)
    total = len(scored) + len(rejected)
    lines = [
        "## Result Integrity",
        "",
        f"- runs: **{total}**",
        f"- scored: **{len(scored)}**  — the denominator of every number below",
        f"- **harness-rejected: {len(rejected)}**"
        + ("" if not rejected else "  — excluded from every number below; the "
                                   "harness captured no completion, so nothing "
                                   "about the model was measured"),
        f"- **empty answers: {len(failures)}**"
        + ("" if not failures else "  — scored 0 and KEPT in the denominator; "
                                   "the harness worked and the model produced "
                                   "nothing usable"),
    ]
    lines += _reason_table(rejected, "invalid_reasons", "Harness-rejection reason")
    if rejected:
        lines += [
            "",
            "> A harness-rejected run did not measure the model: tool-call "
            "markup leaked into the completion, the adapter errored, or a "
            "stage's binary was absent while the stage recorded a pass. Such a "
            "run is re-run, not reported. "
            f"`python3 -m bench.validate results/{label} --verbose` lists them.",
        ]
    lines += _reason_table(failures, "model_failure_reasons", "Empty-answer reason")
    if failures:
        lines += [
            "",
            "> An empty answer IS a measurement, and the worst one: the harness "
            "delivered the prompt and captured the reply, and the reply was "
            "unusable. These score 0 on every axis and stay in the denominator, "
            "so a model cannot raise its average by answering nothing.",
        ]
    partial = [r for r in scored if r["_integrity"]["verdict"] == "partial"]
    if partial:
        lines += [
            "",
            f"- partial provenance: **{len(partial)}** run(s) carry incomplete "
            "provenance (no harness commit, prompt hash or toolchain versions) "
            "and cannot be compared against another result set.",
        ]
    lines.append("")
    return lines


def generate_report(model: str, results: list[dict]) -> str:
    """Generate markdown report from results.

    Harness-rejected runs are partitioned out before anything is averaged;
    model-failure runs stay in at 0.0. Both counts are stated above the matrix
    rather than in a footnote.
    """
    results, rejected = partition_by_validity(results)
    _zero_model_failures(results)
    lines = [
        f"# Benchmark Report: {model}",
        "",
        *integrity_section(model.replace("/", "-"), results, rejected),
        "## Stack × Archetype Matrix",
        "",
        "Each cell shows: **pass@1 / pass@k / avg composite score**",
        "",
        "| Stack | " + " | ".join(ARCHETYPE_LABELS[a] for a in ARCHETYPES) + " | Average |",
        "| " + " | ".join(["---"] * (len(ARCHETYPES) + 2)) + " |",
    ]

    matrix = {}
    for stack in STACKS:
        for arch in ARCHETYPES:
            matrix[(stack, arch)] = {"runs": [], "tasks": []}

    # Populate matrix (valid runs only — see docstring)
    for result in results:
        stack = result.get("stack", "")
        task = result.get("task", "")
        score = result.get("score", {})
        composite = score.get("composite", 0)
        # A model failure never passes, whatever its stage flags recorded — an
        # empty completion routinely collects a vacuous "no YAML to lint" pass.
        passed = not result.get("_model_failure") and all(
            result.get("stages", {}).get(s, {}).get("passed", False)
            for s in ("lint", "static")
        )

        for arch in ARCHETYPES:
            key = (stack, arch)
            if arch in task.lower():
                matrix[key]["runs"].append({
                    "passed": passed,
                    "composite": composite,
                })

    # Render rows
    for stack in STACKS:
        row = [stack]
        stack_composites = []
        for arch in ARCHETYPES:
            key = (stack, arch)
            runs = matrix[key]["runs"]
            if runs:
                pass_at_1 = sum(1 for r in runs if r["passed"]) / len(runs)
                pass_at_k = 1.0 if any(r["passed"] for r in runs) else 0.0
                avg_comp = sum(r["composite"] for r in runs) / len(runs)
                cell = f"{pass_at_1:.0%} / {pass_at_k:.0%} / {avg_comp:.2f}"
                stack_composites.append(avg_comp)
            else:
                cell = "—"
                stack_composites.append(0)
            row.append(cell)
        stack_avg = sum(stack_composites) / len(stack_composites) if stack_composites else 0
        row.append(f"{stack_avg:.2f}")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")

    # knr-ops cold vs warm delta (if cold runs exist)
    cold_results = [r for r in results if r.get("condition") == "cold"]
    warm_results = [r for r in results if r.get("condition") == "warm"]
    if cold_results and warm_results:
        lines.append("## knr-ops Cold vs Warm Delta")
        lines.append("")
        lines.append("| Task | Cold pass@1 | Warm pass@1 | Delta |")
        lines.append("| --- | --- | --- | --- |")

        cold_by_task = {}
        warm_by_task = {}
        for r in cold_results:
            t = r.get("task", "")
            cold_by_task.setdefault(t, []).append(r)
        for r in warm_results:
            t = r.get("task", "")
            warm_by_task.setdefault(t, []).append(r)

        for task_id in cold_by_task:
            if task_id not in warm_by_task:
                continue
            cold_pass = sum(1 for r in cold_by_task[task_id] if r.get("stages", {}).get("lint", {}).get("passed")) / len(cold_by_task[task_id])
            warm_pass = sum(1 for r in warm_by_task[task_id] if r.get("stages", {}).get("lint", {}).get("passed")) / len(warm_by_task[task_id])
            delta = warm_pass - cold_pass
            lines.append(f"| {task_id} | {cold_pass:.0%} | {warm_pass:.0%} | {delta:+.0%} |")

        lines.append("")
        lines.append("> **Cold/warm delta measures how much in-context documentation** knr-ops needs to match training-data-driven stacks.")

    # Token usage summary
    lines.append("")
    lines.append("## Token Usage")
    lines.append("")
    total_input = sum(r.get("tokens", {}).get("input", 0) for r in results)
    total_output = sum(r.get("tokens", {}).get("output", 0) for r in results)
    lines.append(f"- Input tokens: {total_input:,}")
    lines.append(f"- Output tokens: {total_output:,}")
    lines.append(f"- Total: {total_input + total_output:,}")
    lines.append(
        f"- Runs scored: {len(results)} "
        f"(harness-rejected: {len(rejected)}; empty answers: {len(model_failures(results))})"
    )

    return "\n".join(lines)


def archetype_of(task: str) -> str | None:
    """Map a task id (T1-comprehend) onto its archetype."""
    task = (task or "").lower()
    for arch in ARCHETYPES:
        if arch in task:
            return arch
    return None


def _cell(values: list[float]) -> str:
    return f"{sum(values) / len(values):.2f}" if values else "—"


def comparability_section(dirs: list[Path]) -> tuple[list[str], bool]:
    """Whether these result sets are the same experiment, rendered.

    chant-bench's rule, ported: two runs are comparable when they share a
    harness commit and a briefing SHA — different either, different
    experiment. Here the axes are harness commit, toolchain versions,
    provider and reasoning effort, and a conflict on any of them makes the
    table a category error rather than a comparison. Sets whose provenance
    predates the stamp cannot be shown to differ, which is not the same as
    agreeing, so they are labelled unverifiable.
    """
    reports = [validate_mod.validate_result_set(d) for d in dirs if d.is_dir()]
    comp = validate_mod.comparability(reports)
    lines = ["## Comparability", ""]
    if comp["conflicts"]:
        lines.append("**These result sets are NOT the same experiment.**")
        lines.append("")
        lines += [f"- CONFLICT: {c}" for c in comp["conflicts"]]
    elif comp["unverifiable"]:
        lines.append(
            "**Comparability could not be verified.** These sets predate the "
            "provenance stamp, so nothing proves they were produced by the "
            "same harness against the same tools."
        )
        lines.append("")
        lines += [f"- UNVERIFIABLE: {u}" for u in comp["unverifiable"]]
    else:
        lines.append(
            "Harness commit, toolchain versions, provider and reasoning effort "
            "agree across every set below."
        )
    lines.append("")
    return lines, bool(comp["conflicts"])


def generate_comparison(
    result_sets: list[tuple[str, list[dict]]],
    dirs: list[Path] | None = None,
) -> str:
    """Side-by-side composite scores across result-set directories.

    One column per result set; rows are stacks, then stack × archetype. Cells
    are the mean composite score of the runs in that bucket, or — when the set
    has no runs there. Rejected runs never reach a cell.
    """
    rejected_counts: dict[str, int] = {}
    failure_counts: dict[str, int] = {}
    cleaned: list[tuple[str, list[dict]]] = []
    for label, results in result_sets:
        scored, rejected = partition_by_validity(results)
        _zero_model_failures(scored)
        rejected_counts[label] = len(rejected)
        failure_counts[label] = len(model_failures(scored))
        cleaned.append((label, scored))
    result_sets = cleaned

    labels = [label for label, _ in result_sets]
    header = "| " + " | ".join(["Stack", *labels]) + " |"
    divider = "| " + " | ".join(["---"] * (len(labels) + 1)) + " |"

    # bucket[label][(stack, archetype)] -> [composite, ...]  (already-scored
    # runs only — result_sets was filtered by partition_by_validity above)
    buckets: dict[str, dict[tuple[str, str], list[float]]] = {}
    for label, results in result_sets:
        bucket: dict[tuple[str, str], list[float]] = {}
        for r in results:
            arch = archetype_of(r.get("task", ""))
            if arch is None:
                continue
            composite = r.get("score", {}).get("composite", 0.0)
            bucket.setdefault((r.get("stack", ""), arch), []).append(composite)
        buckets[label] = bucket

    lines = [
        "# Comparative Benchmark Report",
        "",
        f"Comparing {len(result_sets)} result sets: " + ", ".join(f"`{l}`" for l in labels),
        "",
    ]
    if dirs:
        comp_lines, _ = comparability_section(dirs)
        lines += comp_lines
    lines += [
        "## Composite Score by Stack",
        "",
        "Mean composite score across all runs in the stack.",
        "",
        header,
        divider,
    ]

    for stack in STACKS:
        row = [stack]
        for label in labels:
            values = [
                c for (s, _a), cs in buckets[label].items() if s == stack for c in cs
            ]
            row.append(_cell(values))
        lines.append("| " + " | ".join(row) + " |")

    overall = ["**Overall**"]
    for label in labels:
        overall.append(_cell([c for cs in buckets[label].values() for c in cs]))
    lines.append("| " + " | ".join(overall) + " |")

    # Stack × archetype detail
    lines += [
        "",
        "## Composite Score by Stack × Archetype",
        "",
        "| " + " | ".join(["Stack / Archetype", *labels]) + " |",
        divider,
    ]
    for stack in STACKS:
        for arch in ARCHETYPES:
            cells = [_cell(buckets[label].get((stack, arch), [])) for label in labels]
            if all(c == "—" for c in cells):
                continue
            lines.append(
                "| " + " | ".join([f"{stack} / {ARCHETYPE_LABELS[arch]}", *cells]) + " |"
            )

    # Coverage: run counts, rejections, and the judge pinning behind any idiom
    # scores. `rejected` sits beside `scored` rather than under it — a column
    # averaging 39 surviving runs of 90 is a different claim from one
    # averaging 90.
    lines += ["", "## Coverage", "",
              "| Result set | Scored | Harness-rejected | Empty answers | Judged runs "
              "| Judge model | Judge prompt |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for label, results in result_sets:
        judged = [m for r in results if (m := judge_metadata(r))]
        models = sorted({m["judge_model"] for m in judged if m["judge_model"]}) or ["—"]
        prompts = sorted({m["prompt_sha256"] for m in judged if m["prompt_sha256"]}) or ["—"]
        lines.append(
            f"| {label} | {len(results)} | **{rejected_counts.get(label, 0)}** | "
            f"**{failure_counts.get(label, 0)}** | "
            f"{len(judged)} | {', '.join(models)} | {', '.join(prompts)} |"
        )

    lines += [
        "",
        "> Harness-rejected runs contribute to no cell above. A run the harness could",
        "> not capture a completion for did not measure the model, so it has to happen",
        "> again rather than be averaged in.",
        "",
        "> Empty answers DO contribute, at 0.0, and are inside the Scored column. The",
        "> harness worked and the model produced nothing usable, which is a result about",
        "> the model — excluding it would let a model raise its average by answering",
        "> nothing (#69).",
        "",
        "> Runs without a judge verdict score 0.0 on the idiom axis (weight 1 of 9),",
        "> so composites are only strictly comparable between equally judged sets.",
    ]

    return "\n".join(lines)


def collect_result_sets(paths: list[str]) -> list[tuple[str, list[dict]]]:
    """Load each result-set directory, skipping non-directories and empties."""
    result_sets: list[tuple[str, list[dict]]] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_dir():
            continue
        results = load_result_set(path)
        if not results:
            print(f"Skipping {path}: no run JSONs found")
            continue
        result_sets.append((path.name, results))
    return result_sets


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark report")
    parser.add_argument("--model", default=None, help="Model identifier")
    parser.add_argument("--compare", nargs="+", metavar="DIR", default=None,
                        help="Result-set directories to compare side by side "
                             "(e.g. --compare results/claude-opus-5 results/gpt-5.4)")
    parser.add_argument("--output", default=None, help="Output path (default: results/<model>/report.md)")
    parser.add_argument("--allow-incomparable", action="store_true",
                        help="Render a comparison whose result sets disagree on harness "
                             "commit, toolchain versions, provider or effort. Without "
                             "this the comparison is refused, because such a table is a "
                             "category error rather than a comparison.")
    parser.add_argument("--fail-on-rejected", action="store_true",
                        help="Exit non-zero if any run in the reported sets was rejected "
                             "by the validity gates (for CI).")
    args = parser.parse_args()

    if args.compare:
        result_sets = collect_result_sets(args.compare)
        if not result_sets:
            print("No result sets with runs found; nothing to compare")
            return
        dirs = [Path(p) for p in args.compare if Path(p).is_dir()]
        comp_lines, incomparable = comparability_section(dirs)
        if incomparable and not args.allow_incomparable:
            print("\n".join(comp_lines), file=sys.stderr)
            print(
                "Refusing to render a comparison across result sets that are not "
                "the same experiment. Re-run the sets under one harness commit and "
                "toolchain, or pass --allow-incomparable to render it with the "
                "conflicts stated in the report.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        report = generate_comparison(result_sets, dirs=dirs)
        out_path = Path(args.output) if args.output else RESULTS_DIR / "comparison.md"
        rejected_total = sum(
            len(partition_by_validity(rs)[1]) for _label, rs in collect_result_sets(args.compare)
        )
    else:
        if not args.model:
            parser.error("--model is required unless --compare is given")
        results = load_results(RESULTS_DIR, args.model)
        if not results:
            print(f"No results found for model: {args.model}")
            return
        rejected_total = len(partition_by_validity(list(results))[1])
        report = generate_report(args.model, results)
        out_path = (
            Path(args.output) if args.output
            else RESULTS_DIR / args.model.replace("/", "-") / "report.md"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"Wrote report to {out_path}")
    print()
    print(report)

    if args.fail_on_rejected and rejected_total:
        print(
            f"\n--fail-on-rejected: {rejected_total} run(s) were excluded by the "
            "validity gates; re-run them rather than publishing the remainder.",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
