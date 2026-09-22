"""The Resolver: words in, ids out, and a question whenever that is not certain.

Every test here uses the real reference/ files rather than invented ones, because the point of the
Resolver is how it behaves against the data we actually ship.
"""
import json
from pathlib import Path

import pytest

from reorg import resolve
from reorg.contracts import Field

REFERENCE = {p.stem: json.loads(p.read_text()) for p in Path("reference").glob("*.json")}
SENT_AT = "2026-09-21"


def field(entity_type, mention):
    """A field as it looks straight out of the extraction: quoted, not yet looked up."""
    return Field(entity_type=entity_type, mention=mention, source_span=[0, len(mention)])


def resolved(entity_type, mention):
    f = field(entity_type, mention)
    resolve._resolve_field(f, SENT_AT, REFERENCE)
    return f


# ---- exactly one match becomes an id --------------------------------------------------------
@pytest.mark.parametrize("entity_type, mention, expected", [
    ("worker", "Sam Okafor", "10422"),
    ("org", "Data Platform team", "org_data_platform"),
    ("org", "Priya's Data Platform team", "org_data_platform"),   # attribution stripped
    ("org", "Infrastructure", "org_infra"),
    ("cost_center", "Infra cost center", "4400"),                 # via the org code INFRA
    ("cost_center", "4410", "4410"),                              # a number is already an id
    ("band", "L5", "L5"),
    ("band", "l5", "L5"),                                         # case does not matter
    ("date", "Oct 1", "2026-10-01"),
])
def test_a_single_match_resolves(entity_type, mention, expected):
    f = resolved(entity_type, mention)
    assert f.resolved_id == expected
    assert not f.unresolved and f.question is None


# ---- anything else becomes a question --------------------------------------------------------
def test_three_sams_is_a_question_not_a_guess():
    """The centre of the demo. A model could pick one; this cannot, and does not try."""
    f = resolved("worker", "Sam")
    assert f.resolved_id is None
    assert f.unresolved and "Which one" in f.question
    assert len(f.candidates) == 3
    assert all(c.startswith(("10422", "20871", "10201")) for c in f.candidates)


def test_the_quote_survives_an_unsuccessful_lookup():
    """A failed lookup must not lose the evidence — the words are still in the message."""
    f = resolved("worker", "Sam")
    assert f.mention == "Sam" and f.source_span == [0, 3]


def test_no_match_says_so_and_offers_nothing():
    f = resolved("org", "Marketing")
    assert f.resolved_id is None and f.unresolved
    assert "No org" in f.question and f.candidates is None


# ---- the mistakes we are most trying to avoid -------------------------------------------------
def test_a_code_does_not_match_a_longer_word():
    """The org code PAY must not match the word "payments". A silent wrong match here would move
    people into the wrong cost centre, and nothing downstream would disagree."""
    f = resolved("cost_center", "Payments cost center")
    assert f.resolved_id == "4600"          # matched the org name, not the code inside a word


def test_reference_data_is_not_quietly_extended():
    """"Priya's team" has no name in it, only attribution. There is no alias list to catch it, so
    it becomes a question. That is the intended outcome, not a gap to paper over."""
    f = resolved("org", "Priya's team")
    assert f.unresolved and f.resolved_id is None


def test_an_answer_from_a_person_is_never_overwritten():
    f = Field(entity_type="cost_center", unresolved=True, question="Which new cost centre?")
    f.supply("4410", by="human:jordan.hrbp")
    resolve._resolve_field(f, SENT_AT, REFERENCE)
    assert f.resolved_id == "4410" and f.supplied_by == "human:jordan.hrbp"


def test_a_field_the_message_never_stated_is_left_for_a_person():
    f = Field(entity_type="cost_center", unresolved=True, question="Which new cost centre?")
    resolve._resolve_field(f, SENT_AT, REFERENCE)
    assert f.resolved_id is None and f.unresolved


# ---- dates come from the message, never from today --------------------------------------------
def test_the_year_comes_from_the_message_not_the_clock():
    assert resolved("date", "Oct 1").resolved_id == "2026-10-01"
    f = field("date", "Oct 1")
    resolve._resolve_field(f, "2031-01-15", REFERENCE)
    assert f.resolved_id == "2031-10-01"


def test_a_backdated_effective_date_is_not_treated_as_an_error():
    """Backdating to the start of a quarter is an ordinary request. Rejecting it, or silently
    rolling it forward a year, would change what was asked for."""
    f = field("date", "Mar 1")
    resolve._resolve_field(f, SENT_AT, REFERENCE)
    assert f.resolved_id == "2026-03-01"


def test_a_date_it_cannot_read_becomes_a_question():
    f = resolved("date", "end of Q4")
    assert f.unresolved and f.resolved_id is None
