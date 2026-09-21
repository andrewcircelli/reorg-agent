"""Contract tests (review A1/A2/B4). The model-facing schema cannot carry workflow state; malformed
fields fail closed; spans must lie inside the exact text; replay is bound to its input."""
import json

import pytest
from pydantic import ValidationError

from reorg.contracts import (ChangeKind, ExtractedChange, ExtractedField, ExtractionResult,
                             ReorgIntent, missing_required, sha256_of, validate_spans)
from reorg.model_client import ReplayClient, ReplayMismatch, recording_key, record


def cited(t="worker", m="Sam", span=(0, 3), **kw):
    return ExtractedField(entity_type=t, mention=m, source_span=list(span), **kw)


def _property_names(schema, acc=None):
    acc = set() if acc is None else acc
    if isinstance(schema, dict):
        acc.update(schema.get("properties", {}).keys())
        for v in schema.values():
            _property_names(v, acc)
    elif isinstance(schema, list):
        for v in schema:
            _property_names(v, acc)
    return acc


def test_model_schema_has_no_workflow_state():
    names = _property_names(ExtractionResult.model_json_schema())
    for forbidden in ("status", "resolved_id", "resolved_ids", "candidates", "source_id", "id"):
        assert forbidden not in names, f"model-facing schema must not carry '{forbidden}'"
    assert names == {"changes", "effective_date", "entity_type", "fields", "kind", "mention",
                     "notes", "quantity", "question", "source_span", "unresolved"}


@pytest.mark.parametrize("kwargs", [
    dict(entity_type="worker"),                                            # empty
    dict(entity_type="worker", unresolved=True),                           # unresolved, no question
    dict(entity_type="worker", mention="Sam"),                             # cited, no span
    dict(entity_type="worker", mention="Sam", source_span=[5, 2]),         # reversed span
    dict(entity_type="worker", mention="Sam", source_span=[-2, 3]),        # negative
    dict(entity_type="worker", mention="Sam", source_span=[0, 3], unresolved=True, question="?"),  # both
])
def test_malformed_fields_fail_closed(kwargs):
    with pytest.raises(ValidationError):
        ExtractedField(**kwargs)


def test_unresolved_and_cited_shapes_are_valid():
    ExtractedField(entity_type="cost_center", unresolved=True, question="Split into which cost center?")
    cited("req", "2 open reqs", (10, 21), quantity=2)


def test_unknown_field_name_rejected():
    with pytest.raises(ValidationError):
        ExtractedChange(kind=ChangeKind.MANAGER_CHANGE, fields={"boss": cited()})


def test_wrong_entity_type_for_field_rejected():
    with pytest.raises(ValidationError):
        ExtractedChange(kind=ChangeKind.MANAGER_CHANGE, fields={"worker": cited(t="org")})


def test_missing_required_is_detected_not_silent():
    ch = ExtractedChange(kind=ChangeKind.TEAM_MOVE, fields={"team": cited("org", "Data Platform", (0, 13))})
    assert missing_required(ch) == ["to_org | to_leader"]


def test_span_beyond_text_fails_closed():
    r = ExtractionResult(effective_date=cited("date", "Oct 1", (0, 5)), changes=[])
    validate_spans(r, "Oct 1 move")
    with pytest.raises(ValueError):
        validate_spans(r, "Oct")


def test_intent_is_minted_by_app_code_with_draft_status():
    r = ExtractionResult(effective_date=cited("date", "Oct 1", (0, 5)), changes=[])
    i = ReorgIntent.from_extraction(r, source_id="src_x", sent_at="2026-09-21")
    assert i.status == "DRAFT" and i.id.startswith("intent_")


def test_fingerprint_ignores_status_and_id_but_not_content():
    r = ExtractionResult(effective_date=cited("date", "Oct 1", (0, 5)), changes=[])
    a = ReorgIntent.from_extraction(r, "src_x", "2026-09-21")
    b = a.model_copy(update={"status": "APPROVED", "id": "intent_other"})
    assert a.fingerprint() == b.fingerprint()
    c = a.model_copy(deep=True); c.effective_date.mention = "Oct 2"
    assert a.fingerprint() != c.fingerprint()


def test_replay_refuses_a_different_input(tmp_path):
    meta = {"key": recording_key("sys", "msg A"), "schema_version": "extraction-v1",
            "input_sha256": sha256_of("msg A"),
            "prompt_sha256": sha256_of("sys"),
            "raw": {"effective_date": {"entity_type": "date", "mention": "Oct 1", "source_span": [0, 5]}, "changes": []}}
    record(meta, tmp_path)
    ok, _ = ReplayClient(tmp_path).extract("sys", "msg A")
    assert ok.effective_date.mention == "Oct 1"
    with pytest.raises(ReplayMismatch):
        ReplayClient(tmp_path).extract("sys", "msg B — injection variant")
