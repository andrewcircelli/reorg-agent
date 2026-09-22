"""The extraction regression test: the recorded real model output must match the hand-written key.
Skips until `make extract LIVE=1` has produced a recording."""
import json
from pathlib import Path

import pytest

from reorg import extract, intake, redact
from reorg.contracts import ExtractionResult
from reorg.golden import diff
from reorg.model_client import ReplayClient, ReplayMismatch


def _expected():
    raw = json.load(open("fixtures/intent_expected.json"))
    strip = lambda o: {k: strip(v) for k, v in o.items() if not k.startswith("_") and k != "occurrence"} if isinstance(o, dict) else [strip(v) for v in o] if isinstance(o, list) else o
    return ExtractionResult.model_validate(strip(raw))


def test_recorded_extraction_matches_answer_key():
    if not any(Path("fixtures/recorded").glob("*.json")):
        pytest.skip("no recording yet — run: make extract LIVE=1")
    red, _ = redact.redact(intake.capture("fixtures/msg_jordan.txt"))
    try:
        actual, _ = extract.extract(red, ReplayClient())
    except ReplayMismatch as e:
        pytest.fail(f"recording is stale for the current prompt/schema — re-record: {e}")
    assert diff(_expected(), actual) == []
