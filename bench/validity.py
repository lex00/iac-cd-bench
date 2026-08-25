"""
Run-validity gate (#59).

Two independent ports of the same fix landed in parallel (bench/cli-provider-fix
and bench/integrity-gates) and were merged together on bench/run-ready rather
than picking a winner, because each has callers the other doesn't: bench.score
and the older report-generation path read the simple `run_validity`/
`check_validity` shape below; bench.validate, bench.preflight and bench.runner's
gate-refusal path read the richer `check_content`/`check_result` shape further
down. Both are kept; `bench.runner.run_task` stamps a run's `result["validity"]`
with the union of both verdicts (disjoint key sets, so `{**old, **new}` merges
cleanly) so every consumer finds the field it expects.

## Background

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

Both classifiers below reject rather than score contaminated runs, in the
"chant-bench spirit": a run the gates reject is recorded with a reason and
excluded from scoring, never scored as a failure and never silently dropped.

## Part 1: `check_validity` / `check_run_validity` / `run_validity`

Calibrated from the 144-run #40 result set, `results/claude-*-3arm/`,
committed as provenance in the same commit as this module — see
`tools/classify_run_validity.py`.

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

## Part 2: `check_content` / `expects_artifacts` / `check_result`

The rule ported from chant-bench's postflight audit is that a trial which did
not measure the tool is not a low score, it is not a measurement — so this
half REJECTS rather than scores too, but classifies differently: structural
transcript markers (XML tool-call tags, Claude Code's own UI bullets, tool
names appearing in prose) are decisive on their own; narration phrases only
count once they cross a repetition/variety threshold; and a completion with
no fenced code block on a task whose enabled stages act on model-produced
files is flagged as the vacuous-pass generator described in issue #59 (lint
had no YAML to lint, static had nothing to build, so a stub scored 2 of 3).

Two independent classifiers live in this module, both closing issue #59 from
different angles and both kept because different callers need each shape:

- `check_validity`/`check_run_validity`/`run_validity` (above) run pattern
  calibration against the 144-run #40 set and are what `bench.runner` stamps
  onto a result at generation time and what `bench.score`/`bench.report`
  filter on directly.
- `check_content`/`expects_artifacts`/`check_result` (below) are the
  structural/narration classifier `bench.validate.classify_run` (#60) uses to
  re-derive a verdict for historical results and to catch the vacuous-pass
  case where a task expected an artifact and got prose instead.

`bench.validate.classify_run` is the single source of truth downstream: it
prefers a result's already-stamped `validity` block (this module's first
API), and otherwise recomputes with `check_result` (this module's second
API), so the two do not disagree silently — anything either classifier
rejects, `classify_run` rejects.

No network, no subprocess in either half: this is pure text classification
over the recorded completion, so both re-run identically over historical
result JSONs.

## Part 0: the failure taxonomy (#69)

Both classifiers above originally returned one verdict — "invalid" — for two
situations that are not alike, and `bench.score` excluded both from every
aggregate. That is a scoring bug, not a cosmetic one:

- The harness failing to capture a completion means no measurement of the
  model exists. Excluding the run is right; scoring it 0 would charge the
  model for the harness's mistake.
- The model producing nothing usable while the harness worked fine IS a
  measurement, and the worst one a model can produce. Excluding it drops a
  model's worst runs from its own denominator, so a model that answers
  nothing half the time gets averaged over the survivor-biased half it did
  answer. That is the same perverse incentive as the vacuous passes this
  project just removed, arriving through the other door: a free pass became
  a free exclusion.

  Empirically, `qwen 3.8 - local` keeps rank #1 of 13 under blanket exclusion
  because 44 of its 90 runs are dropped rather than counted; zero-filled, it
  is #12. The exclusion is doing the work, not the answers.

So every rejection reason carries a category:

- `HARNESS_INVALID` — the harness failed to capture a completion. Tool-call
  markup and Claude Code UI markers leaking into the answer, a real host
  worktree path (the model saw its own environment), transcript structural
  markers, an adapter/API error or timeout, an unreadable result JSON, and a
  stage recording a pass with its own binary absent. Excluded from every
  aggregate; a high rate of these means the harness is broken and the set is
  unpublishable.
- `MODEL_FAILURE` — the harness worked and the model produced nothing usable.
  An empty or near-empty completion, a short stub, prose where the task's
  enabled stages needed a file. Scored as a failure (correctness 0) and kept
  in the denominator. A high rate of these is a real, publishable result
  about the model, not a broken run set.

A reason this module does not recognise is categorised HARNESS_INVALID, the
conservative direction: charging a model for a failure mode nobody has
classified is the false-accusation error, and excluding an unknown is only
the loss of one data point.

### The ambiguous case: an empty completion that burned its budget on reasoning

`claude-opus-5` produced 31 completions of zero visible characters in the 90-run
historical set, every one of them billed at exactly `max_tokens` (16,384) of
output. Nothing was truncated by the harness and no API error was raised: the
model spent its entire output allowance on reasoning tokens and emitted no
answer.

**This is scored as a MODEL_FAILURE, not as missing data.** The reasoning:
the harness sets a token budget and asks a question; how a model spends that
budget is part of what a benchmark at that configuration measures. A model
that reliably thinks itself past its own output allowance has failed the task
as surely as one that answers wrongly — the user gets nothing either way.
Calling it "not a measurement" would mean a model could raise its average by
thinking longer, which is precisely the incentive #69 exists to close.

The counter-argument is real and is why this is configurable rather than
asserted: the budget is a harness parameter, so one could argue the harness
under-provisioned the model. Set `IAC_BENCH_REASONING_EXHAUSTION=harness-invalid`
to score it that way, and the runs are excluded instead. The distinct
sub-reason `empty_reasoning_exhausted` is recorded either way, so the choice
is always visible in the data and reversible without a re-run.

Detection is deliberately budget-agnostic: a completion under the empty floor
whose provider billed more than `REASONING_EXHAUSTION_OUTPUT_TOKENS` output
tokens spent those tokens somewhere invisible. That holds whatever `max_tokens`
was, and does not fire on the genuinely-terse answers that make up every other
short completion in the corpus (`qwen 3.8 - local`'s stubs bill 43-200 output
tokens, matching their visible length).
"""

