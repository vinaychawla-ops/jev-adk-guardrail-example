"""Tests for audit logging: the log itself plus guardrail wiring."""

import json
import os
from types import SimpleNamespace

from audit import AuditLog, prompt_hash, prompt_preview
from guardrail import RISK_QUESTION_ID, make_jev_guardrail
from jev_client import JevError

QID = RISK_QUESTION_ID


def stub_decide(probability=None, exc=None):
    def _fake(state, questions, model=None):
        if exc is not None:
            raise exc
        return {"answers": {QID: {"type": "noul", "noul": probability}}}, 5.0

    return _fake


def tool(name):
    return SimpleNamespace(name=name)


# --- AuditLog core -----------------------------------------------------------


def test_record_stamps_ts_and_appends():
    log = AuditLog()
    evt = log.record({"component": "guardrail", "verdict": "blocked"})
    assert evt["ts"]  # ISO timestamp added
    assert len(log) == 1
    assert log.events[0]["verdict"] == "blocked"


def test_jsonl_sink_writes_parseable_lines(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLog(path=path)
    log.record({"component": "guardrail", "verdict": "allowed", "p_risky": 0.1})
    log.record({"component": "guardrail", "verdict": "blocked", "p_risky": 0.9})
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) == 2
    assert lines[0]["verdict"] == "allowed"
    assert lines[1]["p_risky"] == 0.9
    assert all("ts" in e for e in lines)


def test_summary_counts_by_verdict():
    log = AuditLog()
    log.record({"verdict": "allowed"})
    log.record({"verdict": "allowed"})
    log.record({"verdict": "blocked"})
    assert log.summary() == {"total": 3, "by_verdict": {"allowed": 2, "blocked": 1}}


def test_prompt_preview_truncates_and_hash_is_stable():
    long_prompt = "x" * 500
    assert len(prompt_preview(long_prompt)) == 200
    assert prompt_preview("short") == "short"
    assert prompt_hash("abc") == prompt_hash("abc")
    assert prompt_hash("abc") != prompt_hash("abd")
    assert len(prompt_hash("abc")) == 16


# --- guardrail wiring --------------------------------------------------------


def test_blocked_decision_is_audited():
    log = AuditLog()
    cb = make_jev_guardrail(decide_fn=stub_decide(0.93), guard_tools={"delete_customer_account"}, audit=log)
    cb(tool("delete_customer_account"), {"customer_id": "c1"}, None)
    assert len(log) == 1
    evt = log.events[0]
    assert evt["component"] == "guardrail"
    assert evt["verdict"] == "blocked"
    assert evt["tool"] == "delete_customer_account"
    assert evt["args"] == {"customer_id": "c1"}
    assert evt["p_risky"] == 0.93
    assert evt["threshold"] == 0.85
    assert evt["jev_model"] == "typesafe/jev-1.13"
    assert evt["latency_ms"] == 5.0


def test_allowed_decision_is_audited():
    log = AuditLog()
    cb = make_jev_guardrail(decide_fn=stub_decide(0.04), guard_tools=None, audit=log)
    assert cb(tool("lookup_customer"), {}, None) is None
    assert log.events[0]["verdict"] == "allowed"
    assert log.events[0]["p_risky"] == 0.04


def test_fallback_is_audited_with_reason():
    log = AuditLog()
    cb = make_jev_guardrail(decide_fn=stub_decide(exc=JevError("timeout")), guard_tools=None, audit=log)
    assert cb(tool("delete_customer_account"), {}, None) is None
    evt = log.events[0]
    assert evt["verdict"] == "allowed-fallback"
    assert "timeout" in evt["reason"]


def test_skipped_tool_is_audited_without_jev_call():
    log = AuditLog()
    cb = make_jev_guardrail(decide_fn=stub_decide(0.99), guard_tools={"delete_customer_account"}, audit=log)
    assert cb(tool("lookup_customer"), {}, None) is None
    assert log.events[0]["verdict"] == "skipped"


def test_no_audit_log_means_no_overhead():
    # audit=None (default) must keep working exactly as before
    cb = make_jev_guardrail(decide_fn=stub_decide(0.93), guard_tools={"delete_customer_account"})
    assert cb(tool("delete_customer_account"), {}, None)["status"] == "blocked"
