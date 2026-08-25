"""
Run-validity gate (#59).

`ClaudeCliAdapter` shells out to `claude --print`, which runs Claude Code
itself. Even with tools disabled (`--tools ""`), models reliably reached for
the agentic framing baked into Claude Code's *default* system prompt instead
of answering: narrating an intent to explore the workspace, emitting
Claude-Code-specific tool-call markup for tools that were never wired up, or
stalling out asking for files/tool access instead of using what the prompt
already gave them. Since `--print` returns only the model's first turn as
`result`, that preamble (or a full but still-agentic transcript, sometimes
tens of thousands of characters of simulated `Read`/`Edit`/`Glob` calls) *is*
the run's entire recorded output.

This module classifies a run's `content` as valid or invalid by inspecting
it for that contamination, in the "chant-bench spirit": a run the gates
reject is recorded with a reason and excluded from scoring, never scored as
a failure and never silently dropped.

Calibration (from the 144-run #40 result set, `results/claude-*-3arm/`,
committed as provenance in the same commit as this module — see
`tools/classify_run_validity.py`):

- STRONG signals are literal leakage of Claude Code's own agent machinery
  into the answer text: tool-invocation markup (`<invoke name=...>`,
  `**Bash**`/`**Tool call: Bash**`, a `- Bash (...)` list-style tool call),
  the `★ Insight` UI divider, or a real filesystem path under this machine's
  `.claude/worktrees/agent-*` (the workspace a run is answered from is an
  isolated tempdir - a real worktree path can only appear if the model
  actually saw its own host environment). These never appear in a genuine
  prose/code answer, so they invalidate a run at any length - some
  contaminated transcripts ran to 50,000+ characters of simulated tool use
  and would pass a pure length check easily.
- WEAK signals are exploration/refusal phrasing ("I'll start by exploring",
  "I don't see the actual diff", "could you provide...") that also shows up,
  rarely, as an aside inside otherwise-complete answers. Those only
  invalidate a run when the run is ALSO short (< WEAK_PATTERN_FLOOR chars) -
  long answers that mention "let me check" once in passing are not stubs.
- An absolute floor (ABSOLUTE_FLOOR) rejects near-empty content outright,
  regardless of pattern match.

WEAK_PATTERN_FLOOR is set below the shortest genuine answer this dataset
produced for a non-quiz task and comfortably below the observed valid-run
median (~2500-3500 chars per arm), while staying above every confirmed stub
in the calibration set. T6-semantics (a short JSON-quiz task) has genuine
full answers as short as ~450 chars; because those carry no WEAK pattern
match, they clear the gate untouched by the floor. Recorded stubs in the
calibration set topped out at 996 chars.
"""

from __future__ import annotations

import re
from typing import Any

# Below this many (stripped) characters, content is invalid regardless of
# pattern match - there is no legitimate task answer this short.
ABSOLUTE_FLOOR = 50

# WEAK patterns only invalidate a run when content is also under this floor.
# Calibrated between the longest confirmed stub (996 chars, a "please share
# the diff" refusal) and the shortest genuine non-quiz answer in the
# calibration set (~1600+ chars); T6-semantics quiz answers run shorter but
# never trip a WEAK pattern, so they are unaffected by this floor.
WEAK_PATTERN_FLOOR = 1500

# Claude Code's own agent/tool-call machinery leaking into what should be a
# single-turn completion. Any of these invalidates a run at any length.
STRONG_PATTERNS: list[tuple[str, str]] = [
    (r"<invoke\s+name=", "tool_invocation_markup"),
    (r"</invoke>", "tool_invocation_markup"),
    (r"<parameter\s+name=", "tool_invocation_markup"),
    (r"\*\*(?:Tool call:\s*)?Bash\*\*", "tool_invocation_markup"),
    (r"★\s*Insight", "claude_code_ui_marker"),
    (r"^\s*-\s*Bash\s*\(", "tool_invocation_markup"),
    (r"\.claude/worktrees/agent-", "leaked_host_worktree_path"),
]
_STRONG_RE = re.compile(
    "|".join(f"(?P<p{i}>{pat})" for i, (pat, _label) in enumerate(STRONG_PATTERNS)),
    re.IGNORECASE | re.MULTILINE,
)


def _strong_reason(content: str) -> str | None:
    m = _STRONG_RE.search(content)
    if not m or m.lastgroup is None:
        return None
    idx = int(m.lastgroup[1:])  # named group "p{i}" -> i
    return STRONG_PATTERNS[idx][1]


# Exploration-intent or clarifying-refusal phrasing: a model reaching for
# tools it doesn't have, or asking for inputs it was already given (the
# prompt describes the diff/scenario inline; it never withholds it pending a
# follow-up). Only disqualifying when the run is also short - see module
# docstring.
_WEAK_RE = re.compile(
    r"\bi'?ll (?:start by |first )?(?:look|examine|explore|survey|check)\b|"
    r"\blet me (?:first )?(?:check|try|start)\b|"
    r"\bi (?:don't|do not) see the actual\b|"
    r"\bi need to see the actual\b|"
    r"\bcould you (?:please )?provide\b|"
    r"\bcan you provide\b|"
    r"\bonce you (?:share|provide)\b",
    re.IGNORECASE,
)


def check_validity(content: str | None) -> dict[str, Any]:
    """Classify one run's model output. Returns {"valid": bool, "reason": str|None}.

    `reason` is always populated when `valid` is False, and always None when
    `valid` is True - callers should treat that as the contract, not guess.
    """
    text = content or ""
    stripped = text.strip()

    if len(stripped) < ABSOLUTE_FLOOR:
        return {"valid": False, "reason": "empty_or_near_empty", "content_length": len(stripped)}

    strong = _strong_reason(text)
    if strong is not None:
        return {"valid": False, "reason": strong, "content_length": len(stripped)}

    if len(stripped) < WEAK_PATTERN_FLOOR and _WEAK_RE.search(text):
        return {"valid": False, "reason": "short_stub", "content_length": len(stripped)}

    return {"valid": True, "reason": None, "content_length": len(stripped)}


def check_run_validity(result: dict[str, Any]) -> dict[str, Any]:
    """Same as `check_validity`, reading `content` off a run result dict."""
    return check_validity(result.get("content"))


def run_validity(result: dict[str, Any]) -> dict[str, Any]:
    """Validity of an already-scored run, for use by score.py/report.py.

    Prefers a `validity` block the runner already stamped on the run JSON
    (recomputing would be redundant and, in principle, could drift from what
    was actually recorded). Falls back to computing fresh from `content` for
    result sets written before this gate existed - the 144-run #40 set among
    them (see tools/classify_run_validity.py).

    A run with no `content` key at all predates content being recorded, or
    is a synthetic test fixture — it cannot be judged by this gate, so it is
    treated as valid (grandfathered), not silently rejected.
    """
    existing = result.get("validity")
    if isinstance(existing, dict) and "valid" in existing:
        return existing
    if "content" not in result:
        return {"valid": True, "reason": None, "content_length": None}
    return check_validity(result.get("content"))
