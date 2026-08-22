"""
Generate markdown report from benchmark results.
Produces a stack x archetype matrix with per-model scores.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.score import compute_score, load_results

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"

STACKS = ["knr-ops", "crossplane", "terraform", "pulumi-python", "pulumi-typescript"]
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


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark report")
    parser.add_argument("--model", required=True, help="Model identifier")
    parser.add_argument("--output", default=None, help="Output path (default: results/<model>/report.md)")
    args = parser.parse_args()

    results = load_results(RESULTS_DIR, args.model)
    if not results:
        print(f"No results found for model: {args.model}")
        return

    report = generate_report(args.model, results)

    out_path = Path(args.output) if args.output else RESULTS_DIR / args.model.replace("/", "-") / "report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"Wrote report to {out_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()
