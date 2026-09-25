"""Stdlib-only client for TypeSafe Jev via OpenRouter's Decisions API.

Jev is NOT a chat model: you POST a ``state`` plus typed, bounded questions
to ``https://openrouter.ai/api/alpha/decisions`` and get back calibrated
probabilities -- no generated text.

Question types::

    {"name": {"type": "noul", "instructions": "..."}}
        -> answers["name"]["noul"] = P(yes), a float in [0, 1]
    {"name": {"type": "choice", "instructions": "...",
              "criteria": {"opt_a": "description", ...}}}
        -> answers["name"]["choice"], plus per-option probabilities
    {"name": {"type": "score", "instructions": "...",
              "criteria": ["level 0", "level 1", ...]}}
        -> answers["name"]["score"], plus per-level probabilities

Auth: inside Muse the stored ``custom.openrouter`` credential is attached via
an authd surrogate (no raw key anywhere). Everywhere else, set
``OPENROUTER_API_KEY``.
"""

import json
import os
import time
import urllib.request

try:
    sys_path = "/opt/hatch/skills/skill-creator/bin"
    import sys as _sys

    if sys_path not in _sys.path:
        _sys.path.insert(0, sys_path)
    from dynamic_credentials import add_surrogate_to_request, read_json_response

    _HAVE_VAULT = True
except ImportError:  # plain local run
    _HAVE_VAULT = False

    def read_json_response(resp):  # type: ignore[no-redef]
        return json.loads(resp.read().decode("utf-8"))


API_URL = "https://openrouter.ai/api/alpha/decisions"
ALLOWED_HOSTS = ("openrouter.ai",)
MODEL = "typesafe/jev-1.13"  # pinned; the API also accepts typesafe/jev-latest


class JevError(Exception):
    """Raised when the Jev request cannot be completed or parsed."""


def decide(state, questions, model=MODEL):
    """Send one Jev evaluation; return ``(response_dict, latency_ms)``.

    ``state`` is unstructured (a string, or a JSON-serializable object).
    ``questions`` maps names to typed question dicts (see module docstring).
    """
    payload = {"model": model, "state": state, "questions": questions}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if _HAVE_VAULT and not os.environ.get("OPENROUTER_API_KEY"):
        add_surrogate_to_request(req, "custom.openrouter", allowed_hosts=ALLOWED_HOSTS)
    else:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise JevError("set OPENROUTER_API_KEY to call Jev (or run inside Muse)")
        req.add_header("Authorization", f"Bearer {key}")

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = read_json_response(resp)
    except JevError:
        raise
    except Exception as exc:
        raise JevError(f"request failed: {exc}") from exc
    latency_ms = (time.perf_counter() - t0) * 1000

    if isinstance(data, dict) and "error" in data:
        raise JevError(f"api error: {json.dumps(data['error'])}")
    if not isinstance(data, dict) or "answers" not in data:
        raise JevError(f"unexpected response shape: {str(data)[:200]}")
    return data, latency_ms


def noul_probability(response, question_name):
    """Extract P(yes) for a ``noul`` question; raises JevError if missing."""
    try:
        return float(response["answers"][question_name]["noul"])
    except (KeyError, TypeError, ValueError) as exc:
        raise JevError(f"no noul answer for {question_name!r}: {exc}") from exc
