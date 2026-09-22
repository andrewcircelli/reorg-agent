"""Contract tests (review A1/A2/B4). The model-facing schema cannot carry workflow state; malformed
fields fail closed; spans must lie inside the exact text; replay is bound to its input."""
import json

import pytest
from pydantic import ValidationError

from reorg.contracts import (ChangeKind, ExtractedChange, ExtractedField, ExtractionResult, Field,
                             ExtractedField, ReorgIntent, missing_required, sha256_of,
                             validate_citations)
from reorg.model_client import (SCHEMA_SHA256, ReplayClient, ReplayMismatch, recording_key,
                                record)


def named(name, t="worker", m="Sam", span=(0, 3), **kw):
    return ExtractedField(name=name, entity_type=t, mention=m, source_span=list(span), **kw)


def cited(t="worker", m="Sam", span=(0, 3), **kw):
    """The effective date is the same shape as any other field, so it carries a name too."""
    return named("effective_date", t, m, span, **kw)


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
    for forbidden in ("status", "resolved_id", "candidates", "source_id", "id"):
        assert forbidden not in names, f"model-facing schema must not carry '{forbidden}'"
    assert names == {"changes", "effective_date", "entity_type", "fields", "kind", "mention",
                     "name", "notes", "question", "source_span", "unresolved"}


@pytest.mark.parametrize("kwargs", [
    dict(name="worker", entity_type="worker"),                             # empty
    dict(name="worker", entity_type="worker", unresolved=True),                           # unresolved, no question
    dict(name="worker", entity_type="worker", mention="Sam"),                             # cited, no span
    dict(name="worker", entity_type="worker", mention="Sam", source_span=[5, 2]),         # reversed span
    dict(name="worker", entity_type="worker", mention="Sam", source_span=[-2, 3]),        # negative
    dict(name="worker", entity_type="worker", mention="Sam", source_span=[0, 3], unresolved=True, question="?"),  # both
])
def test_malformed_fields_fail_closed(kwargs):
    with pytest.raises(ValidationError):
        ExtractedField(**kwargs)


def test_unresolved_and_cited_shapes_are_valid():
    ExtractedField(name="target_cc", entity_type="cost_center", unresolved=True,
                   question="Split into which cost center?")
    cited("band", "L5", (10, 12))


def test_unknown_field_name_rejected():
    with pytest.raises(ValidationError):
        ExtractedChange(kind=ChangeKind.COST_CENTER_SPLIT, fields=[named("boss")])


def test_wrong_entity_type_for_field_rejected():
    with pytest.raises(ValidationError):
        ExtractedChange(kind=ChangeKind.COST_CENTER_SPLIT, fields=[named("team", t="worker")])


def test_unsupported_kind_is_rejected_loudly():
    with pytest.raises(ValidationError, match="not supported in this version"):
        ExtractedChange(kind=ChangeKind.TEAM_MOVE, fields=[])


def test_missing_required_is_detected_not_silent():
    ch = ExtractedChange(kind=ChangeKind.COST_CENTER_SPLIT, fields=[named("source_cc", t="cost_center")])
    assert missing_required(ch) == ["target_cc", "team"]


def test_duplicate_field_name_rejected():
    """A list shape makes duplicates expressible, so they are refused rather than last-one-wins."""
    with pytest.raises(ValidationError, match="given twice"):
        ExtractedChange(kind=ChangeKind.COST_CENTER_SPLIT,
                        fields=[named("team", t="org"), named("team", t="org", m="Infra")])


# ---- citations must quote the text, not merely fit inside it ---------------------------------
TEXT = "effective Oct 1, we're bumping Sam to the L5 band"


def test_citation_that_quotes_the_text_is_accepted():
    r = ExtractionResult(effective_date=cited("date", "Oct 1", (10, 15)), changes=[])
    validate_citations(r, TEXT)


def test_span_beyond_text_fails_closed():
    r = ExtractionResult(effective_date=cited("date", "Oct 1", (0, 5)), changes=[])
    with pytest.raises(ValueError, match="exceeds text length"):
        validate_citations(r, "Oct")


