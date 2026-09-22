"""DATA-MODEL.md lists the fields of every contract. This checks it still tells the truth.

A reference document that has drifted is worse than no document, because it is trusted. The field
lists in that appendix are the part most likely to go stale silently — someone adds a field and the
table keeps describing the old shape. So the table is checked rather than maintained by memory.
"""
import re
from pathlib import Path

import pytest

from reorg import contracts as c

DOC = Path("DATA-MODEL.md")
DOCUMENTED = [c.ExtractionResult, c.ExtractedChange, c.ExtractedField,
              c.ReorgIntent, c.Change, c.Field, c.SourceRecord, c.RedactedText,
              c.Finding, c.Approval, c.Plan, c.StepInstance, c.HumanTask, c.StepDef]


CLASS_NAME = re.compile(r"`([A-Z][A-Za-z]+)`")


def listed_fields(name: str, text: str) -> set[str]:
    """The backticked field names that follow this class on its line.

    A line can name two classes — the families table puts the model-facing one and the workflow one
    side by side — so read only as far as the next class name."""
    for line in text.splitlines():
        if f"`{name}`" not in line:
            continue
        after = line.split(f"`{name}`", 1)[1]
        nxt = CLASS_NAME.search(after)
        if nxt:
            after = after[:nxt.start()]
        found = set(re.findall(r"`([a-z][a-z0-9_]*)`", after))
        if found:
            return found
    pytest.fail(f"DATA-MODEL.md does not list the fields of {name}")


@pytest.mark.parametrize("cls", DOCUMENTED, ids=lambda x: x.__name__)
def test_the_appendix_lists_the_fields_this_class_actually_has(cls):
    documented = listed_fields(cls.__name__, DOC.read_text())
    assert documented == set(cls.model_fields), (
        f"DATA-MODEL.md is out of date for {cls.__name__}: "
        f"missing {set(cls.model_fields) - documented or '—'}, "
        f"stale {documented - set(cls.model_fields) or '—'}")


def test_every_supported_change_kind_is_named_in_the_appendix():
    text = DOC.read_text()
    for kind in c.SUPPORTED_KINDS:
        assert kind.value in text, f"{kind.value} is supported but the appendix does not mention it"
