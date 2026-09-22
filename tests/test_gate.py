"""The approval gate: the three ways it says no, and what an approval is attached to.

The test that matters most is the last one. An approval is not a general blessing — it is a
statement about specific content, and editing that content has to take the approval with it.
"""
import pytest

from reorg import gate
from reorg.contracts import (Approval, Field, Finding, Severity, SourceRecord, now_iso,
                              sha256_of)
from tests.test_validate import answered, intent, split

AUTHOR = "jordan.hrbp"
REGISTRY = "reg_abc123"
REFERENCE = "ref_def456"


def source():
    return SourceRecord(id="src_test", channel="slack", author=AUTHOR, sent_at="2026-09-21",
                        captured_at=now_iso(), raw_text="…", sha256=sha256_of("…"))


def blocking(message="something is unanswered"):
    return Finding(rule_id="R_UNRESOLVED", severity=Severity.BLOCKING, change_ref=1, message=message)


def sign(the_intent, role, approver="dana.finance", findings=()):
    return gate.approve(the_intent, list(findings), source(), approver=approver, role=role,
                        registry_version=REGISTRY, reference_sha256=REFERENCE)


# ---- status ----------------------------------------------------------------------------------
def test_status_reflects_whether_anything_is_blocking():
    assert gate.status_for([blocking()]) == "NEEDS_RESOLUTION"
    assert gate.status_for([]) == "READY"
    info = Finding(rule_id="R_BAND_CHANGE", severity=Severity.INFO, change_ref=1, message="L4 → L5")
    assert gate.status_for([info]) == "READY"      # only BLOCKING stops things


# ---- the three refusals -----------------------------------------------------------------------
def test_it_refuses_while_anything_is_blocking():
    with pytest.raises(gate.GateRefused, match="blocking"):
        sign(intent(split()), "finance", findings=[blocking()])


def test_the_person_who_asked_cannot_approve_it():
    """Segregation of duties. Jordan sent the message, so Jordan cannot sign it off."""
    with pytest.raises(gate.GateRefused, match="cannot also approve"):
        sign(intent(split()), "finance", approver=AUTHOR)


def test_it_refuses_a_role_the_request_does_not_need():
    with pytest.raises(gate.GateRefused, match="does not need approval"):
        sign(intent(split()), "comp_hr")           # a split needs finance, and nothing else


# ---- every role the request needs, and only those ------------------------------------------------
def test_the_request_is_not_approved_until_its_role_has_signed():
    one = intent(split())
    assert gate.outstanding_roles(one, [], REGISTRY, REFERENCE) == ["finance"]
    assert gate.outstanding_roles(one, [sign(one, "finance")], REGISTRY, REFERENCE) == []


def test_roles_are_derived_per_change_kind_not_per_request():
    """This version supports one kind and derives one role. The rule is per kind, so a request
    containing two kinds would need both owners and either alone would not be enough."""
    from reorg.validate import ROLE_FOR_KIND
    assert list(ROLE_FOR_KIND.values()) == ["finance"]


# ---- what an approval is attached to -------------------------------------------------------------
def test_an_approval_records_the_content_the_reference_data_and_the_registry():
    """A plan does not follow from the request alone. It also depends on what the directory said
    and what the step registry said, so an approval has to name all three."""
    one = intent(split())
    approval = sign(one, "finance")
    assert approval.intent_sha256 == one.fingerprint()
    assert approval.registry_version == REGISTRY
    assert approval.reference_sha256 == REFERENCE
    assert approval.approver == "dana.finance" and approval.role == "finance"


def test_editing_the_request_after_approval_takes_the_approval_with_it():
    """The point of the whole gate. Approve it, change one value, and the earlier approval no
    longer applies — not deleted, just no longer about this content."""
    one = intent(split())
    approvals = [sign(one, "finance")]
    assert gate.outstanding_roles(one, approvals, REGISTRY, REFERENCE) == []

    one.changes[0].fields["target_cc"] = answered("cost_center", "4999")   # someone edits it
    assert gate.outstanding_roles(one, approvals, REGISTRY, REFERENCE) == ["finance"]


def test_an_approval_for_other_content_does_not_count():
    one = intent(split())
    stale = Approval(intent_sha256="not-this-content", registry_version=REGISTRY,
                     reference_sha256=REFERENCE, approver="dana.finance", role="finance",
                     ts=now_iso())
    assert gate.outstanding_roles(one, [stale], REGISTRY, REFERENCE) == ["finance"]


