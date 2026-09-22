"""Compare a model ExtractionResult against the hand-written answer key, field by field.

What counts as a match: same change kinds in the same order; same field names; same cited/unresolved
status; same mention and span for cited fields. Question wording is not compared (presence is).
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
        for name, ef in e.fields.items():
            problems += _field(f"[{i}].{name}", ef, g.fields.get(name))
        for name in g.fields.keys() - e.fields.keys():
            problems.append(f"[{i}].{name}: unexpected extra field (cited {g.fields[name].mention!r})")
    return problems
