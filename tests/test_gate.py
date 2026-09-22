"""The approval gate: the three ways it says no, and what an approval is attached to.

The test that matters most is the last one. An approval is not a general blessing — it is a
statement about specific content, and editing that content has to take the approval with it.
"""
import pytest

from reorg import gate
from reorg.contracts import (Approval, Field, Finding, Severity, SourceRecord, now_iso,
                              sha256_of)
from tests.test_validate import answered, comp, intent, split

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
        sign(intent(split()), "comp_hr")           # a split needs finance, not comp_hr


# ---- one approval is not enough when a message asks for two things ------------------------------
def test_finance_alone_does_not_approve_a_message_that_also_changes_pay():
    """The planted trap: the pay change rides along with the org change."""
    both = intent(split(), comp())
    finance = sign(both, "finance")
    assert gate.outstanding_roles(both, [finance]) == ["comp_hr"]


def test_both_roles_together_complete_it():
    both = intent(split(), comp())
    approvals = [sign(both, "finance"), sign(both, "comp_hr", approver="raj.comp")]
    assert gate.outstanding_roles(both, approvals) == []


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
    both = intent(split(), comp())
    approvals = [sign(both, "finance"), sign(both, "comp_hr", approver="raj.comp")]
    assert gate.outstanding_roles(both, approvals) == []

    both.changes[0].fields["target_cc"] = answered("cost_center", "4999")   # someone edits it
    assert gate.outstanding_roles(both, approvals) == ["comp_hr", "finance"]


def test_an_approval_for_other_content_does_not_count():
    one = intent(split())
    stale = Approval(intent_sha256="not-this-content", registry_version=REGISTRY,
                     reference_sha256=REFERENCE, approver="dana.finance", role="finance",
                     ts=now_iso())
    assert gate.outstanding_roles(one, [stale]) == ["finance"]


# ---- the review packet ---------------------------------------------------------------------------
TEXT = "bumping Sam to the L5 band at [COMP_1] as part of this"
MAP = {"COMP_1": "$215K"}


def test_the_packet_puts_the_hidden_pay_figure_back():
    """The only place the real figure reappears, because it is the only place someone is asked to
    approve it. It is never sent to the model and never written to the run folder by the model."""
    change = comp()
    change.fields["new_comp"] = answered("text", None)
    change.fields["new_comp"].mention = "[COMP_1]"
    change.fields["new_comp"].source_span = [TEXT.index("[COMP_1]"), TEXT.index("[COMP_1]") + 8]
    packet = gate.render_packet(intent(change), [], TEXT, MAP)
    assert "$215K" in packet and "[COMP_1]" not in packet


def test_a_value_the_message_never_gave_is_shown_as_such():
    change = split()
    change.fields["target_cc"] = Field(entity_type="cost_center", unresolved=True,
                                       question="Which new cost centre?")
    change.fields["target_cc"].supply("4410", by="human:jordan.hrbp")
    packet = gate.render_packet(intent(change), [], TEXT, MAP)
    assert "4410 (answered by human:jordan.hrbp)" in packet
    assert "[not stated in the message]" in packet


def test_a_quote_survives_a_person_answering_which_record_it_meant():
    """The case that is easy to get wrong. The message said "Sam"; a person only supplied which
    Sam. Showing that as though a person invented the whole value would misrepresent the evidence
    to the one reader whose job is to check it."""
    change = comp()
    sam = Field(entity_type="worker", mention="Sam",
                source_span=[TEXT.index("Sam"), TEXT.index("Sam") + 3])
    sam.unresolved, sam.question = True, "Which Sam?"
    sam.supply("10422", by="human:jordan.hrbp")
    change.fields["worker"] = sam
    packet = gate.render_packet(intent(change), [], TEXT, MAP)
    assert "Sam → 10422 (answered by human:jordan.hrbp)" in packet
    assert "message said “Sam”" in packet


def test_the_packet_says_who_still_has_to_approve():
    both = intent(split(), comp())
    packet = gate.render_packet(both, [], TEXT, MAP, [sign(both, "finance")])
    assert "still required: comp_hr" in packet


def test_the_packet_flags_an_approval_that_no_longer_applies():
    both = intent(split(), comp())
    approvals = [sign(both, "finance")]
    both.changes[0].fields["target_cc"] = answered("cost_center", "4999")
    assert "no longer applies" in gate.render_packet(both, [], TEXT, MAP, approvals)


# ---- the demo surface: a typo has to come back as a sentence ---------------------------------------
def test_a_mistyped_resolve_argument_explains_itself():
    """This is the command typed live during the demo. Each of these used to be a stack trace."""
    import pytest as _pytest
    from reorg.cli import _apply_resolutions

    one = intent(split(), comp())
    for bad, expected in [("garbage", "expected CHANGE.FIELD=VALUE"),
                          ("9.worker=10422", "points at change"),
                          ("x.worker=1", "points at change"),
                          ("1.target_cc=", "expected CHANGE.FIELD=VALUE"),
                          ("1.nope=x", "has no field")]:
        with _pytest.raises(SystemExit) as exit_info:
            _apply_resolutions(one, [bad])
        assert expected in str(exit_info.value), bad
