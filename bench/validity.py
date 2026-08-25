"""
Run-validity gate: does this completion describe the model answering the task?

Failure mode this closes (issue #59): a provider returned agent-transcript
preambles ("I'll start by reading the manifests...", tool-call narration)
instead of completions, and it did so differentially by arm. Every one of
those runs was *scored* — lint had no YAML to lint, static had nothing to
build, so two of three stages passed and the arm's gate rate went up because
its provider was broken.

The rule ported from chant-bench's postflight audit is that a trial which did
not measure the tool is not a low score, it is not a measurement — so this
module REJECTS rather than scores. bench.runner stamps the verdict onto the
result JSON; bench.validate classifies on it; bench.report gives a rejected
run no number at all (chant-bench's `rate()`: "not a low one, not a caveated
one — none. The badge lost to the number, including with me.")

No network, no subprocess: this is pure text classification over the recorded
completion, so it re-runs identically over historical result JSONs.
"""

from __future__ import annotations

import re
from typing import Any

# Below this many characters the completion cannot contain a usable answer to
# any task in this suite (the shortest golden answer key is ~900 chars). Set
# deliberately low: this is a floor for "the provider returned nothing usable",
# not a quality bar.
MIN_CONTENT_CHARS = 200

# Structural markers: these appear only in an agent transcript, never in a
# completion. A single hit is decisive.
TRANSCRIPT_STRUCTURAL = [
    (re.compile(r"<function_calls>|<invoke\s+name=|<function_results>"), "xml tool-call markup"),
    (re.compile(r"^\s*[⏺●]\s", re.MULTILINE), "Claude Code tool-call bullets"),
    (re.compile(r"\bstr_replace_editor\b|\bTodoWrite\b|\bmulti_tool_use\b"), "tool names in prose"),
    (re.compile(r"^\s*(?:Tool|Function)\s+(?:use|call|result)\s*:", re.MULTILINE), "tool-call transcript header"),
    # First-person future tense naming a tool it is about to call. A model
    # writing an answer recommends a tool ("use kustomize for this"); only an
    # agent transcript says "I'll use the Read tool".
    (re.compile(r"\bI(?:'ll| will)\s+(?:now\s+)?(?:use|call|invoke)\s+the\s+\w+\s+tool\b", re.I), "announces a tool call"),
]

# Narration markers: individually these can appear in a legitimate answer
# ("Let me walk through the composition"), so they only count in aggregate.
TRANSCRIPT_NARRATION = [
    (re.compile(r"^\s*(?:Let me|I'll|I will)\s+(?:start by\s+)?(?:read|check|search|look|explor|examin|inspect)\w*\b", re.I | re.MULTILINE), "announces reading the workspace"),
    (re.compile(r"\bI (?:don't|do not) have (?:access to|any) (?:the )?(?:tools|filesystem|workspace)\b", re.I), "reports missing tool access"),
    (re.compile(r"^\s*(?:Reading|Searching|Editing|Writing|Listing)\s+(?:the\s+)?(?:file|director|workspace)", re.I | re.MULTILINE), "narrates a filesystem action"),
    (re.compile(r"\bI'll (?:begin|get started) by\b", re.I), "agentic preamble"),
]

# Two ways to clear the narration bar, because a transcript gives itself away
# either by variety or by repetition:
#   - two *different* narration markers, or
#   - three narration lines of any kind.
# Neither is one: models legitimately open a review answer with "Let me walk
# through what changed", and a single such line must not void a run that
# otherwise produced real artifacts. Swept against all 1140 historical result
# JSONs, these thresholds flag exactly one run — a genuine #59 preamble
# ("I'll start by exploring the project structure...") — and nothing else.
NARRATION_KINDS_THRESHOLD = 2
NARRATION_LINES_THRESHOLD = 3

FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def _fenced_blocks(content: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in FENCE_RE.finditer(content)]


def check_content(
    content: str | None,
    *,
    expects_artifacts: bool = False,
    extracted_files: list[Any] | None = None,
    min_chars: int = MIN_CONTENT_CHARS,
) -> dict[str, Any]:
    """Classify one completion.

    Args:
        content: the raw completion text the provider returned.
        expects_artifacts: True when the task's spec enables a stage that acts
            on files the model was supposed to produce (lint/static/e2e). For
            such a task a completion with no fenced code block and no extracted
            file is the vacuous-pass generator described in issue #59.
        extracted_files: what bench.runner.extract_code_blocks actually wrote.

    Returns a verdict dict:
        {"verdict": "valid"|"invalid", "reasons": [...], "checks": {...}}
    """
    reasons: list[str] = []
    text = content or ""
    stripped = text.strip()

    blocks = _fenced_blocks(text)
    checks: dict[str, Any] = {
        "content_chars": len(stripped),
        "fenced_blocks": len(blocks),
        "extracted_files": len(extracted_files or []),
        "min_chars": min_chars,
        "expects_artifacts": bool(expects_artifacts),
    }

    if not stripped:
        reasons.append("empty_completion: the provider returned no text at all")
    elif len(stripped) < min_chars:
        reasons.append(
            f"content_too_short: {len(stripped)} chars < {min_chars} floor — "
            "no task in this suite has a usable answer this short"
        )

    structural_hits = [label for rx, label in TRANSCRIPT_STRUCTURAL if rx.search(text)]
    narration_counts = {
        label: len(rx.findall(text))
        for rx, label in TRANSCRIPT_NARRATION
        if rx.search(text)
    }
    checks["transcript_structural"] = structural_hits
    checks["transcript_narration"] = narration_counts

    if structural_hits:
        reasons.append(
            "agent_transcript: completion carries tool-call markup "
            f"({', '.join(structural_hits)}) — the provider returned a "
            "transcript, not an answer (#59)"
        )
    elif (
        len(narration_counts) >= NARRATION_KINDS_THRESHOLD
        or sum(narration_counts.values()) >= NARRATION_LINES_THRESHOLD
    ):
        detail = ", ".join(f"{label} x{n}" for label, n in sorted(narration_counts.items()))
        reasons.append(
            f"agent_transcript: completion narrates agent actions ({detail}) "
            "rather than answering (#59)"
        )

    if expects_artifacts and not blocks and not (extracted_files or []):
        reasons.append(
            "no_extractable_output: the task's enabled stages act on files the "
            "model was to produce, and the completion contains no code block — "
            "lint and static would have nothing to check and would pass vacuously"
        )

    return {
        "verdict": "invalid" if reasons else "valid",
        "reasons": reasons,
        "checks": checks,
    }


def expects_artifacts(spec: dict[str, Any] | None) -> bool:
    """Whether a task's spec enables a stage that acts on model-produced files.

    Mirrors bench.runner._stage_enabled's default-True semantics, so a spec
    without a `stages:` block is treated as expecting artifacts.
    """
    if not spec:
        return True
    stages = spec.get("stages") or {}
    for name in ("lint", "static", "e2e"):
        stage = stages.get(name) or {}
        if bool(stage.get("enabled", True)):
            return True
    return False


def check_result(result: dict[str, Any], spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Re-derive a validity verdict from a stored result JSON.

    Used by bench.validate to classify historical runs written before the gate
    existed, so old result sets get the same verdict a fresh run would.
    """
    return check_content(
        result.get("content"),
        expects_artifacts=expects_artifacts(spec) if spec is not None else False,
        extracted_files=result.get("extracted_files"),
    )
