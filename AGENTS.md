# AGENTS.md -- jev-adk-guardrail-example

## What this repo is
A minimal, working example of TypeSafe's Jev decision model acting as a risk
guardrail inside a Google ADK agent's `before_tool_callback`. Public demo repo.

## Conventions
- `jev_client.py` stays **stdlib-only** (urllib, no requests/httpx). Keep it that way.
- Jev model is pinned to `typesafe/jev-1.13` in `jev_client.MODEL`. Only change
  the pin deliberately and note it in the README.
- Never commit API keys. Auth is `OPENROUTER_API_KEY` env var locally; inside
  Muse the `custom.openrouter` vault surrogate is used (see `jev_client.py`).
- Tests must run with zero network by default. Live API tests live in
  `tests/test_live_jev.py` and skip when Jev is unreachable.

## ADK callback contract (do not break)
`before_tool_callback(tool, args, tool_context)`:
- return `None` -> tool runs normally
- return a `dict` -> tool is SKIPPED and the dict becomes the tool response
- tools are wrapped in `FunctionTool` in `agent.py` so callbacks fire on all ADK versions

## Jev API facts (verified, don't regress)
- Endpoint: `POST https://openrouter.ai/api/alpha/decisions` (NOT chat/completions)
- Payload: `{"model", "state", "questions"}`; questions are typed:
  `{"name": {"type": "noul", "instructions": "..."}}`
- Answers are dicts: `resp["answers"][name]["noul"]` -> float P(yes). Not attributes.
- `state` may be a plain string; `build_state()` renders the tool call as one.

## Running
- `python demo.py` -- mock demo, no keys
- `python demo.py --live` -- real Jev (needs `OPENROUTER_API_KEY` or Muse vault)
- `pytest -q` -- full suite; live tests skip without a key
- `pytest -q tests/test_guardrail.py tests/test_jev_client.py` -- offline only

## Observability
- `audit.py` provides `AuditLog`: in-memory `events` list plus an optional
  JSONL file (`AuditLog(path="audit.jsonl")`, one line per decision).
- Pass `audit=` to `make_jev_guardrail()`; every callback records one event:
  `ts`, `component="guardrail"`, `jev_model`, `tool`, `args`, `question_id`,
  `p_risky`, `threshold`, `latency_ms`, and `verdict` in
  {allowed, blocked, skipped, allowed-fallback, blocked-fallback} with a
  `reason` on fallbacks. Skipped tools are logged even though Jev isn't called.
- `audit.summary()` -> `{"total": n, "by_verdict": {...}}`.
- `demo.py --audit PATH` exercises the full audit path end to end.
- No credentials are ever recorded. `audit=None` (default) keeps zero overhead.

## Deploy notes
- Default is `fail_open=True` (Jev outage -> allow + warning). Production
  destructive tools should consider `fail_open=False`.
- Tune `threshold` per tool sensitivity; 0.85 is the demo default.
- `guard_tools=None` evaluates every tool (cost/latency per call); prefer an
  explicit set of destructive tools.
