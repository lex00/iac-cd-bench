"""Semantic-understanding quiz grader — pulumi-typescript T6."""

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


def _as_bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes")
    return v


def test_q1_output_concat_footgun(answers):
    """String + Output<string> yields the Output repr, not the value."""
    q1 = answers.get("q1") or {}
    assert "output" in _norm(q1.get("contains", "")), \
        f"q1 contains: expected output-repr, got {q1.get('contains')!r}"
    assert "output" in _norm(q1.get("type", "")), \
        f"q1 type: expected Output<string>, got {q1.get('type')!r}"


def test_q2_protect_blocks_destroy(answers):
    """protect: true on artifacts blocks pulumi destroy."""
    q2 = answers.get("q2") or {}
    assert _as_bool(q2.get("completes")) is False, \
        f"q2 completes: expected false, got {q2.get('completes')!r}"
    assert "artifact" in _norm(q2.get("blocking_resource", "")), \
        f"q2 blocking_resource: expected artifacts, got {q2.get('blocking_resource')!r}"


def test_q3_delete_before_replace_order_and_risk(answers):
    """deleteBeforeReplace deletes first; risk is a downtime window."""
    q3 = answers.get("q3") or {}
    assert "delete-then-create" in _norm(q3.get("order", "")), \
        f"q3 order: expected delete-then-create, got {q3.get('order')!r}"
    risk = _norm(q3.get("risk", ""))
    assert any(w in risk for w in ("downtime", "gap", "unavailable", "outage", "loss", "window", "exist")), \
        f"q3 risk should mention the availability window, got {q3.get('risk')!r}"


def test_q4_secret_export_masked(answers):
    """Secret exports stay masked without --show-secrets."""
    assert "mask" in _norm(answers.get("q4", "")), \
        f"q4: expected masked, got {answers.get('q4')!r}"


def test_q5_getnumber_default(answers):
    """getNumber returns undefined -> ?? 30 applies; no runtime error."""
    q5 = answers.get("q5") or {}
    try:
        value = int(q5.get("value"))
    except (TypeError, ValueError):
        value = None
    assert value == 30, f"q5 value: expected 30, got {q5.get('value')!r}"
    assert _as_bool(q5.get("error")) is False, \
        f"q5 error: expected false, got {q5.get('error')!r}"


def test_q6_rename_replaces_aliases_fix(answers):
    """Logical rename = replace; aliases option makes it a no-op."""
    q6 = answers.get("q6") or {}
    assert "replace" in _norm(q6.get("plan", "")), \
        f"q6 plan: expected replace, got {q6.get('plan')!r}"
    assert "alias" in _norm(q6.get("fix_option", "")), \
        f"q6 fix_option: expected aliases, got {q6.get('fix_option')!r}"


def test_q7_arn_unknown_at_preview(answers):
    """Fresh-stack preview leaves the applied ARN unknown."""
    assert "unknown" in _norm(answers.get("q7", "")), \
        f"q7: expected unknown, got {answers.get('q7')!r}"