from __future__ import annotations

import os
import re
from typing import Any

# ─────────────────────────────────────────────────────────────────────────
# Part 0: the failure taxonomy (#69) — see the module docstring
# ─────────────────────────────────────────────────────────────────────────

#: The harness failed to capture a completion. No measurement of the model
#: exists, so the run is excluded from every aggregate.
HARNESS_INVALID = "harness-invalid"

#: The harness worked; the model produced nothing usable. A measurement, and
#: the worst one available, so the run scores 0 and stays in the denominator.
MODEL_FAILURE = "model-failure"

#: Environment variable overriding how an empty-because-reasoning-exhausted
#: completion is categorised. Accepts either category constant.
REASONING_EXHAUSTION_ENV = "IAC_BENCH_REASONING_EXHAUSTION"

#: Default for that case. See "The ambiguous case" in the module docstring.
REASONING_EXHAUSTION_DEFAULT = MODEL_FAILURE

#: A completion under the empty floor that still billed more than this many
#: output tokens spent them on invisible (reasoning) output rather than on an
#: answer. Set far above the longest genuinely-terse completion in the corpus
#: (200 output tokens) and far below any real reasoning budget.
REASONING_EXHAUSTION_OUTPUT_TOKENS = 1024

#: Sub-reason -> category. Sub-reasons are kept exactly as they were already
#: recorded (#59, #56, #60) so nothing already on disk loses its meaning; the
#: category is the new axis layered over them.
REASON_CATEGORIES: dict[str, str] = {
    # Part 1 (check_validity): Claude Code's own machinery in the answer.
    "tool_invocation_markup": HARNESS_INVALID,
    "claude_code_ui_marker": HARNESS_INVALID,
    "leaked_host_worktree_path": HARNESS_INVALID,
    # Part 1: the model answered, badly or not at all.
    "empty_or_near_empty": MODEL_FAILURE,
    "short_stub": MODEL_FAILURE,
    # Part 2 (check_content).
    "agent_transcript": HARNESS_INVALID,
    "empty_completion": MODEL_FAILURE,
    "content_too_short": MODEL_FAILURE,
    # Prose where the task's enabled stages needed a file: the harness
    # delivered the completion intact, the model just did not produce the
    # artifact. This is the vacuous-pass generator of #59 and it is squarely
    # a model failure.
    "no_extractable_output": MODEL_FAILURE,
    # bench.validate.classify_run's own reasons.
    "runner_error": HARNESS_INVALID,
    "adapter_error": HARNESS_INVALID,
    "api_error": HARNESS_INVALID,
    "timeout": HARNESS_INVALID,
    "unreadable_json": HARNESS_INVALID,
    # The stage's binary was absent from PATH: an infrastructure gap, so
    # nothing about the model was checked (#56).
    "tool_missing_scored_as_pass": HARNESS_INVALID,
    # Every enabled stage had nothing to act on because the model produced no
    # artifact — same family as no_extractable_output, same verdict.
    "all_stages_inapplicable": MODEL_FAILURE,
}


