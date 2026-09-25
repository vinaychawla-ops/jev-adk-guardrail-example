"""Tests for the stdlib Jev Decisions API client (all HTTP mocked)."""

import io
import json
import os
from unittest import mock

import pytest

import jev_client
from jev_client import JevError, decide, noul_probability


def _fake_urlopen(captured, body):
    def _fake(req, timeout=60):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode("utf-8"))

        class _Resp:
            def __init__(self):
                self._raw = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
                self._sent = False

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                if self._sent:
                    return b""
                self._sent = True
                return self._raw if n is None or n < 0 else self._raw[:n]

        return _Resp()

    return _fake


NOUL_BODY = {
    "answers": {"is_destructive_without_authorization": {"type": "noul", "noul": 0.93}},
    "usage": {"input_tokens": 40, "output_tokens": 2, "cost": 0.000018},
    "provider": "typesafe",
    "model": "typesafe/jev-1.13",
}


def test_posts_to_decisions_endpoint_with_bearer_auth():
    captured = {}
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key-123"}), mock.patch(
        "urllib.request.urlopen", _fake_urlopen(captured, NOUL_BODY)
    ):
        resp, ms = decide("some state", {"q": {"type": "noul", "instructions": "yes?"}})

    assert captured["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert captured["headers"]["Authorization"] == "Bearer test-key-123"
    assert captured["payload"]["model"] == "typesafe/jev-1.13"
    assert captured["payload"]["state"] == "some state"
    assert captured["payload"]["questions"]["q"]["type"] == "noul"
    assert resp["answers"]["is_destructive_without_authorization"]["noul"] == 0.93
    assert ms >= 0


def test_model_override_is_sent():
    captured = {}
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), mock.patch(
        "urllib.request.urlopen", _fake_urlopen(captured, NOUL_BODY)
    ):
        decide("s", {"q": {"type": "noul", "instructions": "?"}} , model="typesafe/jev-latest")
    assert captured["payload"]["model"] == "typesafe/jev-latest"


def test_missing_key_raises_jev_error():
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENROUTER_API_KEY", None)
        # force the non-vault path even inside Muse
        with mock.patch.object(jev_client, "_HAVE_VAULT", False):
            with pytest.raises(JevError, match="OPENROUTER_API_KEY"):
                decide("s", {"q": {"type": "noul", "instructions": "?"}})


def test_api_error_body_raises_jev_error():
    captured = {}
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}), mock.patch(
        "urllib.request.urlopen", _fake_urlopen(captured, {"error": {"message": "bad model"}})
    ):
        with pytest.raises(JevError, match="api error"):
            decide("s", {"q": {"type": "noul", "instructions": "?"}})


def test_noul_probability_extracts_p_yes():
    assert noul_probability(NOUL_BODY, "is_destructive_without_authorization") == 0.93


def test_noul_probability_missing_answer_raises():
    with pytest.raises(JevError):
        noul_probability({"answers": {}}, "is_destructive_without_authorization")
