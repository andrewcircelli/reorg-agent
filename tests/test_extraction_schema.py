"""The schema we WRITE must survive the trip to the API as the schema we MEAN.

Structured outputs accept a subset of JSON Schema. `additionalProperties: <schema>` — what pydantic
emits for `dict[str, Model]` — is not in that subset: the SDK strips it and sends
`additionalProperties: false` with no `properties`, i.e. an object the model may only return EMPTY.
That failure is silent — the call succeeds, every extracted field is gone, and the diff blames the
prompt. This test is the guard, and the reason ExtractedChange.fields is a list (contracts.py).
"""
import json

import pytest

from reorg.contracts import ExtractionResult


def _objects(schema, path="$"):
    """Every object-typed subschema in the document, with a readable path."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield path, schema
        for k, v in schema.items():
            yield from _objects(v, f"{path}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            yield from _objects(v, f"{path}[{i}]")


def test_no_open_ended_maps_in_the_model_facing_schema():
    """The documented limitation, asserted on our own schema — no SDK internals involved."""
    for path, obj in _objects(ExtractionResult.model_json_schema()):
        ap = obj.get("additionalProperties", False)
        assert ap is False, (
            f"{path}: additionalProperties={ap!r}. Structured outputs only accept `false`; a "
            f"model-keyed map becomes an object the model can only return empty. Use a list of "
            f"named entries instead.")


def test_field_names_reach_the_model():
    schema = ExtractionResult.model_json_schema()
    entry = schema["$defs"]["NamedExtractedField"]
    assert "name" in entry["properties"] and "name" in entry["required"]


def test_field_name_comes_first():
    """The model fills an object in property order, so it must say which field it is answering
    before it commits to evidence. `name` comes from the _FieldName base for exactly this reason
    (pydantic orders fields by reverse MRO); if that ever silently flips, the first live call's
    failure comes back — entries holding a name and nothing else."""
    props = list(ExtractionResult.model_json_schema()["$defs"]["NamedExtractedField"]["properties"])
    assert props[0] == "name", f"name must be the first property, got {props}"


def test_the_model_facing_schema_carries_no_implementation_notes():
    """Every docstring on these classes ships to the model as a schema `description` — it is prompt
    surface, not internal commentary."""
    schema = json.dumps(ExtractionResult.model_json_schema())
    for leak in ("additionalProperties: <schema>", "registry/steps.yaml", "reverse MRO",
                 "tests/test_extraction_schema", "validate_citations()", "log #"):
        assert leak not in schema, f"{leak!r} is being sent to the model"


def test_schema_the_sdk_actually_sends_has_no_empty_object():
    """Belt and braces: run the SDK's own transform and check nothing collapsed to an empty shape."""
    transform = pytest.importorskip("anthropic.lib._parse._transform", reason="SDK internals moved")
    sent = transform.transform_schema(ExtractionResult.model_json_schema())
    for path, obj in _objects(sent):
        assert obj.get("properties"), f"{path}: object with no properties — the model can only fill it with {{}}"
    assert "mention" in json.dumps(sent), "evidence fields vanished from the schema sent to the API"
