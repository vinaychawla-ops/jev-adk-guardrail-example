"""ADK agent wired with the Jev risk guardrail.

``delete_customer_account`` is destructive, so every call to it is evaluated
by Jev in ``before_tool_callback`` before it may run. ``lookup_customer`` is
read-only and passes straight through.

Run ``python demo.py`` to see the guardrail allow/block without needing API
keys. A live run needs ``OPENROUTER_API_KEY`` (Jev) and ``GOOGLE_API_KEY``
(the agent's Gemini model).
"""

from guardrail import make_jev_guardrail

try:
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    _HAVE_ADK = True
except ImportError:  # pragma: no cover - lets tests import without google-adk
    _HAVE_ADK = False


def delete_customer_account(customer_id: str) -> dict:
    """Permanently delete a customer account and all associated data."""
    return {"status": "deleted", "customer_id": customer_id}


def lookup_customer(customer_id: str) -> dict:
    """Look up a customer account. Read-only; no side effects."""
    return {"status": "found", "customer_id": customer_id}


# The guardrail itself. Swap fail_open=False for production fail-closed
# behavior, and tune the threshold to your risk tolerance.
jev_before_tool_callback = make_jev_guardrail(
    guard_tools={"delete_customer_account"},
    threshold=0.85,
    fail_open=True,
)

if _HAVE_ADK:
    # FunctionTool wrapping guarantees before_tool_callback fires for these
    # tools on every ADK version.
    root_agent = Agent(
        name="jev_governed_agent",
        model="gemini-2.5-flash",
        instruction="You are a CRM assistant. Process requests carefully.",
        tools=[
            FunctionTool(delete_customer_account),
            FunctionTool(lookup_customer),
        ],
        before_tool_callback=jev_before_tool_callback,
    )
else:  # pragma: no cover
    root_agent = None