def reasoning_exhaustion_category() -> str:
    """How an empty-because-reasoning-exhausted completion is categorised.

    Read per call rather than at import so a rescore can flip it without
    reloading the module. Anything other than the two category constants is
    ignored in favour of the default, rather than silently creating a third
    category.
    """
    override = (os.environ.get(REASONING_EXHAUSTION_ENV) or "").strip().lower()
    if override in (HARNESS_INVALID, MODEL_FAILURE):
        return override
    return REASONING_EXHAUSTION_DEFAULT


def categorize_reason(reason: str | None) -> str | None:
    """Map one rejection reason (or `reason: detail` string) to a category.

    Unknown reasons categorise as HARNESS_INVALID — see the module docstring
    on why that is the conservative direction.
    """
    if not reason:
        return None
    key = str(reason).split(":", 1)[0].strip()
    if key == "empty_reasoning_exhausted":
        return reasoning_exhaustion_category()
    return REASON_CATEGORIES.get(key, HARNESS_INVALID)


def merge_categories(*categories: str | None) -> str | None:
    """Combine categories for a run with several reasons.

    HARNESS_INVALID wins: if any part of the run shows the harness failed,
    the completion cannot be attributed to the model at all, so the run is
    not evidence about the model even if it also looks empty.
    """
    present = [c for c in categories if c]
    if not present:
        return None
    return HARNESS_INVALID if HARNESS_INVALID in present else MODEL_FAILURE


def categorize_reasons(reasons: list[str] | None) -> str | None:
    return merge_categories(*(categorize_reason(r) for r in (reasons or [])))


def is_harness_invalid(verdict: dict[str, Any] | None) -> bool:
    """Whether a validity block says the harness, not the model, failed."""
    return _category_of(verdict) == HARNESS_INVALID


def is_model_failure(verdict: dict[str, Any] | None) -> bool:
    """Whether a validity block says the model produced nothing usable."""
    return _category_of(verdict) == MODEL_FAILURE


def _category_of(verdict: dict[str, Any] | None) -> str | None:
    """Category of an arbitrary validity block, recomputing if it predates one.

    Result JSONs written before #69 carry reasons but no `category`, so the
    category is re-derived from the reasons rather than defaulting — the
    whole point of keeping the sub-reason strings stable.
    """
    if not isinstance(verdict, dict):
        return None
    stated = verdict.get("category")
    if stated in (HARNESS_INVALID, MODEL_FAILURE):
        return stated
    if verdict.get("reasons"):
        return categorize_reasons(verdict.get("reasons"))
    if verdict.get("valid") is False or verdict.get("verdict") == "invalid":
        return categorize_reason(verdict.get("reason"))
    return None


def _output_tokens(result: dict[str, Any]) -> int | None:
    tokens = result.get("tokens")
    if isinstance(tokens, dict):
        try:
            return int(tokens.get("output"))
        except (TypeError, ValueError):
            return None
    return None


def is_reasoning_exhausted(result: dict[str, Any]) -> bool:
    """Did this run bill a large output budget while emitting no answer?

    True only for the ambiguous case in the module docstring: visible text
    below the empty floor, but the provider charged for output tokens that
    have to have gone into reasoning. A run that errored out is not this
    case — that is a harness failure with its own reason.
    """
    if result.get("error"):
        return False
    if len((result.get("content") or "").strip()) >= ABSOLUTE_FLOOR:
        return False
    out = _output_tokens(result)
    return out is not None and out > REASONING_EXHAUSTION_OUTPUT_TOKENS

