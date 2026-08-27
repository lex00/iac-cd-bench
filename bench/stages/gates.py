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
