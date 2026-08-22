"""Semantic-understanding quiz grader — crossplane T6."""

import json
import re
from pathlib import Path

import pytest


def _load_answers() -> dict:
    ws = Path(".")
    for c in sorted(ws.rglob("answers.json")):
        try:
            return json.loads(c.read_text())
        except Exception:
            continue
    out = ws / "model_output.md"
    if out.exists():
        text = out.read_text()
        # Accept any fence info string (```json, ```answers.json, bare ```, etc.)
        blocks = re.findall(r"```([\w.-]*)[ \t]*\n(.*?)```", text, re.DOTALL)
        for _info, raw in reversed(blocks):
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                return json.loads(raw)
            except Exception:
                continue
    pytest.fail("no parseable answers.json found in workspace or model_output.md")


@pytest.fixture(scope="module")
def answers() -> dict:
    return _load_answers()


def _norm(v) -> str:
    return str(v).strip().lower().replace("_", "-")


def test_q1_claim_delete_cascades(answers):
    """Claim deletion cascades to composed managed resources."""
    assert "delet" in _norm(answers.get("q1", "")), \
        f"q1: expected deleted, got {answers.get('q1')!r}"


def test_q2_orphan_bucket_survives(answers):
    """deletionPolicy: Orphan keeps the AWS bucket."""
    assert "exist" in _norm(answers.get("q2", "")), \
        f"q2: expected exists, got {answers.get('q2')!r}"


def test_q3_delete_policy_removes_role(answers):
    """deletionPolicy: Delete removes the IAM role in AWS."""
    assert "delet" in _norm(answers.get("q3", "")), \
        f"q3: expected deleted, got {answers.get('q3')!r}"


def test_q4_manual_update_policy_pins_revision(answers):
    """compositionUpdatePolicy: Manual pins the claim to its revision."""
    assert "manual" in _norm(answers.get("q4", "")), \
        f"q4: expected manual, got {answers.get('q4')!r}"


def test_q5_claim_connection_secret_location(answers):
    """Claim secret lands as storefront-conn in the claim namespace team-a."""
    q5 = answers.get("q5") or {}
    assert _norm(q5.get("name", "")) == "storefront-conn", \
        f"q5 name: expected storefront-conn, got {q5.get('name')!r}"
    assert _norm(q5.get("namespace", "")) == "team-a", \
        f"q5 namespace: expected team-a, got {q5.get('namespace')!r}"


def test_q6_parallel_convergence(answers):
    """Composed resources are created in parallel and converge."""
    assert "parallel" in _norm(answers.get("q6", "")), \
        f"q6: expected parallel-converge, got {answers.get('q6')!r}"


def test_q7_claim_namespaced_xr_cluster_scoped(answers):
    """Claims are namespaced; XRs are cluster-scoped."""
    q7 = answers.get("q7") or {}
    assert "namespaced" in _norm(q7.get("claim", "")), \
        f"q7 claim: expected namespaced, got {q7.get('claim')!r}"
    assert "cluster" in _norm(q7.get("xr", "")), \
        f"q7 xr: expected cluster-scoped, got {q7.get('xr')!r}"
