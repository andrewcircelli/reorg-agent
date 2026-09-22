"""The seam, on its bad days. A call that returns is not the same as an extraction.

Four outcomes have to be told apart, because each needs a different human response:
  the contract rejected the answer   → ExtractionRejected, carrying what the model actually said
  the model refused                  → arrives as invalid JSON (the SDK validates before we see
                                       stop_reason), so it lands in the same family, with the prose
  the output was truncated           → same path, with the partial JSON
  a parseable response, no output    → ExtractionUnavailable

No network: LiveClient is built without __init__ and handed a stub whose messages.parse() stands in
for the SDK's. That stub is the only fiction here — everything downstream of it is the real code.
"""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from reorg.contracts import ExtractionResult
from reorg.model_client import (SCHEMA_SHA256, SCHEMA_VERSION, ExtractionRejected,
                                ExtractionUnavailable, LiveClient, recording_key, sha256_of)

GOOD = {"effective_date": {"entity_type": "date", "mention": "Oct 1", "source_span": [0, 5]},
        "changes": []}


def live(parse):
    """A LiveClient with the SDK swapped out. __init__ is skipped on purpose: it wants an API key."""
    c = LiveClient.__new__(LiveClient)
    c.model = "stub-model"
    c._client = SimpleNamespace(messages=SimpleNamespace(parse=parse))
    return c


def raises_validation(payload):
    """What the SDK does on a bad response: TypeAdapter(...).validate_json inside messages.parse."""
    from anthropic._models import TypeAdapter

    def parse(**kwargs):
        TypeAdapter(ExtractionResult).validate_json(payload)
        raise AssertionError("payload should not have validated")
    return parse


def responds(**fields):
    fields.setdefault("model", "stub-model")
    fields.setdefault("usage", SimpleNamespace(model_dump=lambda: {"input_tokens": 1}))
    fields.setdefault("stop_details", None)
    return lambda **kwargs: SimpleNamespace(**fields)


# ---- the contract rejects the answer, and says what the model sent --------------------------------
def test_contract_violation_is_reported_with_the_models_own_words():
    payload = ('{"effective_date": {"entity_type": "date", "mention": "Oct 1", "source_span": [0,5]},'
               ' "changes": [{"kind": "COMP_CHANGE", "fields": [{"name": "worker", "entity_type":'
               ' "worker", "mention": "Sam", "source_span": [1,4], "unresolved": true,'
               ' "question": "which Sam?"}]}]}')
    with pytest.raises(ExtractionRejected) as exc:
        live(raises_validation(payload)).extract("sys", "msg")
    msg = str(exc.value)
    assert "cited or unresolved, not both" in msg, "the violated rule must be named"
    assert "which Sam?" in msg, "the model's own output must come back for the prompt loop"


def test_a_refusal_is_not_an_empty_extraction():
    with pytest.raises(ExtractionUnavailable) as exc:
        live(raises_validation("I can't help with that request.")).extract("sys", "msg")
    assert "I can't help with that request." in str(exc.value)


def test_a_truncated_response_is_not_a_partial_extraction():
    with pytest.raises(ExtractionUnavailable) as exc:
        live(raises_validation('{"effective_date": {"entity_type": "da')).extract("sys", "msg")
    assert "Invalid JSON" in str(exc.value)


def test_an_unrelated_error_is_not_swallowed():
    """Only response-validation failures become ExtractionRejected; a transport error propagates."""
    def parse(**kwargs):
        raise TimeoutError("connection reset")
    with pytest.raises(TimeoutError):
        live(parse).extract("sys", "msg")


# ---- a parseable response that still is not an extraction ----------------------------------------
def test_stop_reason_guards_fire_when_the_response_did_parse():
    result = ExtractionResult.model_validate(GOOD)
    for stop_reason, expected in [("refusal", "declined"), ("max_tokens", "truncated")]:
        with pytest.raises(ExtractionUnavailable, match=expected):
            live(responds(stop_reason=stop_reason, parsed_output=result)).extract("sys", "msg")


def test_no_parsed_output_is_never_read_as_an_empty_result():
    with pytest.raises(ExtractionUnavailable, match="no parsed output"):
        live(responds(stop_reason="end_turn", parsed_output=None)).extract("sys", "msg")


# ---- the good path still binds the recording to input + prompt + schema --------------------------
def test_a_good_response_is_recorded_against_its_input_and_prompt():
    result = ExtractionResult.model_validate(GOOD)
    got, meta = live(responds(stop_reason="end_turn", parsed_output=result)).extract("sys", "msg")
    assert got == result
    assert meta["key"] == recording_key("sys", "msg") != recording_key("sys", "other msg")
    assert meta["input_sha256"] == sha256_of("msg")
    assert meta["prompt_sha256"] == sha256_of("sys")
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["schema_sha256"] == SCHEMA_SHA256, "the recording must bind to the schema itself"
    assert meta["raw"] == result.model_dump(mode="json"), "the recording holds the whole result"
