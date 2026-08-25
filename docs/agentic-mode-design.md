# Agentic runner mode — design

Epic: [lex00/iac-cd-bench#8](https://github.com/lex00/iac-cd-bench/issues/8).
Status: design only. Nothing here is built; building is gated on owner approval
of the decisions at the end of this document.

## The question this mode exists to answer

The upstream bench author's comment on #8 states a hypothesis worth testing
rather than assuming: stacks with cheap local validation give an agent a
tighter feedback loop than stacks whose validation is a plan-and-state round
trip. `kustomize build` and `flux build kustomization --dry-run` are sub-second
and offline. `chant lint` and `chant build` are the same shape. `terraform
plan` needs `terraform init` and a provider download; `pulumi preview` needs a
stack and a backend. If the hypothesis holds, the ranking of stacks under an
agentic runner should differ from the ranking under the current one-shot
runner, and the difference should be explained by how often each arm's agent
actually ran its local check and how early it first got a green one.

That framing sets the measurement requirement up front. A mode that only
reports final gate pass rates cannot distinguish "chant won because the
language is easier to write" from "chant won because the agent could check
itself twelve times in ninety seconds." So the instrumentation below treats
validation-loop usage as a first-class output, on equal footing with the stage
gates, and every metric it collects is chosen because it discriminates between
those two explanations.

The secondary caution from the same comment: reasoning effort must be pinned
per arm. An agentic loop multiplies the effect of an unpinned effort setting,
because effort influences both the quality of each edit and the willingness to
spend turns iterating. Section "Effort pinning" covers this, and the prior art
makes the caution concrete — see the finding immediately below.

## What chant-bench actually does, and where #8's premise needs adjusting

Issue #8 describes chant-bench as agentic with "three attempts per question."
Reading the harness changes that picture in one important way, and the design
below is built on the corrected version.

First, the harness is not in `chant-bench` at all. That repo is the
publication half — `scripts/`, `results/`, `transcripts/`, `briefings/`, a
`justfile`, and mkdocs pages. `scripts/bootstrap.sh` clones
`github.com/lex00/aws-bench` into a sibling directory, and that repo (plus a
generic trial runner called Harbor, vendored into its virtualenv) owns the
container, the agent adapter, and the scored invocation.

Second, and this is the correction that matters: **chant-bench does not run a
validation loop.** `-k 3` means three *independent* trials of the same
question, each in its own fresh Docker compose project with its own fresh
`claude --print` session. There is no in-trial retry, no self-correction step,
and `jobs/chant-h3/config.json` shows `retry.max_retries: 0` with the relevant
exception classes excluded anyway. Every metric chant-bench publishes about
agent behavior is derived post-hoc by parsing the agent's own stream-json log.
The design is deliberately one-shot-per-trial with rich instrumentation.

That is not a flaw in chant-bench — its questions are read-only estate
queries, so there is nothing to iterate toward. But it means iac-cd-bench
cannot copy a validation loop from chant-bench, because chant-bench does not
have one. This design has to build the loop, and what it borrows from
chant-bench is the *measurement discipline*: the result schema, the gate
structure, the briefing-hash comparability rule, and a set of hard-won lessons
about how agentic benchmark numbers go wrong.

Third, on effort pinning: chant-bench's Claude Code invocation is

```
claude --verbose --output-format=stream-json --permission-mode=bypassPermissions
  --print -- <instruction> 2>&1 </dev/null | tee /logs/agent/claude-code.txt
```

with no `--effort`, no `--max-turns`, no `--allowedTools`, and no
`MAX_THINKING_TOKENS`. Harbor's adapter supports every one of those as an
optional kwarg (`/agents/installed/claude_code.py`, `CLI_FLAGS`); the harness
sets none of them. Only the model id is pinned, via `ANTHROPIC_MODEL`. So the
author's effort-pinning caution is not a hypothetical worry about someone
else's benchmark — it is an unfixed gap in the closest prior art, and this
design should not repeat it.

Fourth, chant-bench's sandboxing is worth understanding precisely because this
design departs from it. Isolation is the container and nothing else: permissions
are fully open inside (`bypassPermissions`, `IS_SANDBOX=1`, no tool allowlist,
no hooks), the container has unrestricted outbound network, and cloud isolation
is achieved by pointing `AWS_ENDPOINT_URL` at a local emulator with fake
credentials rather than by any network policy. The per-arm "allowlist" is not
enforced at runtime at all — it is a regex in `aws-bench:benchmarks/agent-env/arms.py`
(chant's is `\bchant\s+(search|graph|lifecycle)\b`) applied *after* the run by
`audit.py` and `emit-result.py`. Whether iac-cd-bench should enforce up front
or audit after the fact is an open decision.

## What exists today in this repo

`bench/runner.py` is one-shot end to end. `run_task()` (line 402) loops `k`
times; each iteration makes a fresh `tempfile.mkdtemp()` workspace,
`materialize_task()` (line 118) copies `seed/` into it and, for the warm
condition, `docs/` into `context/`, then a single `adapter.complete(prompt,
workspace_files)` call returns markdown. `extract_code_blocks()` (line 35)
parses fenced blocks out of that markdown and writes them into the workspace
with per-stack filtering, and only then do the four stages run: `lint.run_lint`,
`static.run_static`, `semantic.run_semantic`, and optionally `e2e.run_e2e`.

Two properties of that flow matter here. First, the model never sees a stage
result — validation happens strictly after the model is done, so the current
runner measures one-shot authoring, not iterative authoring. Second, the stages
already encapsulate exactly the per-stack local commands an agent would want to
run. `bench/stages/lint.py` holds `LINT_COMMANDS`, a dict keyed by stack;
`bench/stages/static.py` holds one `_<stack>_static()` function per stack. The
agentic mode does not need to invent a command vocabulary; it needs to expose
the one that already exists.

The adapters are thin HTTP clients. `AnthropicAdapter` (line 174) posts to
`/v1/messages` with a single user message and no `tools` key.
`OpenAICompatAdapter` (line 278) posts a single user message to
`/chat/completions`. Neither has any notion of a multi-turn conversation, tool
results, or a transcript. Both carry a `reasoning_effort` attribute and
translate it per model family — adaptive `output_config.effort` for
`claude-opus-5*` and `claude-opus-4-8`, legacy `thinking.budget_tokens` for
older Anthropic reasoning models, `reasoning_effort` for gpt-5, kimi, qwen, and
GLM. Both retry ten times on 429/529/5xx and transport errors.

Results land at `results/<model>[-<results-tag>]/<stack>/<condition>/<task>_run<N>.json`
(`main()`, line 566), each carrying `model`, `task`, `stack`, `run`,
`condition`, `stages`, `tokens`, `content`, and — once #50 merges —
`reasoning_effort`. `bench/score.py` computes a weighted composite from the
stage gates; `bench/report.py` renders a stack-by-archetype matrix.

Seven stacks are in flight: five on `main` (knr-ops, crossplane, terraform,
pulumi-python, pulumi-typescript), chant on `bench/chant-wiring` (PR #41), and
bare on `bench/bare-wiring` (PR #46). This design assumes all seven, because
the comparison the epic cares about — chant versus knr-ops versus bare —
requires them.

One piece of gate machinery already exists and should be reused rather than
reinvented: PR #41 adds `e2e.preflight_chant_golden()`, which asserts
`golden-base/chant` passes lint and static before any model run burns tokens on
chant tasks. Its docstring credits chant-bench for the idea, and it is the
direct analogue of `aws-bench`'s `preflight.py`. Agentic mode should run the
same preflight for every arm, not just chant.

## Loop architecture

### External driver versus in-adapter loop

chant-bench drives an agent externally, shelling out to the Claude Code CLI
(`agent: {"name": "claude-code", "model": "claude-haiku-4-5-20251001", "k": 3}`
in every result file). Its transcripts record commands as full shell strings —
`cd /workspace/alchemy && alchemy state resources ... | grep -i instance` —
so the agent gets a real shell with pipes and redirection.

That design is right for chant-bench, which compares stacks under one fixed
agent. It is wrong here, because this bench compares *models* across seven
stacks, and a CLI-driver approach binds the harness to whichever vendor ships a
suitable CLI. Half the current result set (`results/gpt-5.4`, `results/glm-5.3`,
`results/qwen 3.8 - local`, `results/kimi-k3`) comes from OpenAI-compatible
endpoints, including a locally hosted vLLM. Those arms have no agent CLI. An
external driver would silently reduce the agentic mode to an Anthropic-only
mode, which destroys the cross-model comparison the bench is for.

So: an in-process tool-execution loop, implemented once against the two
provider protocols the adapters already speak. Anthropic gets `tools` plus
`tool_use`/`tool_result` blocks; OpenAI-compatible gets `tools` with `function`
entries plus `tool_calls`/`role:"tool"` messages. Both protocols express the
same three-tool surface described below, so one loop body drives both with a
per-provider serialization shim.

The cost of this choice, stated plainly: the harness owns the loop, so results
describe how a *model* behaves given tools, not how a shipped agent product
behaves. chant-bench measures the latter. Neither is more correct; they answer
different questions, and the report should not conflate them.

The concrete shape: a new `bench/agentic.py` module holding the loop, and two
small additions to the adapter interface. `ModelAdapter` grows a
`converse(messages, tools) -> dict` method alongside the existing `complete()`;
`complete()` stays exactly as it is so the one-shot path is untouched.
`AnthropicAdapter.converse` and `OpenAICompatAdapter.converse` each reuse the
existing payload-construction logic — including every reasoning-effort branch
and the ten-attempt retry ladder — and differ only in adding tool definitions
and parsing tool calls back out.

An adapter that cannot do tool calling (a local model whose server does not
implement the `tools` parameter) raises `AgenticUnsupported`, and the runner
records the run as skipped rather than falling back to one-shot. A silent
fallback would produce a results directory that looks agentic but is not.

### The tool surface

Three tools, identical in shape across all seven stacks; only the allowlist
behind `run_check` varies.

`read_file(path)` returns the contents of a workspace-relative file, capped
(proposed 100 KB, in the spirit of the existing 50 KB per-file cap in
`AnthropicAdapter.complete`). `list_files(path)` returns a recursive listing.
`write_file(path, content)` writes a workspace-relative file, creating parents.
`run_check(argv)` executes one command from the stack's allowlist inside the
workspace and returns exit code plus truncated stdout/stderr.

`write_file` deliberately replaces `extract_code_blocks()` for agentic runs.
That function (`bench/runner.py`, line 35) is an inference layer built to guess
which fenced block belongs at which path; it carries per-stack heuristics
(`k8s_stacks` must contain `apiVersion`, `tf_stacks` only accept HCL,
`chant_stacks` only accept TypeScript) precisely because guessing is hard. An
agent that writes files directly removes the guessing, which removes a source
of measurement noise — but also removes a confound the one-shot numbers
contain. That asymmetry is real and is called out as a threat to validity in
"Distinguishing the two modes" below, not papered over.

No `edit_file` in v1. A whole-file `write_file` is more tokens per edit but has
no failure mode of its own; a string-replacement tool introduces "old_string
not found" retries that would show up in the loop metrics as agent effort when
they are really tool friction. If v1 shows agents burning turns rewriting large
files, an `edit_file` can be added and the effect measured against the v1
baseline.

### Attempts, turns, and timeouts

Three limits, all recorded per run so a truncated run is never mistaken for a
finished one.

A turn cap bounds the conversation: proposed 30 model turns per run (a turn
being one assistant message, whether or not it calls tools). For calibration,
chant-bench's read-only query trials average 5.04 turns for chant and 17.5 for
alchemy-effect (`effort.turns` in `results/chant-i1.json` and
`results/alchemy-effect-g1.json`); an authoring task with a validation loop
should run longer than either, so 30 is a starting guess that a pilot must
confirm.

A wall-clock cap bounds the run: proposed 900 seconds, matching the existing
900-second read timeout for adaptive-thinking Opus generations
(`bench/runner.py`, line 220), so a single slow generation cannot alone exhaust
the budget. chant-bench's per-task agent timeout is 600 seconds
(`[agent] timeout_sec = 600.0` in each `task.toml`), scaled by a
`--timeout-multiplier`; adopting a multiplier here would be cheap and would let
slow local models run without editing the default.

A token cap bounds cost: see "Cost model and controls."

Each `run_check` invocation gets its own subprocess timeout, reusing the
per-stage values already in the stage modules — 60 seconds for lint and most
static checks, 120 for `pulumi preview` (`bench/stages/static.py`, line 153).
A check that times out returns a timeout marker to the agent as an ordinary
tool result rather than aborting the run; the agent is allowed to learn that
its command was too slow.

The run ends when the model returns a turn with no tool calls (it considers
itself done), or when any cap trips. On a cap trip, the workspace is graded as
it stands and `truncated_by` is recorded as one of `turns`, `wall_clock`, or
`tokens`. Grading truncated work rather than discarding it is deliberate: an
arm whose agents routinely hit the turn cap is telling us something about that
stack's feedback loop, and throwing those runs away would hide it. It also
follows chant-bench's hardest-won rule, discussed under metrics: an errored
trial stays in the denominator.

chant-bench's `-k 3` maps onto this repo's existing `-k` flag, and means the
same thing in both: independent trials, not nested attempts. `bench/score.py`
already computes pass@1 and pass@k from them. Adding a second attempt dimension
inside a run would make the two modes' `k` incomparable.

## Sandboxing and per-stack allowlists

The agent may run its own stack's local validation and nothing else.

The allowlist lives in a new `bench/agentic_allowlist.py` as
`ALLOWED_COMMANDS: dict[str, list[CommandSpec]]`, where a `CommandSpec` pins an
executable name and the argument shapes permitted for it. It is a per-stack
allowlist of argv prefixes, not a shell. `run_check` never invokes a shell: the
model supplies an argv list, the first element must match an allowed executable
for that stack, the remaining elements must satisfy that spec's argument policy,
and every path argument must resolve inside the workspace after `Path.resolve()`.
No pipes, no redirection, no `&&`, no shell globbing.

This is a deliberate departure from chant-bench, which gives the agent a full
shell and audits afterward. The argument for enforcing up front is that a
post-hoc regex catches a violation only after the tokens are spent and the run
is scored, and `aws-bench`'s own `emit-result.py` carries scar tissue from that
approach: it strips heredocs and answer-file redirections before matching,
because agents quoting `aws ec2 ...` inside their prose answers were inflating
the account-read count by about 6%. Enforcing at the call site makes the
question unambiguous. The argument against is that a shell is what a real
practitioner uses, and forbidding pipes may distort how agents work. This is an
open decision.

Per stack, seeded from what the stages already run:

knr-ops gets `yq eval . <paths>` and `kubeconform -summary
-ignore-missing-schemas <paths>` from `LINT_COMMANDS` (`bench/stages/lint.py`,
line 16), plus `kustomize build <dir>` and `flux build kustomization <file>
--dry-run` from `_knr_ops_static` (`bench/stages/static.py`, line 39).

crossplane gets `kubeconform -summary -ignore-missing-schemas <paths>` and
`crossplane beta render <claim>` (`bench/stages/static.py`, line 88).

terraform gets `terraform init -backend=false -input=false`, `terraform
validate`, and `terraform fmt -check`. `init -backend=false` is already what the
lint stage runs (`bench/stages/lint.py`, line 23) and is the one command in the
allowlist that may touch the network, since it resolves providers. See the open
decisions.

pulumi-python gets `python -m ruff check --select E,F .` (the same interpreter
path the lint stage constructs from `.venv/bin/python`) and `pulumi preview -s
dev --non-interactive --diff`. pulumi-typescript gets `tsc --noEmit
--skipLibCheck <files>` and the same `pulumi preview`.

chant gets `chant lint .` and `chant build . -f yaml -o <path>` (from PR #41's
`LINT_COMMANDS["chant"]` and `_chant_static`), `tsc --noEmit --skipLibCheck
<files>`, and `kubeconform` over the build output. The read-only query surface
that makes chant distinctive is also in scope: `chant search <query> [--src
<dir>] [--env <e>] [--explain] [--show <fields>]`, `chant graph <dir> --format
ir`, `chant list`, and `chant describe`. Those are the commands
`golden-base/chant/fixtures/MANIFEST.md` (on `bench/chant-golden`) documents as
the real operator surface, and the ones #4 currently approximates with
pre-computed fixtures. Excluded from chant's allowlist: `chant lifecycle
snapshot` and `chant lifecycle show` (cluster-touching), `chant import`,
`chant migrate`, `chant onboard`, `chant update`, `chant vendor`, `chant
dev-publish` (network or repo-mutating), and `chant mcp` / `chant lsp` / `chant
run` / `chant emulator` (long-lived processes).

bare gets `kubectl apply --dry-run=client -f <file>` (from PR #46's
`_bare_static`, `bench/stages/static.py` line 230 on that branch), plus `yq` and
`kubeconform`. `--dry-run=client` is load-bearing: it is what keeps bare's check
offline, and `--dry-run=server` must stay off the allowlist.

### Fairness rules for allowlist construction

`aws-bench`'s briefing rule is worth adopting verbatim in spirit: no arm is
taught a route the others lack. Its enforcement history is instructive — chant's
briefing originally carried a fourth rung pointing at `--live` mode, and
removing it dropped account reads from 44 to 0. A single extra sentence in one
arm's briefing changed that arm's measured behavior completely.

The rule proposed here: a command belongs on an arm's allowlist if and only if
it is (a) what a competent practitioner of that stack runs before committing,
and (b) runnable offline against a workspace with no cloud credentials. Rule (b)
is what keeps `terraform plan` and `pulumi up` off every list. That the
resulting lists differ in cheapness across arms is not an unfairness to correct
— it is the independent variable the hypothesis is about.

Process-level containment for every `run_check`: `cwd` set to the workspace,
`subprocess.run` with an explicit argv (never `shell=True`), a scrubbed
environment that carries only `PATH`, `HOME` pointed at a per-run scratch dir,
and `TF_IN_AUTOMATION`/`PULUMI_SKIP_UPDATE_CHECK`-style noise suppressors. Every
cloud credential variable is stripped: `AWS_*`, `GOOGLE_*`, `AZURE_*`,
`PULUMI_ACCESS_TOKEN`, `KUBECONFIG`, and the model API keys themselves
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Stripping the model keys matters: an
agent that can read the harness's own key from its environment is a real
exfiltration surface, and there is no legitimate reason for a validation command
to see it.

Network policy: no network beyond the model API, which the harness makes on the
agent's behalf and the agent cannot reach. The honest caveat is that argv
allowlisting plus environment scrubbing is not a network sandbox —
`terraform init` reaching a provider registry is the deliberate exception, and a
compromised or misbehaving binary on the allowlist could in principle reach out.
chant-bench does not solve this either; it runs its container with unrestricted
egress and relies on endpoint substitution for cloud isolation. If the owner
wants a hard guarantee rather than a policy, the loop needs to run inside a
network-namespaced container, which is a much larger change. Open decision.

## Briefings

The current prompt is `tasks/<stack>/<task>/prompt.md` with `{{scenario_spec}}`
substituted from `scenario/SPEC.md` (`materialize_task`, line 152). Those
prompts are written for a model that will answer in markdown: knr-ops
T2-generate, for instance, describes the repo layout in prose because the model
cannot look at it.

An agentic run needs a second layer, not a replacement. The task prompt stays
verbatim — it is the thing held constant across modes — and a per-stack briefing
is prepended. chant-bench composes exactly this way: Harbor's task assembly is
`"\n\n".join([instruction.md, *extra_instructions])`, so the agent sees the
question, a blank line, then the arm's briefing verbatim, and nothing else.
Proposed location: `briefings/<stack>.md`, mirroring chant-bench's `briefings/`
register, with `briefings/_common.md` holding shared boilerplate.

chant-bench's briefings share a rigid skeleton that transfers well: an H1 naming
the source of truth; a provenance paragraph saying what is mounted where and
what is installed; a bolded thesis sentence; one paragraph of domain gotcha
repeated *verbatim across all seven arms* (the launch-template caveat) so no arm
gets a hint the others lack; a command list under "Run from the project root";
and a numbered "Path to estate facts, in order" giving the same three rungs to
every arm. Word counts are published as a deliberate disclosure — chant 861,
alchemy-effect 446, cdk 395, terraform 326, pulumi 295, bare 232 — with the
argument that a model has read years of Terraform and has never seen chant.
iac-cd-bench should publish the same table for the same reason.

The common part states the workspace contract (you are in a scratch directory
containing the seeded repo; write your answer as files in it), the tool contract
(these are your tools; `run_check` runs only these commands), the completion
contract (stop when you believe the work is correct; a final markdown summary is
optional and is not what gets graded), and one constraint that has no analogue
in chant-bench and matters more here than anything else in this section.

**The briefing must not tell the agent to validate.** chant-bench's briefings
do steer — "Query the recorded state rather than enumerating the account
resource by resource" is a bolded instruction — and that is fine there, because
the thing being measured is whether the tool can answer the question, not
whether the agent chooses to use it. Here the thing being measured *is* whether
the agent chooses to run its local check. If the briefing says "run `kustomize
build` until it passes," the mode measures instruction-following and the
hypothesis becomes untestable. Each briefing lists what the agent *may* run and
says nothing about what it *should* run. This is the single most important
constraint on briefing authorship and the one most likely to erode as briefings
get edited.

The per-stack part is a short orientation: the stack's layout convention, the
idiom for environment separation (already stated per stack in
`scenario/SPEC.md`), and the allowlist rendered as a table of command plus
one-line description. Chant's is adapted from
`chant-bench/briefings/briefing-chant-snapshot.md`, which already describes
chant's query surface, its search grammar (`kind:`, `attr:`, `tag:`, `!`,
`->`/`<-`, `--show`, `--explain`), its derived attributes, and the stderr
warning about redirecting with `2>/dev/null` rather than `2>&1`.

Briefings are versioned in-repo and their SHA-256 prefix is recorded in every
run JSON, following `chant-bench`'s `briefing: {path, sha256}` block (a
12-hex-char prefix). Its skill file states the comparability rule outright: two
runs are comparable when they share a harness commit and a briefing SHA. This
repo should record a harness commit too — it has none today, and without one a
re-run silently becomes a different experiment.

The cold/warm condition still applies: warm copies `docs/` into `context/`, and
the briefing notes that `context/` holds documentation slices. Cold agentic runs
are where the "docs versus training-data recall" question gets its sharpest
version, since a cold agent can at least read the seed repo.

## Transcript capture

chant-bench splits artifacts three ways, and the split is worth copying: raw
evidence stays in the harness repo (`aws-bench/jobs/<job-id>/`, roughly 10 MB
per job, including per-trial `agent/claude-code.txt` stream logs and 172 KB ATIF
trajectories), while the publication repo carries a distilled
`results/<run-id>.json` and `transcripts/<run-id>.json` — both flat, both small,
both schema-validated in CI.

This repo has no separate harness repo, so the same idea maps to a retention
tier rather than a repo boundary: a full transcript written during the run, and
a distilled record kept in git.

Layout: `transcripts/<model>[-<tag>]/<stack>/<condition>/<task>_run<N>/` holding

`messages.jsonl` — one JSON object per conversation event, in order, each with
`seq`, `ts` (epoch float), `role` (`system` | `user` | `assistant` | `tool`), and
a role-appropriate payload. Assistant events carry `text`, `tool_calls`, and
per-turn `usage`. Tool events carry `tool`, `args`, `exit_code`, `stdout`,
`stderr`, and `duration_ms`.

`meta.json` — the run's identity and configuration: model, stack, task,
condition, run index, `reasoning_effort`, briefing path and SHA, allowlist
version, harness commit, the three caps, `truncated_by`, start/end timestamps.

`workspace/` — the final workspace contents, or a tarball, subject to the
retention decision below.

Rationale for JSONL over one JSON blob: transcripts are appended during the run,
so a crashed or killed run still leaves a readable partial transcript.
chant-bench gets this property for free because Claude Code streams stream-json
to a `tee`; an in-process loop has to choose it deliberately. The existing result
JSON already embeds full model output in `content`; agentic runs would make that
field enormous, so the run JSON keeps a `transcript_path` pointer and the last
assistant message only.

The distilled per-run transcript that stays in git should follow chant-bench's
`by_task` shape: the deduplicated, whitespace-collapsed command list plus the
tail of the final answer. chant-bench filters boring commands with
`BORING = ^\s*(cd \S+\s*&&\s*)?(ls|pwd|cat /etc|echo)\b` and truncates answers to
the last 700 characters. Here the analogue is: keep every `run_check` argv, drop
`list_files`, and keep the last assistant message.

Truncation policy for the full transcript: each `stdout`/`stderr` capped at 8 KB
(with `truncated: true` and the original byte count), which is generous next to
the 500-byte caps the stage modules use for their own logs. Workspaces are the
larger cost and are the subject of an open decision.

Transcripts are the audit trail for the loop metrics. Every number in the next
section is derivable from `messages.jsonl` alone, which means metric definitions
can change without re-running anything — the same property chant-bench gets from
deriving everything post-hoc from the stream log.

## Metrics

### The existing gates, unchanged

Every agentic run finishes by running the same four stages against the final
workspace: `lint.run_lint`, `static.run_static`, `semantic.run_semantic`, and
optionally `e2e.run_e2e`. Same functions, same thresholds, same `stages`
structure in the result JSON, so `bench/score.py` scores an agentic run without
modification and the composite is comparable across modes.

One wrinkle deserves stating plainly. In agentic mode the lint and static gates
run commands the agent was allowed to run itself, so an agent that iterates to
green has, by construction, passed those gates. Lint and static therefore stop
being independent measurements for agentic runs and become close to a check that
the agent looked. The semantic stage (`tests/test_task.py`, which the agent never
sees and cannot run) remains genuinely independent, as does e2e. Any cross-mode
headline number should lead with the semantic gate. The alternative —
withholding the local check from the agent — would make the mode unable to test
the hypothesis at all.

### Harness gates, borrowed from aws-bench

`aws-bench` runs four blocking gates around every scored run, and three of them
have direct analogues here worth building.

A preflight gate: assert each arm's golden implementation still passes its own
lint and static checks before spending tokens. `preflight_chant_golden()` in
PR #41 already does this for chant; generalizing it to all seven arms is a small
change. `aws-bench`'s version adds a lesson worth copying — its `Smoke` checks
carry a `must_match` regex, not just an exit code, because `terraform show -json`
on a missing state prints `{"format_version":"1.0"}` and exits 0. Exit codes are
not proof.

A tooling-health gate, modeled on `audit.py`. It buckets every tool invocation
into ok / missing / failed / killed and refuses the run on any of: the arm's own
CLI not found on PATH, any invocation killed by the kernel, more than 25% of
invocations failing when there were at least 10, or more than 10% of trials
never landing a successful tool call. A stack whose binary is absent produces a
zero that looks like a model failure, and this bench has already hit the milder
version of that — `bench/stages/lint.py` line 85 catches `FileNotFoundError` and
logs `NOT FOUND: <cmd>` while letting the stage pass. In agentic mode a missing
binary must be loud.

An independence gate, modeled on `independence.account_reads`. chant-bench
counts how often an agent bypassed its own stack's tooling to read the cloud
account directly. The analogue here: count `run_check` calls that invoke a tool
belonging to a *different* arm — a chant agent shelling out to `kustomize`, a
bare agent reaching for `flux`. Under the argv allowlist those calls are
rejected rather than executed, so the metric becomes attempted cross-arm reaches
per run. Non-zero is not automatically a failure, but it is a signal the arm's
own surface was found wanting.

### Validation-loop instrumentation

This is the part built specifically for the author's hypothesis. All of it is
computed from `messages.jsonl` and written into the run JSON under a new `loop`
key.

`check_invocations` — the count of `run_check` calls, and a breakdown by command
name. This is the headline number the hypothesis predicts will differ across
arms.

`check_invocations_before_first_write` and `..._after_last_write` — whether the
agent probes before authoring or only verifies afterward. A stack whose local
check is a genuine feedback loop should show checks interleaved with writes; a
stack where the check is expensive should show a single verification pass at the
end.

`time_to_first_green` — seconds from run start to the first `run_check` that
exits zero, and `turns_to_first_green` alongside it. Null when no check ever went
green. This is the most direct operationalization of "tighter feedback loop."
Recording both wall-clock and turns matters because wall-clock conflates the
check's own speed with the model's thinking time, and turns does not.

`green_streak_at_end` — whether the last invocation of each distinct allowed
command exited zero. Distinguishes "finished green" from "gave up."

`check_latency_ms` — per-invocation duration, aggregated to median and p90 per
command. This is the stack property the hypothesis is actually about, measured
rather than assumed. If `kustomize build` turns out to take four seconds in this
harness's environment while `terraform validate` takes two, the hypothesis's
premise needs revisiting before its conclusion does.

`failed_check_recovery_rate` — of the `run_check` calls that exited non-zero, the
fraction followed within three turns by a `write_file` and then a passing run of
the same command. This measures whether the loop is *useful*, not just whether it
is *used*. An arm that runs its check twenty times and never acts on the output is
not benefiting from a tight loop.

`turns`, `wall_clock_s`, `tokens.input`, `tokens.output`, `tokens.cache_read`
(where the provider reports it), `cost_usd`, `truncated_by`.

Naming caution: chant-bench calls this block `effort` — `{tool_calls, turns,
wall_seconds, tokens_in, tokens_out, cost_usd, cost_usd_run}` — meaning
*expenditure*. This repo already uses `reasoning_effort` to mean the pinned
thinking level. Calling the block `loop` here avoids a collision that would be
confusing in exactly the comparison the epic is about.

### Testing the hypothesis

With those fields, the hypothesis has a direct test rather than a narrative one.

Within a model and effort level, across arms: rank arms by median
`check_invocations` and by median `check_latency_ms`, and rank them by semantic
gate pass rate. The hypothesis predicts a negative rank correlation between check
latency and pass rate, mediated by invocation count. The mediation is the
interesting part — if cheap-check arms win *without* elevated invocation counts,
the win is coming from something other than the feedback loop, and the hypothesis
is wrong even though its prediction held.

Within an arm, across runs: correlate `check_invocations` and
`failed_check_recovery_rate` with semantic gate pass. A positive within-arm
correlation is the cleanest evidence that the loop causes the outcome, because it
holds the stack fixed.

Across modes: for each arm, the agentic-minus-one-shot delta in semantic pass
rate. The hypothesis predicts the delta is largest for the cheapest-check arms.
This is the comparison #8 asks for ("rerun the chant-vs-knr-ops comparison in
both modes to see whether the mode changes the ranking") and it is the one most
exposed to the `write_file`-versus-`extract_code_blocks` confound.

Sample size is the honest limitation. At k=3 and three tasks, an arm has 9 runs
per mode. That supports descriptive comparison and rank ordering; it does not
support a significance claim per task. The report should present these as effect
sizes with run counts, not p-values.

Two reporting rules from chant-bench are worth adopting wholesale, both of which
exist because of specific failures. First, errored runs stay in the denominator:
`validate_results.py` fails a run whose `trials != expected_trials`, with the
comment that pass rate is over the survivors rather than over the run. The
originating incident was a terraform run that lost 22 of 24 trials to Docker and
published as 2 passed / 2 trials = 1.000. This repo has the same scar —
commit `c6b6b90` deleted error-only artifacts from a credit-exhausted opus-5
partial run. An `expected_runs` field alongside `runs` would make the failure
structural rather than a cleanup chore. Second, ranking uses the median of the
last three valid runs, never best-of and never latest-alone.

A new `bench/loop_metrics.py` computes the `loop` block from a transcript, and a
`--recompute-loop-metrics` path lets definitions change after the fact.
`bench/report.py` grows a validation-loop table rendered only for agentic result
sets.

## Effort pinning and recording

PR #50 adds `reasoning_effort` to every run JSON, read off the adapter. That
carries over unchanged, and agentic mode extends it three ways.

Effort is pinned per arm, and pinning is enforced rather than documented. The
runner refuses to write into an existing agentic results directory whose prior
runs carry a different `reasoning_effort` unless `--results-tag` distinguishes
them. The current convention (`results/claude-opus-5-low/`) already does this by
hand; the check turns a convention into a guarantee. The failure this prevents is
subtle and expensive: a suite half-run at `max` and half at `low` looks like a
complete suite. `validate_results.py` in chant-bench is the model — a standalone
schema-and-invariant checker run in CI, which this repo lacks entirely.

Effort is recorded per turn, not just per run. Adaptive-effort models
(`claude-opus-5*`, `claude-opus-4-8` — `bench/runner.py`, line 216) decide how
much to think per request, so a 30-turn run has 30 effort decisions behind one
pinned setting. Where the provider reports thinking-token usage,
`messages.jsonl` records it per assistant turn. This is how "the agent iterated
more" gets separated from "the agent thought harder each turn," and it is a
distinction no chant-bench number can currently make.

The effort-to-arm mapping is recorded in `meta.json` and asserted at suite level.
A cross-arm agentic comparison where chant ran at `max` and knr-ops at `low` is
not a comparison, and the mode should make that state unrepresentable rather than
merely discouraged.

Cross-provider effort levels are not equivalent and the design does not pretend
otherwise. `low` on gpt-5 and `low` on GLM-5.3 are different amounts of
computation. Effort pinning makes an arm-to-arm comparison valid *within* a
model; it does not make model-to-model comparison at nominally equal effort
valid. The report should say so where it presents cross-model tables.

## Cost model and controls

Agentic runs are the most expensive thing this bench would do, and chant-bench
supplies real numbers rather than guesses.

Its per-trial means, from published results: chant at 123,650 input tokens and
2,250 output tokens per trial, $0.0301 each, $0.7218 for a 24-trial run;
alchemy-effect at 421,515 input and 4,966 output, $0.0882 each, $2.1166 per run.
Both on `claude-haiku-4-5`. `chant-bench/docs/running.md` quotes $0.70–$2.40 per
arm run and about $40 for a full three-replicate matrix across seven arms.

Two things follow. First, the input side dominates by roughly 50:1 — an agentic
run re-sends a growing conversation every turn, and the accumulated tool output
is most of it. Prompt caching is therefore the single biggest cost lever, which
is why `cache_read` is in the recorded metrics: without it the cost model is
unfalsifiable. Second, the spread between arms is 3.4x on tokens, tracking turn
count (5.04 versus 17.5). Cost per arm is itself a finding, not just a budget
line — and on this bench's authoring tasks with a real validation loop, both the
absolute numbers and the spread should be larger.

Scaling to this repo: an agentic run here should be assumed to cost one to two
orders of magnitude more than the current one-shot runs, which measure roughly
2K input and 1.5K output tokens (from
`results/claude-opus-4-8-low/crossplane/warm/T1-comprehend_run0.json`). At
frontier-model prices rather than haiku prices, a seven-arm agentic suite is a
budget item that needs approving before it is started, not after.

Controls, all defaulting conservative.

A hard per-run token cap (`--max-run-tokens`, proposed default 400,000 cumulative
input plus output — just under alchemy-effect's observed per-trial mean, so it
binds rather than decorates). Tripping it ends the run with
`truncated_by: "tokens"`, and the workspace is still graded.

A suite-level budget (`--budget-tokens`, and ideally `--max-budget-usd`) that
stops the suite cleanly between runs when cumulative usage crosses it, writing
what completed. The failure this prevents already happened in this repo: commit
`5fcc0d2` records a `claude-opus-5` suite that stopped at 57 of 75 runs on credit
exhaustion, and `c6b6b90` had to delete the error-only artifacts it left behind.
Harbor's Claude Code adapter exposes `--max-budget-usd` as an unused kwarg,
which suggests the need is general.

Agentic eligibility is per task, not global. The authoring archetypes —
T2-generate, T3-modify, T4-debug — are where a validation loop can help and are
the natural agentic set. T1-comprehend and T5-review produce prose graded by
rubric; an agent could read the repo, which is a real capability difference, but
there is no local check to loop on, so they exercise the tool surface without
testing the hypothesis. T6-semantics is a quiz whose whole point is predicting
tool behavior from reading; letting the agent run the tool would invalidate the
task outright. Proposed default:
`--agentic-tasks T2-generate,T3-modify,T4-debug`, with T6 hard-excluded (the
runner refuses `--agentic` on T6 rather than silently allowing it), and T1/T5
available opt-in for a separate question about repo-reading. That default is a
3-task × 7-stack × k=3 suite: 63 agentic runs.

Cheap-first ordering: the runner should support running one stack or one task
agentically (`--stack`, `--task` already exist) so a pilot on one arm can
calibrate the caps before a full suite. chant-bench's matrix script interleaves
by replicate rather than by arm — `for r in 1..REPS { for arm in ARMS }` — so a
half-finished matrix still compares across arms rather than having complete data
for the first two arms and none for the rest. That ordering is free to adopt and
worth adopting.

## Distinguishing the two modes

Three mechanisms, because one is not enough.

In the run JSON: a `mode` field, `"one-shot"` or `"agentic"`. `bench/score.py`
and `bench/report.py` read it. Existing result files lack the field, so the
loader treats absent as `"one-shot"`, which keeps every archived result valid
without a migration.

In the results path: a `--mode agentic` run writes to
`results/<model>-agentic[-<tag>]/...` by default. The suffix is not decorative —
`bench/score.py`'s `load_results()` (line 118) globs a model directory wholesale,
so mixing modes in one directory would silently average them into a single
composite. Keeping the directories separate makes the existing aggregation
correct with no change to it.

In the report: `bench/report.py` renders one matrix per mode plus a delta table,
and never averages across modes. The delta table is the artifact #8 asks for.
chant-bench states the general form of this rule as "substrate is never pooled,"
reserving a `run.substrate` field with a hard rule against combining emulated and
real-cloud runs. Mode is this repo's substrate.

The confound that must be stated wherever those numbers appear: agentic runs
bypass `extract_code_blocks()`. Some part of any agentic-minus-one-shot delta is
the removal of extraction noise, not the feedback loop. Two ways to bound it, and
the design proposes doing the first. Re-grade the one-shot runs' final markdown
by hand for a sample of tasks to estimate how often extraction lost a file; that
gives a correction factor. The second, stronger option is a third mode — agentic
tools but zero `run_check` allowance — which isolates the loop from the
file-writing. That is a clean experiment and a real cost increase, and it is in
the open decisions.

## Migration path

What changes in `bench/runner.py`: `ModelAdapter` gains an optional `converse()`;
`AnthropicAdapter` and `OpenAICompatAdapter` each gain a `converse()` that reuses
their existing payload construction and retry logic; `run_task()` gains a branch
calling `bench.agentic.run_agentic_task()` instead of the
`complete()`-plus-`extract_code_blocks()` sequence, with both paths converging on
the same four stage calls; `main()` gains `--mode`, `--agentic-tasks`,
`--max-turns`, `--max-run-tokens`, `--budget-tokens`, `--timeout-multiplier`, and
a briefing-directory override; the results-path construction gains the `-agentic`
suffix.

What is new: `bench/agentic.py` (the loop), `bench/agentic_allowlist.py`
(per-stack command specs and the argv validator), `bench/loop_metrics.py`
(transcript to `loop` block), `bench/validate_results.py` (schema and invariant
checker, modeled on chant-bench's, runnable in CI), `briefings/` (per-stack plus
`_common.md`), and `transcripts/`. Note that `.gitignore` already lists
`results/` even though result files are committed — they were force-added — so
`transcripts/` should follow the same pattern deliberately rather than by
accident: ignored by default, with the distilled per-run record force-added and
the full `messages.jsonl` and workspaces left out of git.

What is untouched: all four stage modules, all task definitions, `bench/score.py`
except for reading `mode`, every archived result under `results/`, and the entire
one-shot code path including `extract_code_blocks()`. One-shot remains the
default; `--mode agentic` is opt-in, as #8 specifies.

Sequencing that keeps each step reviewable: the allowlist module and its argv
validator first, with unit tests asserting every rejection case (shell
metacharacters, path escapes, non-allowlisted executables, credential leakage
through the environment) — this is the security surface and it should land before
anything can call it. Then the loop against one adapter and one stack, run
manually. Then the second adapter protocol. Then transcripts and metrics. Then
briefings for all seven arms. Then a one-arm pilot to calibrate caps. Then the
full suite.

`tests/test_runner.py` currently asserts five stacks in three places and imports
the two adapters. Adding tests for the allowlist validator and a transcript
fixture is straightforward; the existing tests need no changes, since nothing in
the one-shot path moves.

## Non-goals

Not replacing one-shot mode. Both modes are reported; #8's question is whether
the mode changes the ranking, which requires keeping both.

Not giving the agent cloud credentials, a cluster, or `apply`/`up` powers. The
e2e stage owns live infrastructure and stays harness-driven, run after the agent
is finished. An agent that can apply can also destroy, and the blast radius is a
real AWS account. chant-bench avoids this with an emulator plus fake credentials;
this bench avoids it by keeping the agent away from e2e entirely.

Not building a general agent framework. The three-tool surface is fixed and
minimal; if a stack needs a fourth tool to be represented fairly, that is a
design change with a fairness argument attached, not a configuration option.

Not measuring agent-framework quality. This bench compares models and stacks.
Whether Claude Code's harness beats a bare tool loop is a different question —
and, notably, the question chant-bench's numbers actually answer — needing a
different control.

Not multi-agent, not subagents, not memory across runs. Each run starts from a
fresh workspace and an empty conversation, matching the one-shot mode's
independence assumption, which `bench/score.py`'s consistency axis depends on.

Not human-in-the-loop. Runs are unattended; a run that stalls trips a cap.

Not making the seven arms' allowlists equally cheap. The cost asymmetry is the
independent variable.

Not adopting chant-bench's container-per-trial isolation. That model costs a
Docker image build and a compose project per run, and this bench's checks are
offline and non-destructive by construction. Revisit only if the sandboxing
decision below goes the other way.

## Open decisions for the owner

1. Loop placement. In-adapter tool loop as proposed, or an external CLI driver
   closer to chant-bench's design? The proposal argues in-adapter because the
   OpenAI-compatible arms (gpt-5.4, GLM-5.3, qwen local, kimi) have no agent CLI
   and would drop out of the comparison. Accepting it means the harness owns the
   loop and can never claim to be measuring a shipped agent product.

2. Enforce the allowlist up front, or audit after the fact? The proposal enforces
   at the call site with no shell. chant-bench gives a full shell and greps the
   trajectory afterward, which is more realistic and demonstrably harder to get
   right — its matcher needs heredoc stripping and redirect filtering to avoid
   counting commands the agent merely quoted in prose. A middle option: allow a
   shell but audit and reject the run, keeping the realism and paying with lost
   token spend on violations.

3. Network for `terraform init`. Terraform's local validation genuinely needs a
   provider download. Options: allow `init -backend=false` and accept one
   network-touching command; pre-warm a provider mirror into the workspace so the
   arm is offline like the others; or drop `init` and accept that `terraform
   validate` fails without it, which effectively removes terraform's local check
   and makes it an extreme point on the hypothesis's own axis.

4. Sandboxing strength. Argv allowlist plus scrubbed environment (proposed), or a
   container with no network namespace? The former is a policy; the latter is a
   guarantee and a significantly larger build. Worth noting chant-bench chose
   neither — its container has unrestricted egress.

5. Turn and token caps. 30 turns, 900 seconds, 400K tokens per run are anchored
   to chant-bench's observed 5–17.5 turns and 123K–421K input tokens on
   *read-only* trials, which should understate authoring runs. A one-arm pilot
   should replace them with data before the caps get baked into a suite whose
   numbers depend on them.

6. Agentic-eligible tasks. Proposed default T2/T3/T4 with T6 hard-excluded and
   T1/T5 opt-in. Is repo-reading on T1/T5 a question worth paying for?

7. The third control mode. Agentic-tools-without-`run_check` would separate the
   feedback loop from the removal of `extract_code_blocks()` noise. It roughly
   doubles the agentic suite cost. Without it, the mode-delta numbers carry a
   confound that can only be bounded by hand-grading, not eliminated.

8. `k` for the agentic suite. k=3 gives 9 runs per arm per mode on a three-task
   set — enough for rank ordering, not for significance. Raising k for the
   agentic comparison specifically is the main lever on statistical strength and
   the main lever on cost.

9. Workspace retention. Keeping every final workspace makes failures debuggable
   and re-grading possible without re-running; it is also the largest storage line
   item. Options: keep all, keep only failed runs, keep a tarball, or keep none
   and rely on transcripts. chant-bench's answer is the split — full evidence in
   the harness repo, a distilled record in the publication repo.

10. Prerequisite ordering. This mode needs seven stacks, so PRs #41 (chant
    wiring), #46 (bare wiring), and #50 (effort recording) should land first. #8
    says agentic is "only worth doing after the single-shot comparison produces
    numbers," and nothing found during this design contradicts that — issue #40
    is the gate.

11. Briefing neutrality enforcement. The briefings must not instruct the agent to
    validate, or the mode measures instruction-following. chant-bench's history
    shows how sharp this edge is: deleting one rung from chant's briefing moved
    its account reads from 44 to 0. Should neutrality be a test — a linter over
    `briefings/*.md` rejecting imperative validation language — or a review
    convention?

12. Adopt chant-bench's schema-validation discipline more broadly? A
    `bench/validate_results.py` with required keys, a pass-rate-consistency
    check, an `expected_runs`-versus-`runs` check, and a CI hook would catch the
    class of failure that produced commits `5fcc0d2` and `c6b6b90` in this repo.
    It is useful for one-shot results today, independent of whether agentic mode
    is ever built.
