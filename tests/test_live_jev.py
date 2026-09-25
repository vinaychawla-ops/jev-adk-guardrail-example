"""Live integration test: hits the real Jev Decisions API.

Skipped unless Jev is reachable -- either ``OPENROUTER_API_KEY`` is set
(local runs) or the Muse vault surrogate is importable (sandbox runs).
Never commits or prints any credential.
"""

import os

import pytest

from guardrail import RISK_QUESTION_ID, make_jev_guardrail


def _jev_reachable():
    if os.environ.get("OPENROUTER_API_KEY"):
        return True
    try:
        import sys

        sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
        import dynamic_credentials  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _jev_reachable(), reason="Jev not reachable: set OPENROUTER_API_KEY")


def test_live_jev_scores_delete_customer_account_high_risk():
    from types import SimpleNamespace

    from jev_client import decide

    cb = make_jev_guardrail(decide_fn=decide, guard_tools={"delete_customer_account"})
    verdict = cb(SimpleNamespace(name="delete_customer_account"), {"customer_id": "cust_live"}, None)
    assert verdict is not None, "expected live Jev to flag account deletion as risky"
    assert verdict["status"] == "blocked"
    p = verdict["risk_probability"]
    assert 0.0 <= p <= 1.0
    print(f"\nlive Jev P(risky | delete_customer_account) = {p:.3f}")


def test_live_jev_response_shape():
    from jev_client import decide
    from guardrail import RISK_QUESTION, build_state

    state = build_state("lookup_customer", {"customer_id": "cust_live"})
    resp, ms = decide(state, RISK_QUESTION)
    p = resp["answers"][RISK_QUESTION_ID]["noul"]
    assert isinstance(p, float) and 0.0 <= p <= 1.0
    assert ms > 0
    print(f"\nlive Jev P(risky | lookup_customer) = {p:.3f} ({ms:.0f} ms)")
