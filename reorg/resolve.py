"""Stage 4 · Resolver — turn quoted names into IDs using reference data, without a model.

The CLI loads reference/*.json and passes the records here; these are local fixtures standing
in for HR and finance data, not live database queries.

For COST_CENTER_SPLIT, org records supply the team's ID and the source org's cost-center ID.
Numeric cost-center mentions are used directly as IDs; the Validator checks whether they exist.
Dates such as "Oct 1" use the year the source message was sent.

Exactly one lookup match supplies an ID. Zero or multiple matches produce a question.
Missing values stay unanswered, and already supplied IDs are left for the Validator to check.
Original quotes are preserved. The CLI saves the result in 04_resolved.json after validation.
"""
from __future__ import annotations

import re

from .contracts import Field, ReorgIntent

# "Priya's Data Platform team" -> "Data Platform team". Attribution names a person, and working out
# which person is this file's job, not part of the name. Both kinds of apostrophe appear in practice.
_POSSESSIVE = re.compile(r"^\w+['’]s\s+")

# "Data Platform team" -> "Data Platform". The org is called Data Platform; "team" is just a noun
# people add when speaking. Stripping it here keeps it out of the reference data.
_TRAILING_NOUN = re.compile(r"\s+(team|teams|org|orgs|group|organisation|organization)$")

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _norm(text: str) -> str:
    """Lower case, and single spaces. Used on both sides of every comparison."""
    return " ".join(text.split()).casefold()


def _org_phrase(mention: str) -> str:
    """Reduce a spoken reference to a team down to the words that name it."""
    return _TRAILING_NOUN.sub("", _POSSESSIVE.sub("", _norm(mention))).strip()


def _contains_word(haystack: str, needle: str) -> bool:
    """True when `needle` appears in `haystack` as a whole word.

    Whole word rather than anywhere in the string, so the code PAY does not match the word
    "payments". Silent wrong matches are the thing we are most trying to avoid."""
    return bool(needle) and re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


# ---------------------------------------------------------------------------------------------
# One lookup per kind of value. Each returns a list of candidate ids: one means resolved, anything
# else means ask a person.
# ---------------------------------------------------------------------------------------------
def _workers(mention: str, people: list[dict]) -> list[str]:
    m = _norm(mention)
    return [p["id"] for p in people
            if m == _norm(p["name"]) or m in _norm(p["name"]).split()]


def _orgs(mention: str, orgs: list[dict]) -> list[str]:
    phrase = _org_phrase(mention)
    return [o["id"] for o in orgs
            if phrase == _norm(o["name"]) or phrase == _norm(o.get("code") or "\0")]


def _cost_centers(mention: str, orgs: list[dict]) -> list[str]:
    m = _norm(mention)
    if m.isdigit():
        return [m]
    # "Infra cost center" does not name a cost center, it names an org. Find the org, then take
    # the cost center it currently sits in.
    hits = {o["cost_center"] for o in orgs
            if _contains_word(m, _norm(o["name"])) or _contains_word(m, _norm(o.get("code") or ""))}
    return sorted(hits)


def _bands(mention: str, bands: list[dict]) -> list[str]:
    m = _norm(mention)
    return [b["id"] for b in bands if m == _norm(b["id"])]


def _date(mention: str, sent_at: str) -> list[str]:
    """Turn "Oct 1" into 2026-10-01, using the year of the message itself.

    The year comes from the message and never from today's clock, so re-running this next year
    cannot silently change an old result. There is deliberately no rule against dates in the past
    either: a reorg backdated to the start of a quarter is an ordinary request, not an error."""
    text = _norm(mention)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return [text]
    written = re.fullmatch(r"([a-z]{3,9})\.?\s+(\d{1,2})", text)
    if not written:
        return []
    month = _MONTHS.get(written.group(1)[:3])
    if month is None:
        return []
    return [f"{sent_at[:4]}-{month:02d}-{int(written.group(2)):02d}"]


def _label(kind: str, ids: list[str], reference: dict) -> list[str]:
    """Candidates as a person would want to read them: the id plus enough to tell them apart."""
    if kind == "worker":
        by_id = {p["id"]: p for p in reference.get("people", [])}
        return [f"{i} — {by_id[i]['name']} ({by_id[i]['org']})" if i in by_id else i for i in ids]
    if kind == "org":
        by_id = {o["id"]: o for o in reference.get("orgs", [])}
        return [f"{i} — {by_id[i]['name']}" if i in by_id else i for i in ids]
    return list(ids)


# ---------------------------------------------------------------------------------------------
def _resolve_field(field: Field, sent_at: str, reference: dict) -> None:
    """Try to turn one field's quoted words into an id. Changes the field in place."""
    if field.resolved_id is not None:
        return          # already settled, either by an earlier run or by a person answering
    if field.mention is None:
        return          # the message never said it, so there is nothing here to look up

    kind = field.entity_type
    if kind == "worker":
        ids = _workers(field.mention, reference.get("people", []))
    elif kind == "org":
        ids = _orgs(field.mention, reference.get("orgs", []))
    elif kind == "cost_center":
        ids = _cost_centers(field.mention, reference.get("orgs", []))
    elif kind == "band":
        ids = _bands(field.mention, reference.get("bands", []))
    elif kind == "date":
        ids = _date(field.mention, sent_at)
    else:
        return          # free text, such as the blanked-out pay figure. Nothing to look up.

    if len(ids) == 1:
        field.resolved_id = ids[0]
        field.unresolved, field.question, field.candidates = False, None, None
        return

    # Nothing else counts. Two matches is not a reason to pick one, and none is not a reason to
    # invent one. Either way the quote stays where it is and a person is asked.
    field.unresolved = True
    field.candidates = _label(kind, ids, reference) or None
    field.question = (
        f"More than one {kind.replace('_', ' ')} matches {field.mention!r}. Which one is meant?"
        if ids else
        f"No {kind.replace('_', ' ')} in the reference data matches {field.mention!r}. Which one is meant?"
    )


def resolve(intent: ReorgIntent, reference: dict) -> ReorgIntent:
    """Look up every field on the intent. Returns the same intent, changed in place."""
    _resolve_field(intent.effective_date, intent.sent_at, reference)
    for change in intent.changes:
        for field in change.fields.values():
            _resolve_field(field, intent.sent_at, reference)
    return intent
