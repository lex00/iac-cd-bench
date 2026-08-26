"""Static-gate tests for the bare and knr-ops arms (#81, #82, #83).

Both gates used to be incapable of passing, for different reasons, and no
test caught it because no test asserted that a correct answer *passes*. A
gate that fails everything looks identical to a stack that gets everything
wrong, right up until someone publishes the difference as a finding.

So the load-bearing assertion in this file is the boring one: a known-good
manifest set produces `passed: True`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bench.stages.static import SCHEMA_DIR, _bare_static, run_static

# The ACK resources bare's task fixtures actually use, spelled correctly.
GOOD_BARE = """\
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
# emitted it, along with UserPolicy and RolePolicy. With schemas vendored and
# -ignore-missing-schemas off, an invented kind has to fail.
INVENTED_KIND = """\
apiVersion: iam.services.k8s.aws/v1alpha1
kind: RolePolicyAttachment
metadata:
  name: myapp-logs-attach
spec:
  roleName: myapp-logs-role
"""

pytestmark = pytest.mark.skipif(
    shutil.which("kubeconform") is None, reason="kubeconform not on PATH"
)


def _run(tmp_path: Path, text: str, name: str = "manifest.yaml"):
    (tmp_path / name).write_text(text)
    results: list[str] = []
    return _bare_static(tmp_path, results), results


def test_vendored_schemas_are_present():
    """The gate is only as good as its schema mirror; an empty schemas/ would
    turn every CRD into a failure and look like a model problem (#83)."""
    assert (SCHEMA_DIR / "s3.services.k8s.aws" / "bucket_v1alpha1.json").is_file()
    assert (SCHEMA_DIR / "iam.services.k8s.aws" / "policy_v1alpha1.json").is_file()


def test_a_correct_bare_answer_passes(tmp_path):
    """The assertion whose absence let #81 stand: the gate can pass."""
    (passed, acted), results = _run(tmp_path, GOOD_BARE)

    assert acted, f"gate abstained on a valid answer: {results}"
    assert passed, f"gate failed a valid answer: {results}"


def test_invented_crd_kind_fails(tmp_path):
    """A kind that resolves to no schema is a kind that does not exist."""
    (passed, acted), results = _run(tmp_path, INVENTED_KIND)

    assert acted
    assert not passed
    assert any("RolePolicyAttachment" in r for r in results)


def test_bare_gate_needs_no_cluster(tmp_path):
    """#81 in one line: the stage must not depend on an API server. If this
    ever regresses to kubectl, the logs carry the connection error again."""
    (passed, _acted), results = _run(tmp_path, GOOD_BARE)

    blob = "\n".join(results)
    assert passed
    assert "connection refused" not in blob
    assert "openapi" not in blob.lower()
    assert "server API group list" not in blob


def test_empty_workspace_is_inapplicable_not_a_pass(tmp_path):
    """A run that produced nothing must not collect a free static pass."""
    stage = run_static(tmp_path, "bare")

    assert stage.get("skipped") or stage.get("inapplicable")
    assert not stage.get("passed")


# ── the harness supplies the Pulumi project scaffold ─────────────────────

def _aws_creds() -> bool:
    import os
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    shared = os.environ.get("AWS_SHARED_CREDENTIALS_FILE") or os.path.expanduser("~/.aws/credentials")
    return Path(shared).is_file()


pulumi_needs_creds = pytest.mark.skipif(
    not _aws_creds(),
    reason="pulumi preview validates AWS credentials against STS; see docs/result-integrity.md",
)

GOLDEN_PY = Path(__file__).resolve().parent.parent / "golden-base" / "pulumi-python"


@pulumi_needs_creds
def test_pulumi_static_passes_without_a_project_file():
    """Models write __main__.py and Pulumi.<stack>.yaml but never Pulumi.yaml,
    the *project* file. Without it pulumi cannot resolve a project and every
    model run failed on "pass the fully qualified name" — a uniform failure
    unrelated to the model's code, while the golden passed only because a
    Pulumi.yaml had been added to it.

    The gate already fabricates a backend, a stack and a venv; the project
    scaffold belongs with them.
    """
    import shutil, tempfile
    from bench.stages import static as static_mod

    ws = Path(tempfile.mkdtemp(prefix="pulumi-noproj-"))
    try:
        shutil.copytree(GOLDEN_PY, ws, dirs_exist_ok=True, symlinks=True)
        (ws / "Pulumi.yaml").unlink()
        stage = static_mod.run_static(ws, "pulumi-python")
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    assert stage.get("passed"), (
        "a workspace without Pulumi.yaml still fails — the harness is not "
        "supplying the project scaffold:\n" + (stage.get("logs") or "")[:800]
    )


@pulumi_needs_creds
def test_a_workspaces_own_project_file_is_not_clobbered():
    """Only supply the scaffold when the workspace has none."""
    import shutil, tempfile
    from bench.stages import static as static_mod

    ws = Path(tempfile.mkdtemp(prefix="pulumi-ownproj-"))
    try:
        shutil.copytree(GOLDEN_PY, ws, dirs_exist_ok=True, symlinks=True)
        original = (ws / "Pulumi.yaml").read_text()
        static_mod.run_static(ws, "pulumi-python")
        assert (ws / "Pulumi.yaml").read_text() == original
    finally:
        shutil.rmtree(ws, ignore_errors=True)