# ─────────────────────────────────────────────────────────────────────────
# Part 1: check_validity / check_run_validity / run_validity
# (bench.score.aggregate_scores, the older report-generation helpers)
# ─────────────────────────────────────────────────────────────────────────

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


def _verdict(valid: bool, reason: str | None, length: int) -> dict[str, Any]:
    return {
        "valid": valid,
        "reason": reason,
        "category": categorize_reason(reason) if not valid else None,
        "content_length": length,
    }


def check_validity(content: str | None) -> dict[str, Any]:
    """Classify one run's model output.

    Returns `{"valid": bool, "reason": str|None, "category": str|None,
    "content_length": int}`. `reason` and `category` are always populated when
    `valid` is False and always None when `valid` is True — callers should
    treat that as the contract, not guess.

    Harness markers are tested BEFORE the empty floor (#69). The order used to
    be the other way round, which meant a 40-character completion consisting of
    nothing but leaked tool-call markup was filed as `empty_or_near_empty` — a
    model failure — when it is the clearest possible evidence that the harness,
    not the model, produced the text. Length is only meaningful once the text is
    known to have come from the model.
    """
    text = content or ""
    stripped = text.strip()

    strong = _strong_reason(text)
    if strong is not None:
        return _verdict(False, strong, len(stripped))

    if len(stripped) < ABSOLUTE_FLOOR:
        return _verdict(False, "empty_or_near_empty", len(stripped))

    if len(stripped) < WEAK_PATTERN_FLOOR and _WEAK_RE.search(text):
        return _verdict(False, "short_stub", len(stripped))

    return _verdict(True, None, len(stripped))


def check_run_validity(result: dict[str, Any]) -> dict[str, Any]:
    """Same as `check_validity`, reading `content` off a run result dict.

    Given the whole run rather than just its text, this can also separate the
    ambiguous empty case: a completion that is empty because the model spent
    its output budget on reasoning is recorded under the distinct sub-reason
    `empty_reasoning_exhausted`, whose category is configurable (see the
    module docstring).
    """
    verdict = check_validity(result.get("content"))
    if verdict.get("reason") == "empty_or_near_empty" and is_reasoning_exhausted(result):
        return _verdict(False, "empty_reasoning_exhausted", verdict["content_length"])
    return verdict


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
        if existing.get("valid") or existing.get("category") in (HARNESS_INVALID, MODEL_FAILURE):
            return existing
        # Stamped before #69: keep the recorded verdict and sub-reason exactly
        # as they are, and only add the category the taxonomy now needs.
        return {**existing, "category": _category_of(existing)}
    if "content" not in result:
        return {"valid": True, "reason": None, "category": None, "content_length": None}
    return check_run_validity(result)


# ─────────────────────────────────────────────────────────────────────────
# Part 2: check_content / expects_artifacts / check_result
# (bench.validate, bench.preflight, bench.runner's gate-refusal path)
# ─────────────────────────────────────────────────────────────────────────

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
        {"verdict": "valid"|"invalid", "category": str|None,
         "reasons": [...], "checks": {...}}

    `category` is HARNESS_INVALID when any reason shows the harness failed to
    capture the completion, MODEL_FAILURE when every reason is about what the
    model produced, and None for a valid completion (#69).
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
        "category": categorize_reasons(reasons),
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
    verdict = check_content(
        result.get("content"),
        expects_artifacts=expects_artifacts(spec) if spec is not None else False,
        extracted_files=result.get("extracted_files"),
    )
    # The ambiguous empty case gets its own sub-reason so the choice made
    # about it stays visible in the data (see the module docstring).
    if is_reasoning_exhausted(result):
        verdict["reasons"] = [
            (
                "empty_reasoning_exhausted: the provider returned no text but "
                f"billed {_output_tokens(result)} output tokens — the model spent "
                "its whole output budget on reasoning and emitted no answer"
            )
            if r.startswith("empty_completion")
            else r
            for r in verdict["reasons"]
        ]
        verdict["category"] = categorize_reasons(verdict["reasons"])
    return verdict
