"""Not a stage · the eval — compare what the model produced against the answer key.

The answer key is fixtures/intent_expected.json: how a person read the same message, written down
before any model was run. This file is what turns "the output looks about right" into a pass or a
list of specific differences.

What has to match: the same kinds of change, in the same order; the same field names on each
change; and for every field, the same choice between quoting the message and asking a question.
Where a field quotes the message, the quoted words and their location both have to match.

What is not compared: the wording of a question. We check that a question is there, not that it is
phrased the way the key phrases it. Two reviewers would word it differently and both be right.
"""
from __future__ import annotations

from .contracts import ExtractedField, ExtractionResult


def _field(label: str, exp: ExtractedField, got: ExtractedField | None) -> list[str]:
    if got is None:
        return [f"{label}: missing"]
    if exp.unresolved != got.unresolved:
        return [f"{label}: expected {'UNRESOLVED' if exp.unresolved else 'cited'}, got {'UNRESOLVED' if got.unresolved else 'cited ' + repr(got.mention)}"]
    if exp.unresolved:
        return []
    out = []
    if exp.mention != got.mention:
        out.append(f"{label}: mention expected {exp.mention!r}, got {got.mention!r}")
    if exp.source_span != got.source_span:
        out.append(f"{label}: span expected {exp.source_span}, got {got.source_span}")
    return out


def diff(expected: ExtractionResult, actual: ExtractionResult) -> list[str]:
    problems = _field("effective_date", expected.effective_date, actual.effective_date)
    exp_kinds = [c.kind.value for c in expected.changes]
    got_kinds = [c.kind.value for c in actual.changes]
    if exp_kinds != got_kinds:
        problems.append(f"changes: expected kinds {exp_kinds}, got {got_kinds}")
    for i, (e, g) in enumerate(zip(expected.changes, actual.changes), 1):
        exp_fields, got_fields = e.by_name(), g.by_name()
        for name, ef in exp_fields.items():
            problems += _field(f"[{i}].{name}", ef, got_fields.get(name))
        for name in got_fields.keys() - exp_fields.keys():
            problems.append(f"[{i}].{name}: unexpected extra field (cited {got_fields[name].mention!r})")
    return problems
