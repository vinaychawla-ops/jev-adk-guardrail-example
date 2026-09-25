"""Jev-powered risk guardrail for Google ADK agents.

Because Jev returns a calibrated probability for a typed yes/no question --
never free-form text -- it works as a fast, deterministic risk gate in front
of destructive tools, instead of a general-purpose LLM safety classifier.

Wire it in as the agent's ``before_tool_callback``::

    from guardrail import make_jev_guardrail

    agent = Agent(
        ...
        tools=[delete_customer_account, lookup_customer],
        before_tool_callback=make_jev_guardrail(
            guard_tools={"delete_customer_account"}
        ),
    )

ADK contract: a ``before_tool_callback`` receives ``(tool, args,
tool_context)``. Return ``None`` to let the tool run; return a ``dict`` to
skip the tool and use that dict as the tool's response.
"""

import json
import logging
from typing import Callable, Dict, Optional

from jev_client import JevError, decide, noul_probability

logger = logging.getLogger(__name__)

RISK_QUESTION_ID = "is_destructive_without_authorization"

RISK_QUESTION = {
    RISK_QUESTION_ID: {
        "type": "noul",
        "instructions": (
            "Does this tool call permanently delete data, destroy resources, "
            "send external communications, move money, or otherwise cause a "
            "major irreversible side effect WITHOUT explicit, verified "
            "administrator approval stated in the conversation?"
        ),
    }
}

DEFAULT_THRESHOLD = 0.85


def build_state(tool_name: str, args: dict, user_message: str = "") -> str:
    """Render the tool call as the unstructured state Jev evaluates."""
    lines = [
        f"Tool call: {tool_name}",
        f"Arguments: {json.dumps(args or {}, default=str)}",
    ]
    if user_message:
        lines.append(f"Latest user message: {user_message}")
    return "\n".join(lines)


def make_jev_guardrail(
    decide_fn: Callable = None,
    threshold: float = DEFAULT_THRESHOLD,
    guard_tools: Optional[set] = None,
    fail_open: bool = True,
    model: Optional[str] = None,
):
    """Build a ``before_tool_callback(tool, args, tool_context)`` for ADK.

    Args:
        decide_fn: Jev call ``(state, questions, model=...) ->
            (response_dict, latency_ms)``. Defaults to the real
            :func:`jev_client.decide`; inject a stub in tests.
        threshold: block when P(yes) for the risk question >= threshold.
        guard_tools: only these tool names go through Jev. ``None`` means
            every tool is evaluated (safe tools just score low).
        fail_open: if True (default), a Jev outage lets the tool run and
            logs a warning. If False, the tool is blocked instead.
        model: override the Jev model pin (default ``typesafe/jev-1.13``).
    """
    _decide = decide_fn or decide

    def jev_before_tool_callback(tool, args, tool_context):
        tool_name = getattr(tool, "name", None) or str(tool)

        if guard_tools is not None and tool_name not in guard_tools:
            return None  # not a guarded tool: no Jev call, no latency

        state = build_state(tool_name, args or {})

        try:
            kwargs = {"model": model} if model else {}
            response, _latency_ms = _decide(state, RISK_QUESTION, **kwargs)
            risk = noul_probability(response, RISK_QUESTION_ID)
        except JevError as exc:
            logger.warning("Jev risk check failed (%s); %s", exc, "allowing" if fail_open else "blocking")
            if fail_open:
                return None
            return {
                "status": "blocked",
                "reason": "risk-check-unavailable",
                "message": "Blocked: the Jev risk check was unreachable and this "
                "guardrail is configured fail-closed.",
            }

        if not 0.0 <= risk <= 1.0:
            logger.warning("Jev returned out-of-range probability %r; %s", risk, "allowing" if fail_open else "blocking")
            if fail_open:
                return None
            return {
                "status": "blocked",
                "reason": "risk-check-invalid",
                "message": "Blocked: the Jev risk check returned an invalid probability.",
            }

        if risk >= threshold:
            logger.warning("JEV BLOCK: %s P(risky)=%.3f >= threshold %.2f", tool_name, risk, threshold)
            return {
                "status": "blocked",
                "reason": "jev-risk-guardrail",
                "tool": tool_name,
                "risk_probability": risk,
                "threshold": threshold,
                "message": (
                    f"Blocked by the Jev risk guardrail: '{tool_name}' scored "
                    f"P(risky)={risk:.3f} against a threshold of {threshold:.2f}. "
                    "Ask the user for explicit administrator approval and retry."
                ),
            }

        return None  # safe: let the tool run

    return jev_before_tool_callback


# A ready-made callback using the real Jev API, guarding the destructive tool.
jev_risk_guardrail = make_jev_guardrail(guard_tools={"delete_customer_account"})
