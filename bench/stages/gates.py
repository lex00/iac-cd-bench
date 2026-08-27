"""Gates migrated onto the contract (bench/stages/contract.py).

One arm at a time. A gate lives here once it reports evidence rather than a
bare verdict, and once it ships the fixture pair that proves it can tell a
right answer from a wrong one.

`bare` goes first because it is the arm that already got this right: its static
gate has counted validated resources and refused a zero-evidence pass since
#81. Everything below is that behaviour restated in the contract's vocabulary,
which is the point — the contract is not a new idea, it is the one good idea in
this file generalised so the other six arms cannot skip it. chant went without
it and shipped #104: `Valid: 0 ... Skipped: 38` reported as PASS on every run
ever recorded.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bench.stages import lint as lint_mod
from bench.stages.contract import Check, Inapplicable, StageResult, register
from bench.stages.static import _kubeconform_valid_count

TIMEOUT = 60
ROOT = Path(__file__).resolve().parents[2]

# The ACK resources bare's fixtures actually use, spelled correctly. A model
# answer, not the golden: the golden is the input this gate was written
# against, so passing it proves almost nothing (contract.Gate.fixture_pass).
_GOOD = """\
apiVersion: s3.services.k8s.aws/v1alpha1
kind: Bucket
metadata:
  name: myapp-logs-prod
spec:
  name: myapp-logs-prod
---
apiVersion: iam.services.k8s.aws/v1alpha1
kind: Policy
metadata:
  name: myapp-logs-access-prod
spec:
  name: myapp-logs-access-prod
  policyDocument: '{"Version":"2012-10-17","Statement":[]}'
"""

# `RolePolicyAttachment` is not an ACK IAM kind. Models in the 3arm-v3 matrix
# emitted it, along with UserPolicy and RolePolicy.
_INVENTED = """\
apiVersion: iam.services.k8s.aws/v1alpha1
kind: RolePolicyAttachment
metadata:
  name: myapp-logs-attach
spec:
  roleName: myapp-logs-role
