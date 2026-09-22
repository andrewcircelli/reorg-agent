"""The Validator: is this request safe to put in front of a person?

Each test is one rule, and the names say what the rule is for. The interesting ones are the two
that catch a request which has been read perfectly and is still wrong.
"""
import json
from pathlib import Path

from reorg import validate
from reorg.contracts import Change, ChangeKind, Field, ReorgIntent, Severity

REFERENCE = {p.stem: json.loads(p.read_text()) for p in Path("reference").glob("*.json")}


def answered(entity_type, resolved_id):
    """A field that has been looked up successfully."""
    return Field(entity_type=entity_type, mention="x", source_span=[0, 1], resolved_id=resolved_id)


def unanswered(entity_type, question="Which one?"):
    return Field(entity_type=entity_type, unresolved=True, question=question)


def intent(*changes, effective_date=None):
    return ReorgIntent(
        id="intent_test", source_id="src_test", sent_at="2026-09-21",
        effective_date=effective_date or answered("date", "2026-10-01"),
        changes=list(changes))


def split(source="4400", target="4410", team="org_data_platform"):
    return Change(kind=ChangeKind.COST_CENTER_SPLIT, fields={
        "source_cc": answered("cost_center", source),
        "target_cc": answered("cost_center", target),
        "team": answered("org", team)})


def rules_fired(findings, severity=None):
    return {f.rule_id for f in findings if severity is None or f.severity is severity}


def check(*changes, **kw):
    return validate.validate(intent(*changes, **kw), REFERENCE)


# ---- a request that is complete and consistent raises nothing blocking -------------------------
def test_a_good_request_has_nothing_blocking():
    assert rules_fired(check(split()), Severity.BLOCKING) == set()


# ---- rule 1: anything unanswered stops everything ---------------------------------------------
def test_an_unanswered_field_blocks():
    change = split()
    change.fields["target_cc"] = unanswered("cost_center", "Which new cost center?")
    findings = check(change)
    assert "R_UNRESOLVED" in rules_fired(findings, Severity.BLOCKING)
    assert "Which new cost center?" in " ".join(f.message for f in findings)


def test_an_unanswered_effective_date_blocks():
    findings = check(split(), effective_date=unanswered("date", "Effective when?"))
    blocking = [f for f in findings if f.severity is Severity.BLOCKING]
    assert blocking and blocking[0].change_ref is None      # belongs to the request, not one change


# ---- rule 2: a change must carry the fields its kind requires ----------------------------------
def test_a_missing_required_field_blocks():
    change = split()
    del change.fields["team"]
    findings = check(change)
    assert "R_REQUIRED_FIELDS" in rules_fired(findings, Severity.BLOCKING)
    assert "team" in " ".join(f.message for f in findings)


# ---- rule 3: the cost center being split exists, the new one does not ---------------------------
def test_a_target_cost_center_that_already_exists_blocks():
    """A split creates a cost center. If the number already exists, someone has mistyped it, and
    carrying on would move people into another team's budget line."""
    findings = check(split(target="4500"))
    assert "R_CC_EXISTS" in rules_fired(findings, Severity.BLOCKING)
    assert "already exists" in " ".join(f.message for f in findings)


def test_an_unknown_source_cost_center_blocks():
    assert "R_CC_EXISTS" in rules_fired(check(split(source="9999")), Severity.BLOCKING)


def test_a_team_that_does_not_exist_blocks():
    assert "R_ID_EXISTS" in rules_fired(check(split(team="org_nope")), Severity.BLOCKING)


def test_the_new_cost_center_is_not_required_to_exist():
    """This rule must stay out of the way of cost centers. A split creates the target one, so its
    absence is the normal case, not an error. Rule 4 owns cost centers for that reason."""
    assert "R_ID_EXISTS" not in rules_fired(check(split(target="4410")))


# ---- rule 4: the team must really sit where the message says it does ----------------------------
def test_a_team_that_does_not_sit_in_the_source_cost_center_blocks():
    """The request reads perfectly and every quote is real. It is still wrong: Payments does not
    sit in the Infra cost center. Nothing before this rule could notice."""
    findings = check(split(team="org_payments"))          # Payments sits in 4600, not 4400
    assert "R_TEAM_IN_SOURCE_CC" in rules_fired(findings, Severity.BLOCKING)
    assert "may have been misread" in " ".join(f.message for f in findings)


def test_a_team_that_does_sit_there_passes():
    assert "R_TEAM_IN_SOURCE_CC" not in rules_fired(check(split()))


def test_the_team_rule_stays_quiet_while_something_is_still_unanswered():
    """One problem should be reported once. If the team was never resolved, rule 1 already said so
    and this rule has nothing to compare."""
    change = split()
    change.fields["team"] = unanswered("org", "Which team?")
    assert "R_TEAM_IN_SOURCE_CC" not in rules_fired(check(change))


# ---- rule 6: who has to approve ------------------------------------------------------------------
def test_the_supported_change_kind_needs_finance():
    assert validate.required_roles(intent(split())) == ["finance"]


def test_every_supported_change_kind_has_an_approving_role():
    """Two tables have to agree: the kinds the contract accepts, and the roles that own them. If a
    kind were added to one and not the other, working out who approves it would crash rather than
    say anything useful."""
    from reorg.contracts import SUPPORTED_KINDS
    assert set(SUPPORTED_KINDS) <= set(validate.ROLE_FOR_KIND)


# ---- the wording of a finding has to point at the right place ------------------------------------
def test_the_team_rule_blames_the_message_only_when_the_message_is_to_blame():
    """A finding is read by someone deciding where to look. If a person supplied the cost center,
    telling them the message was misread sends them to the wrong document."""
    from_message = check(split(team="org_payments"))
    assert "the message may have been misread" in " ".join(f.message for f in from_message)

    change = split()
    change.fields["source_cc"].supply("4600", by="human:jordan.hrbp")
    supplied = " ".join(f.message for f in check(change))
    assert "check which team and which cost center are meant" in supplied
    assert "misread" not in supplied


def test_an_org_id_a_person_invented_blocks():
    """A person can answer a question by typing anything. Before this rule existed, an id nobody
    has went through to fully approved in silence. The model is not the only source that gets
    checked."""
    change = split()
    change.fields["team"] = Field(entity_type="org", mention="Data Platform team", source_span=[0, 3])
    change.fields["team"].supply("org_does_not_exist", by="human:jordan.hrbp")
    findings = check(change)
    assert "R_ID_EXISTS" in rules_fired(findings, Severity.BLOCKING)
    message = " ".join(f.message for f in findings)
    assert "not in the org tree" in message and "answered by human:jordan.hrbp" in message


def test_two_changes_of_the_same_kind_are_refused():
    """Steps are chosen per kind, so two splits would produce one set of steps carrying only the
    second. This version refuses the input rather than mishandling it."""
    findings = check(split(), split(target="4411"))
    assert "R_ONE_PER_KIND" in rules_fired(findings, Severity.BLOCKING)
