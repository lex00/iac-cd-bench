"""
Generate markdown report from benchmark results.
Produces a stack x archetype matrix with per-model scores.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.score import compute_score, judge_metadata, load_result_set, load_results

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


def generate_report(model: str, results: list[dict]) -> str:
    """Generate markdown report from results."""
    lines = [
        f"# Benchmark Report: {model}",
        "",
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

    # Populate matrix
    for result in results:
        stack = result.get("stack", "")
        task = result.get("task", "")
        score = result.get("score", {})
        composite = score.get("composite", 0)
        passed = all(
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
    lines.append(f"- Runs: {len(results)}")

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


def generate_comparison(result_sets: list[tuple[str, list[dict]]]) -> str:
    """Side-by-side composite scores across result-set directories.

    One column per result set; rows are stacks, then stack × archetype. Cells
    are the mean composite score of the runs in that bucket, or — when the set
    has no runs there.
    """
    labels = [label for label, _ in result_sets]
    header = "| " + " | ".join(["Stack", *labels]) + " |"
    divider = "| " + " | ".join(["---"] * (len(labels) + 1)) + " |"

    # bucket[label][(stack, archetype)] -> [composite, ...]
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

    # Coverage: run counts and the judge pinning behind any idiom scores
    lines += ["", "## Coverage", "", "| Result set | Runs | Judged runs | Judge model | Judge prompt |",
              "| --- | --- | --- | --- | --- |"]
    for label, results in result_sets:
        judged = [m for r in results if (m := judge_metadata(r))]
        models = sorted({m["judge_model"] for m in judged if m["judge_model"]}) or ["—"]
        prompts = sorted({m["prompt_sha256"] for m in judged if m["prompt_sha256"]}) or ["—"]
        lines.append(
            f"| {label} | {len(results)} | {len(judged)} | "
            f"{', '.join(models)} | {', '.join(prompts)} |"
        )

    lines += [
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
    args = parser.parse_args()

    if args.compare:
        result_sets = collect_result_sets(args.compare)
        if not result_sets:
            print("No result sets with runs found; nothing to compare")
            return
        report = generate_comparison(result_sets)
        out_path = Path(args.output) if args.output else RESULTS_DIR / "comparison.md"
    else:
        if not args.model:
            parser.error("--model is required unless --compare is given")
        results = load_results(RESULTS_DIR, args.model)
        if not results:
            print(f"No results found for model: {args.model}")
            return
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


if __name__ == "__main__":
    main()
