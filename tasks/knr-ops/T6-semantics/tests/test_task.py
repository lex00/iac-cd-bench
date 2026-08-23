"""Semantic-understanding quiz grader — knr-ops T6.

Parses the model's answers.json (from the workspace or from the last JSON
fenced block in model_output.md) and grades each question independently.
Runs with cwd = model workspace.
"""

import json
import re
from pathlib import Path

import pytest


def _load_answers() -> dict:
    ws = Path(".")
    # Preferred: extracted answers.json anywhere in the workspace
    candidates = sorted(ws.rglob("answers.json"))
    for c in candidates:
        try:
            return json.loads(c.read_text())
        except Exception:
            continue
    # Fallback: last JSON fenced block in model_output.md
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
        # Bare JSON: whole text, or the outermost {...} span (no fence at all)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        for candidate in filter(None, (text.strip(), m.group(0) if m else "")):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and ("q1" in parsed or "q2" in parsed):
                    return parsed
            except Exception:
                continue
    pytest.fail("no parseable answers.json found in workspace or model_output.md")


@pytest.fixture(scope="module")
def answers() -> dict:
    return _load_answers()


def _norm(v) -> str:
    return str(v).strip().lower().replace("_", "-")


def test_q1_rds_class_change_in_place(answers):
    """dbInstanceClass is mutable: ModifyDBInstance, not replacement."""
    assert "updated" in _norm(answers.get("q1", "")) or _norm(answers.get("q1", "")) == "in-place", \
        f"q1: expected updated-in-place, got {answers.get('q1')!r}"


def test_q2_prune_kustomization(answers):
    """infra-aws (prune: true) garbage-collects the removed Buckets."""
    q2 = answers.get("q2") or {}
    assert _norm(q2.get("kustomization", "")) == "infra-aws", \
        f"q2 kustomization: expected infra-aws, got {q2.get('kustomization')!r}"
    assert "prune" in _norm(q2.get("outcome", "")), \
        f"q2 outcome: expected pruned, got {q2.get('outcome')!r}"


def test_q3_default_deletion_policy_deletes(answers):
    """No retain annotation on app-artifacts: AWS bucket is deleted."""
    assert "delet" in _norm(answers.get("q3", "")), \
        f"q3: expected deleted, got {answers.get('q3')!r}"


def test_q4_retain_annotation_orphans(answers):
    """deletion-policy: retain keeps the RDS database in AWS."""
    assert "retain" in _norm(answers.get("q4", "")), \
        f"q4: expected retained, got {answers.get('q4')!r}"


def test_q5_suspended_kustomization_applies_nothing(answers):
    """apps-prod is suspended: nothing changes in the cluster."""
    q5 = answers.get("q5") or {}
    changes = q5.get("changes")
    if isinstance(changes, str):
        changes = changes.strip().lower() in ("true", "yes")
    assert changes is False, f"q5 changes: expected false, got {q5.get('changes')!r}"
    assert "suspend" in _norm(q5.get("reason", "")), \
        f"q5 reason should mention suspend, got {q5.get('reason')!r}"


def test_q6_dependency_gate_blocks_apps_dev(answers):
    """apps-dev is gated on infra-aws readiness via dependsOn + healthChecks."""
    q6 = answers.get("q6") or {}
    rec = q6.get("apps_dev_reconciles")
    if isinstance(rec, str):
        rec = rec.strip().lower() in ("true", "yes")
    assert rec is False, \
        f"q6 apps_dev_reconciles: expected false, got {q6.get('apps_dev_reconciles')!r}"


def test_q7_reconcile_order(answers):
    """Bootstrap order follows the dependsOn chain."""
    q7 = answers.get("q7") or []
    normed = [_norm(x) for x in q7]
    assert normed == ["infra-controllers", "infra-aws", "apps-dev"], \
        f"q7: expected [infra-controllers, infra-aws, apps-dev], got {q7!r}"