"""


class BareGate:
    """kubeconform over every manifest, against the vendored schema mirror."""

    stack = "bare"

    def run(self, workspace: Path) -> StageResult:
        manifests = [
            f for f in sorted(
                list(workspace.rglob("*.yaml")) + list(workspace.rglob("*.yml"))
            )
            if lint_mod.is_k8s_manifest(f)
        ]
        if not manifests:
            return StageResult(
                inapplicable=Inapplicable.NO_ARTIFACT,
                reason="no Kubernetes manifests in workspace",
            )

        resolved = shutil.which("kubeconform")
        if resolved is None:
            # The gate could not run, and the model did not cause that. Scored
            # in neither direction -- failing the arm for a missing binary is
            # the #81 defect, and dropping it silently is #110.
            return StageResult(
                inapplicable=Inapplicable.GATE_DEFECT,
                reason="kubeconform is not on PATH",
            )

        result = StageResult()
        for f in manifests:
            argv = ("-summary", *lint_mod.kubeconform_schema_args(), str(f))
            try:
                proc = subprocess.run(
                    [resolved, *argv], capture_output=True, text=True,
                    timeout=TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                result.checks.append(Check(
                    tool="kubeconform", argv=argv, exit_code=124, examined=0,
                    resolved_path=resolved, detail=f"timed out on {f.name}",
                ))
                continue
            result.checks.append(Check(
                tool="kubeconform",
                argv=argv,
                exit_code=proc.returncode,
                # The Valid count, never the file count: a file whose every
                # kind was skipped is not evidence of anything, which is the
                # distinction #104 turned on.
                examined=_kubeconform_valid_count(proc.stdout),
                resolved_path=resolved,
                detail=(proc.stdout or proc.stderr or "")[:500],
            ))
        return result

    def fixture_pass(self, tmp: Path) -> Path:
        ws = tmp / "bare-good"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "manifest.yaml").write_text(_GOOD)
        return ws

    def fixture_fail(self, tmp: Path) -> Path:
        ws = tmp / "bare-invented"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "manifest.yaml").write_text(_INVENTED)
        return ws


register(BareGate())


class CrossplaneGate:
    """`crossplane render` over the composite the model's XRD declares.

    Migrated second because it is the arm the contract's vocabulary was most
    needed for. Its gate abstained on 12 of 12 runs in coverage-v2 (#89) and 3
    of 6 in coverage-v3 (#109), and under rule 10 an abstention leaves the
    correctness denominator -- so the arm scored 1.00 correctness off a single
    attempted stage and outranked knr-ops, which attempted three and failed two
    (#110). A gate that cannot run was outscoring one that could.

    `GATE_DEFECT` is the distinction that fixes it: crossplane abstaining
    because render wanted an XR the task tells models not to write is the
    harness's fault, and must not be scored in either direction.
    """

    stack = "crossplane"

    def run(self, workspace: Path) -> StageResult:
        from bench.stages.static import (
            _classify_crossplane_docs, _ensure_functions, _synthesize_xr,
        )

        results: list[str] = []
        claims, compositions, xrds, functions = _classify_crossplane_docs(workspace)

        if not claims and xrds:
            synth = _synthesize_xr(workspace, xrds, results)
            if synth is not None:
                claims = [synth]
        if claims and compositions and not functions:
            functions = _ensure_functions(workspace, functions, results)

        if not claims:
            return StageResult(
                inapplicable=Inapplicable.NO_ARTIFACT,
                reason="no composite resource, and no XRD to derive one from: "
                       f"{len(compositions)} composition(s), {len(xrds)} xrd(s)",
            )
        if not compositions or not functions:
            # render structurally cannot run. That is the gate's problem, not
            # the model's -- the tasks ask for an XRD and a Composition, and
            # scoring this either way is #110.
            return StageResult(
                inapplicable=Inapplicable.GATE_DEFECT,
                reason=f"render needs a composition and a functions file, found "
                       f"{len(compositions)} / {len(functions)}",
            )

        resolved = shutil.which("crossplane")
        if resolved is None:
            return StageResult(
                inapplicable=Inapplicable.GATE_DEFECT,
                reason="crossplane is not on PATH",
            )

        result = StageResult(reason="; ".join(results))
        for claim in claims:
            argv = ("render", str(claim), str(compositions[0]), str(functions[0]))
            try:
                proc = subprocess.run(
                    [resolved, *argv], capture_output=True, text=True, timeout=120,
                )
            except subprocess.TimeoutExpired:
                result.checks.append(Check(
                    tool="crossplane", argv=argv, exit_code=124, examined=0,
                    resolved_path=resolved, detail="render timed out"))
                continue
            # Composed resources rendered, not files read: a render that emits
            # nothing has validated nothing, whatever its exit code.
            composed = sum(
                1 for line in (proc.stdout or "").splitlines()
                if line.startswith("kind:")
            )
            result.checks.append(Check(
                tool="crossplane", argv=argv, exit_code=proc.returncode,
                examined=composed, resolved_path=resolved,
                detail=(proc.stderr or proc.stdout or "")[:500],
            ))
        return result

    def fixture_pass(self, tmp: Path) -> Path:
        """XRD + Composition and NO XR -- exactly what the tasks ask for.

        This is the fixture that exposed #109: the gate demanded a composite
        the prompts explicitly tell models not to write ("without changing
        existing claims"), then recorded `inapplicable` when they obeyed.
        """
        ws = tmp / "xp-good"
        ws.mkdir(parents=True, exist_ok=True)
        golden = ROOT / "golden-base" / "crossplane"
        shutil.copy2(golden / "xrds" / "composite-web-service.yaml", ws / "xrd.yaml")
        shutil.copy2(golden / "compositions" / "composition.yaml", ws / "composition.yaml")
        return ws

    def fixture_fail(self, tmp: Path) -> Path:
        """A Composition referencing a function pipeline it never declares."""
        ws = tmp / "xp-bad"
        ws.mkdir(parents=True, exist_ok=True)
        golden = ROOT / "golden-base" / "crossplane"
        shutil.copy2(golden / "xrds" / "composite-web-service.yaml", ws / "xrd.yaml")
        (ws / "composition.yaml").write_text(
            "apiVersion: apiextensions.crossplane.io/v1\n"
            "kind: Composition\n"
            "metadata:\n"
            "  name: broken\n"
            "spec:\n"
            "  compositeTypeRef:\n"
            "    apiVersion: composite.example.com/v1\n"
            "    kind: XAWSWebService\n"
            "  mode: Pipeline\n"
            "  pipeline:\n"
            "    - step: nope\n"
            "      functionRef:\n"
            "        name: function-that-does-not-exist\n"
        )
        return ws


register(CrossplaneGate())
