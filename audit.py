"""Audit logging for every Jev decision: calls made, outcomes, and fallbacks.

Two sinks:
- in-memory ``events`` list (inspect in-process; handy in tests)
- optional JSONL file (``AuditLog(path="audit.jsonl")``) for a persistent,
  line-per-decision audit trail you can grep, ship, or load into a dataframe

Every event is a JSON-serializable dict with a UTC timestamp. User prompts
are stored as a truncated preview plus a SHA-256 hash -- enough to audit
what was decided and correlate repeat prompts, without turning the log into
a full prompt store. Credentials are never recorded.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

PROMPT_PREVIEW_CHARS = 200


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prompt_preview(prompt: str, chars: int = PROMPT_PREVIEW_CHARS) -> str:
    return (prompt or "")[:chars]


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:16]


class AuditLog:
    """Collects Jev decision events in memory and/or a JSONL file."""

    def __init__(self, path: str = None):
        self.events = []
        self.path = path

    def record(self, event: dict) -> dict:
        """Stamp an event with ``ts``, store it, and append it to the JSONL
        file if one was configured. Returns the stamped event."""
        evt = {"ts": utc_now_iso(), **event}
        self.events.append(evt)
        if self.path:
            directory = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(directory, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(evt, default=str) + "\n")
        return evt

    def summary(self) -> dict:
        """Counts per verdict, e.g. ``{'total': 10, 'by_verdict':
        {'allowed': 6, 'blocked': 3, 'allowed-fallback': 1}}``."""
        by_verdict = {}
        for e in self.events:
            v = e.get("verdict", "unknown")
            by_verdict[v] = by_verdict.get(v, 0) + 1
        return {"total": len(self.events), "by_verdict": by_verdict}

    def __len__(self):
        return len(self.events)