def test_span_that_fits_but_quotes_other_words_fails_closed():
    """The failure a bounds check misses: real span, wrong words. The value would look cited while
    its evidence pointed somewhere else, and the reviewer would be verifying nothing."""
    r = ExtractionResult(effective_date=cited("date", "Oct 1", (0, 5)), changes=[])   # "effec"
    with pytest.raises(ValueError) as exc:
        validate_citations(r, TEXT)
    assert "'effec'" in str(exc.value) and "'Oct 1'" in str(exc.value)


def test_every_bad_citation_is_reported_in_one_error():
    r = ExtractionResult(
        effective_date=cited("date", "Oct 1", (0, 5)),                       # quotes "effec"
        changes=[ExtractedChange(kind=ChangeKind.COST_CENTER_SPLIT, fields=[
            named("team", t="org", m="Sam", span=(31, 34)),                  # correct
            named("source_cc", t="cost_center", m="L5", span=(0, 2)),        # quotes "ef"
        ])])
    with pytest.raises(ValueError) as exc:
        validate_citations(r, TEXT)
    msg = str(exc.value)
    assert "effective_date" in msg and "changes[0].source_cc" in msg
    assert "changes[0].team" not in msg, "a correct citation must not be reported"


def test_unresolved_fields_have_nothing_to_quote():
    r = ExtractionResult(
        effective_date=ExtractedField(name="effective_date", entity_type="date", unresolved=True,
                                      question="Effective when?"),
        changes=[ExtractedChange(kind=ChangeKind.COST_CENTER_SPLIT, fields=[
            ExtractedField(name="target_cc", entity_type="cost_center", unresolved=True,
                                question="Which new cost center?")])])
    validate_citations(r, TEXT)


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


def _recording(**overrides):
    meta = {"key": recording_key("sys", "msg A"), "schema_version": "extraction-v1",
            "schema_sha256": SCHEMA_SHA256,
            "input_sha256": sha256_of("msg A"),
            "prompt_sha256": sha256_of("sys"),
            "raw": {"effective_date": {"name": "effective_date", "entity_type": "date",
                                      "mention": "Oct 1", "source_span": [0, 5]}, "changes": []}}
    meta.update(overrides)
    return meta


def test_replay_refuses_a_different_input(tmp_path):
    record(_recording(), tmp_path)
    ok, _ = ReplayClient(tmp_path).extract("sys", "msg A")
    assert ok.effective_date.mention == "Oct 1"
    with pytest.raises(ReplayMismatch):
        ReplayClient(tmp_path).extract("sys", "msg B — injection variant")


def test_replay_refuses_a_recording_made_under_a_different_schema(tmp_path):
    """The failure a version string cannot catch: same prompt, same message, schema since reshaped.
    The recorded answer was valid under a contract that no longer exists."""
    record(_recording(schema_sha256="0" * 64), tmp_path)
    with pytest.raises(ReplayMismatch, match="different schema"):
        ReplayClient(tmp_path).extract("sys", "msg A")


# ---- workflow Field: states the model never produces must survive a save/reload -------------------
def test_ambiguous_identity_keeps_its_citation_and_round_trips():
    f = Field.from_extracted(cited("worker", "Sam", (70, 73)))
    f.unresolved, f.question, f.candidates = True, "Which Sam? Give an employee ID.", ["10422", "20871", "10201"]
    back = Field.model_validate(f.model_dump(mode="json"))
    assert back.mention == "Sam" and back.source_span == [70, 73] and back.unresolved and len(back.candidates) == 3


def test_human_supplied_answer_has_no_fabricated_span_and_round_trips():
    f = Field.from_extracted(ExtractedField(name="target_cc", entity_type="cost_center",
                                            unresolved=True, question="What is the new cost center?"))
    f.supply("4410", by="human:jordan.hrbp")
    back = Field.model_validate(f.model_dump(mode="json"))
    assert back.resolved_id == "4410" and back.supplied_by == "human:jordan.hrbp"
    assert back.source_span is None and back.mention is None and not back.unresolved


def test_workflow_field_still_refuses_nonsense():
    with pytest.raises(ValidationError):
        Field(entity_type="worker", unresolved=True)                                   # no question
    with pytest.raises(ValidationError):
        Field(entity_type="worker", unresolved=True, question="?", resolved_id="1")    # both
    with pytest.raises(ValidationError):
        Field(entity_type="worker", mention="Sam", source_span=[0, 0])                 # empty span
