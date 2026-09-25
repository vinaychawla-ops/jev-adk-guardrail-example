"""Tests for the Jev ADK guardrail (Jev itself is stubbed; no network)."""

from types import SimpleNamespace

import pytest

from guardrail import (
    DEFAULT_THRESHOLD,
    RISK_QUESTION,
    RISK_QUESTION_ID,
    build_state,
    make_jev_guardrail,
)
from jev_client import JevError

QID = RISK_QUESTION_ID


def tool(name):
    return SimpleNamespace(name=name)


def stub_decide(probability=None, exc=None, error_body=None):
    """Build a fake decide_fn. Captures (state, questions, model) per call."""
    calls = []

    def _fake(state, questions, model=None):
        calls.append({"state": state, "questions": questions, "model": model})
        if exc is not None:
            raise exc
        body = error_body if error_body is not None else {
            "answers": {QID: {"type": "noul", "noul": probability}}
        }
        return body, 5.0

    _fake.calls = calls
    return _fake


# --- allow / block paths -----------------------------------------------------


def test_high_risk_blocks_with_probability():
    cb = make_jev_guardrail(decide_fn=stub_decide(0.93), guard_tools={"delete_customer_account"})
    verdict = cb(tool("delete_customer_account"), {"customer_id": "c1"}, None)
    assert verdict is not None
    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "jev-risk-guardrail"
    assert verdict["risk_probability"] == pytest.approx(0.93)
    assert verdict["threshold"] == DEFAULT_THRESHOLD
    assert "delete_customer_account" in verdict["message"]


def test_low_risk_allows():
    fake = stub_decide(0.12)
    cb = make_jev_guardrail(decide_fn=fake, guard_tools={"delete_customer_account"})
    assert cb(tool("delete_customer_account"), {"customer_id": "c1"}, None) is None
    assert len(fake.calls) == 1


def test_threshold_boundary_blocks_at_exactly_threshold():
    cb = make_jev_guardrail(decide_fn=stub_decide(DEFAULT_THRESHOLD), guard_tools=None)
    assert cb(tool("delete_customer_account"), {}, None)["status"] == "blocked"


def test_just_below_threshold_allows():
    cb = make_jev_guardrail(decide_fn=stub_decide(DEFAULT_THRESHOLD - 0.0001), guard_tools=None)
    assert cb(tool("delete_customer_account"), {}, None) is None


def test_custom_threshold():
    cb = make_jev_guardrail(decide_fn=stub_decide(0.6), threshold=0.5, guard_tools=None)
    assert cb(tool("anything"), {}, None)["status"] == "blocked"


def test_unguarded_tool_skips_jev_entirely():
    fake = stub_decide(0.99)  # would block if it were called
    cb = make_jev_guardrail(decide_fn=fake, guard_tools={"delete_customer_account"})
    assert cb(tool("lookup_customer"), {"customer_id": "c1"}, None) is None
    assert fake.calls == []  # no API call, no latency for safe tools


def test_guard_all_tools_when_guard_tools_is_none():
    fake = stub_decide(0.99)
    cb = make_jev_guardrail(decide_fn=fake, guard_tools=None)
    assert cb(tool("lookup_customer"), {}, None)["status"] == "blocked"
    assert len(fake.calls) == 1


# --- failure modes -----------------------------------------------------------


def test_fail_open_on_jev_outage_allows(caplog):
    cb = make_jev_guardrail(decide_fn=stub_decide(exc=JevError("timeout")), fail_open=True, guard_tools=None)
    with caplog.at_level("WARNING"):
        assert cb(tool("delete_customer_account"), {}, None) is None
    assert "Jev risk check failed" in caplog.text


def test_fail_closed_on_jev_outage_blocks():
    cb = make_jev_guardrail(decide_fn=stub_decide(exc=JevError("timeout")), fail_open=False, guard_tools=None)
    verdict = cb(tool("delete_customer_account"), {}, None)
    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "risk-check-unavailable"


def test_malformed_response_fails_open():
    cb = make_jev_guardrail(decide_fn=stub_decide(error_body={"nope": True}), fail_open=True, guard_tools=None)
    assert cb(tool("delete_customer_account"), {}, None) is None


def test_malformed_response_fails_closed():
    cb = make_jev_guardrail(decide_fn=stub_decide(error_body={"nope": True}), fail_open=False, guard_tools=None)
    verdict = cb(tool("delete_customer_account"), {}, None)
    assert verdict["status"] == "blocked"


def test_out_of_range_probability_fails_open():
    cb = make_jev_guardrail(decide_fn=stub_decide(1.5), fail_open=True, guard_tools=None)
    assert cb(tool("delete_customer_account"), {}, None) is None


# --- Jev request shape -------------------------------------------------------


def test_state_contains_tool_name_and_args():
    fake = stub_decide(0.1)
    cb = make_jev_guardrail(decide_fn=fake, guard_tools=None)
    cb(tool("delete_customer_account"), {"customer_id": "cust_9"}, None)
    state = fake.calls[0]["state"]
    assert "delete_customer_account" in state
    assert "cust_9" in state


def test_question_is_typed_noul_yes_no():
    fake = stub_decide(0.1)
    cb = make_jev_guardrail(decide_fn=fake, guard_tools=None)
    cb(tool("delete_customer_account"), {}, None)
    questions = fake.calls[0]["questions"]
    assert set(questions) == {QID}
    assert questions[QID]["type"] == "noul"
    assert "instructions" in questions[QID] and questions[QID]["instructions"].strip()


def test_build_state_includes_user_message_when_given():
    s = build_state("delete_customer_account", {"customer_id": "c1"}, "please wipe everything")
    assert "delete_customer_account" in s and "c1" in s and "wipe everything" in s


def test_blocked_dict_is_usable_as_tool_response():
    """ADK uses the returned dict as the tool's response: it must be JSON-safe."""
    import json

    cb = make_jev_guardrail(decide_fn=stub_decide(0.91), guard_tools=None)
    verdict = cb(tool("delete_customer_account"), {"customer_id": "c1"}, None)
    json.dumps(verdict)  # must not raise
    assert verdict["status"] == "blocked"
