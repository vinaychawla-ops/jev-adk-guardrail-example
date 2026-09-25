# Jev Risk Guardrail for Google ADK

Use [Jev](https://typesafe.ai) (TypeSafe's specialized decision model) as a
fast, deterministic risk gate inside a Google ADK agent.

Instead of asking a general-purpose LLM "is this tool call safe?" -- slow,
chatty, and uncalibrated -- the agent's `before_tool_callback` sends the
tool-call state to Jev with one typed yes/no (`noul`) question. Jev returns a
calibrated probability, and the guardrail blocks the tool when
`P(risky) >= threshold`. No text is generated; the whole check is a single
parallel pass (~0.6-0.9s, fractions of a cent per call).

## How it works

```
user request
    -> agent picks tool, e.g. delete_customer_account(customer_id="c1")
    -> before_tool_callback (guardrail.py)
        -> Jev: "Does this tool call permanently delete data ... WITHOUT
                 explicit, verified administrator approval?"  [noul]
        -> P(yes) = 0.93 >= 0.85  -> BLOCK: tool never runs,
                                     agent receives the blocked dict
        -> P(yes) = 0.04 < 0.85   -> ALLOW: tool runs normally
```

`guardrail.make_jev_guardrail()` returns the callback. ADK's contract:
return `None` to allow the tool, return a `dict` to skip it and use the dict
as the tool's response.

## Quickstart

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=<your key>   # get one at openrouter.ai
python demo.py            # mock run, no API calls
python demo.py --live     # real Jev evaluations
pytest                    # unit tests (mocked) + live tests if key is set
```

Minimal wiring in your own agent:

```python
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from guardrail import make_jev_guardrail

agent = Agent(
    name="jev_governed_agent",
    model="gemini-2.5-flash",
    instruction="You are a CRM assistant. Process requests carefully.",
    tools=[FunctionTool(delete_customer_account)],
    before_tool_callback=make_jev_guardrail(
        guard_tools={"delete_customer_account"},
        threshold=0.85,
        fail_open=True,
    ),
)
```

See `agent.py` for the full working agent.

## Configuration

| Parameter     | Default              | Meaning |
|---------------|----------------------|---------|
| `threshold`   | `0.85`               | Block when P(risky) >= threshold |
| `guard_tools` | `{"delete_customer_account"}` in `agent.py` | Tool names evaluated by Jev; `None` = every tool. Unguarded tools skip Jev entirely (no latency/cost) |
| `fail_open`   | `True`               | Jev outage -> allow (log warning) vs block (`False` = fail-closed) |
| `model`       | `typesafe/jev-1.13`  | Pinned Jev version for stability |

## Jev API notes

- Endpoint is `POST https://openrouter.ai/api/alpha/decisions` -- the
  **Decisions** API, not `/api/v1/chat/completions`. Chat SDKs will not work.
- Request: `{"model": ..., "state": <string|object>, "questions": {...}}`.
- A `noul` answer arrives as `response["answers"][name]["noul"]` (dict access,
  not attributes).
- The client (`jev_client.py`) is stdlib-only: no dependency beyond Python 3.

## Why not just prompt an LLM?

|  | LLM safety prompt | Jev guardrail |
|---|---|---|
| Output | free text, needs parsing | typed `P(yes)` in `[0,1]` |
| Calibration | none -- "looks safe" | calibrated probability vs a threshold you set |
| Latency/cost | full generation | one scoring pass, ~$0.00002 |
| Failure mode | silent mis-parse | typed schema or explicit error -> fail-open/closed |

## Files

- `jev_client.py` -- stdlib-only Jev Decisions API client
- `guardrail.py` -- `make_jev_guardrail()`: the ADK `before_tool_callback`
- `agent.py` -- working ADK agent (`delete_customer_account` guarded, `lookup_customer` open)
- `demo.py` -- mock or `--live` end-to-end demo
- `tests/` -- mocked unit tests + live integration tests (skipped without a key)