# ---- the review packet ---------------------------------------------------------------------------
TEXT = "splitting the Infra cost center so Priya's Data Platform team gets its own"


def test_the_packet_does_not_put_a_hidden_figure_back():
    """A salary in the message is removed before the model sees it and is never restored. Approving
    a cost center split does not require knowing anyone's pay, so the figure is taken out once and
    stays out — the packet is not an exception."""
    packet = gate.render_packet(intent(split()), [], TEXT)
    assert "215" not in packet


def test_a_value_the_message_never_gave_is_shown_as_such():
    change = split()
    change.fields["target_cc"] = Field(entity_type="cost_center", unresolved=True,
                                       question="Which new cost center?")
    change.fields["target_cc"].supply("4410", by="human:jordan.hrbp")
    packet = gate.render_packet(intent(change), [], TEXT)
    assert "4410 (answered by human:jordan.hrbp)" in packet
    assert "[not stated in the message]" in packet


def test_a_quote_survives_a_person_answering_which_record_it_meant():
    """The case that is easy to get wrong. The message named the team; a person only supplied which
    record it meant. Showing that as though a person invented the whole value would misrepresent
    the evidence to the one reader whose job is to check it."""
    change = split()
    team = Field(entity_type="org", mention="Data Platform team",
                 source_span=[TEXT.index("Data Platform team"), TEXT.index("Data Platform team") + 18])
    team.unresolved, team.question = True, "Which team?"
    team.supply("org_data_platform", by="human:jordan.hrbp")
    change.fields["team"] = team
    packet = gate.render_packet(intent(change), [], TEXT)
    assert "Data Platform team → org_data_platform (answered by human:jordan.hrbp)" in packet
    assert "message said “Data Platform team”" in packet


def test_the_packet_says_who_still_has_to_approve():
    one = intent(split())
    assert "still required: finance" in gate.render_packet(one, [], TEXT, [], REGISTRY, REFERENCE)
    packet = gate.render_packet(one, [], TEXT, [sign(one, "finance")], REGISTRY, REFERENCE)
    assert "none — fully approved" in packet


def test_the_packet_flags_an_approval_that_no_longer_applies():
    one = intent(split())
    approvals = [sign(one, "finance")]
    one.changes[0].fields["target_cc"] = answered("cost_center", "4999")
    assert "no longer applies" in gate.render_packet(one, [], TEXT, approvals, REGISTRY, REFERENCE)


# ---- the demo surface: a typo has to come back as a sentence ---------------------------------------
def test_a_mistyped_resolve_argument_explains_itself():
    """This is the command typed live during the demo. Each of these used to be a stack trace."""
    import pytest as _pytest
    from reorg.cli import _apply_resolutions

    one = intent(split())
    for bad, expected in [("garbage", "expected CHANGE.FIELD=VALUE"),
                          ("9.worker=10422", "points at change"),
                          ("x.worker=1", "points at change"),
                          ("1.target_cc=", "expected CHANGE.FIELD=VALUE"),
                          ("1.nope=x", "has no field")]:
        with _pytest.raises(SystemExit) as exit_info:
            _apply_resolutions(one, [bad])
        assert expected in str(exit_info.value), bad


# ---- an approval is about a situation, and situations change ---------------------------------------
def test_an_approval_stops_counting_when_the_reference_data_changes():
    one = intent(split())
    approvals = [sign(one, "finance")]
    assert gate.outstanding_roles(one, approvals, REGISTRY, REFERENCE) == []
    assert gate.outstanding_roles(one, approvals, REGISTRY, "different-reference") == ["finance"]


def test_re_approving_after_a_change_clears_it_and_the_old_entries_stay():
    """The deadlock this replaced: compile refused on any stale approval in the file, so once the
    reference data changed there was no way back — re-approving added new entries but the old ones
    were still there and still refused. Only what applies now is counted."""
    one = intent(split())
    stale = [sign(one, "finance")]
    fresh = [gate.approve(one, [], source(), approver="dana.finance", role="finance",
                          registry_version=REGISTRY, reference_sha256="reference-v2")]

    everything = stale + fresh
    assert gate.outstanding_roles(one, everything, REGISTRY, "reference-v2") == []
    assert len(everything) == 2, "the earlier approval is kept as history, not deleted"


def test_the_packet_says_which_kind_of_change_retired_an_approval():
    one = intent(split())
    approvals = [sign(one, "finance")]
    packet = gate.render_packet(one, [], TEXT, approvals, REGISTRY, "different-reference")
    assert "given against different reference data — no longer applies" in packet
