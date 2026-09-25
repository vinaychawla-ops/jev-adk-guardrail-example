#!/usr/bin/env python3
"""Demo the Jev ADK guardrail without (or with) live API calls.

Default: scripted stand-in for Jev shows the allow/block paths end to end.
Live:   python demo.py --live   (needs OPENROUTER_API_KEY, or run inside Muse)
"""

import argparse
import json
import sys
from types import SimpleNamespace

from guardrail import make_jev_guardrail

MOCK_P = {"delete_customer_account": 0.93, "lookup_customer": 0.04}


def mock_decide(state, questions, **kwargs):
    tool_name = state.splitlines()[0].split("Tool call: ")[1]
    p = MOCK_P.get(tool_name, 0.5)
    return ({"answers": {"is_destructive_without_authorization": {"type": "noul", "noul": p}}}, 3.0)


def run(callback, label):
    print(f"\n--- {label} ---")
    scenarios = [
        ("delete_customer_account", {"customer_id": "cust_123"}),
        ("lookup_customer", {"customer_id": "cust_123"}),
    ]
    for tool_name, args in scenarios:
        tool = SimpleNamespace(name=tool_name)
        verdict = callback(tool, args, None)
        if verdict is None:
            print(f"  ALLOWED  {tool_name}{args} -> tool would run")
        else:
            print(f"  BLOCKED  {tool_name}{args}")
            print(f"           P(risky)={verdict['risk_probability']:.3f} >= {verdict['threshold']:.2f}")
            print(f"           agent sees: {json.dumps(verdict)[:120]}...")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="call the real Jev API")
    ns = ap.parse_args()

    if ns.live:
        callback = make_jev_guardrail(guard_tools={"delete_customer_account"})
        run(callback, "LIVE Jev (typesafe/jev-1.13 via OpenRouter Decisions API)")
    else:
        callback = make_jev_guardrail(decide_fn=mock_decide, guard_tools={"delete_customer_account"})
        run(callback, "MOCK Jev (no API calls)")
        print("\nTip: re-run with --live to evaluate the same calls with real Jev.")


if __name__ == "__main__":
    sys.exit(main())
