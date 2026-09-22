"""Execution against real systems. DESIGNED, DELIBERATELY NOT BUILT.

This file is here so the boundary is visible in the code as well as in the design document. The
prototype stops at an approved plan. Nothing in it writes to an HR or finance system, and nothing
in it simulates one either.

WHY NOT BUILT

Writing to those systems correctly depends on things this prototype has no access to: how each one
treats an effective date, what it does with a write that arrives twice, and what it can be asked
afterwards to confirm the change actually took. A simulated adapter would answer all three
questions the way we imagined them rather than the way they are, and the demonstration would be of
our own assumptions.

The honest version of this step is also the least interesting to watch: get real access, run in
preview or shadow mode first, establish how each step is verified — including the one a person
keys in by hand — and only then enable a narrow write path with someone supervising it.

WHAT THE PROTOTYPE DOES INSTEAD

It produces the plan and, for any step no system can do, a task card saying who it is for, what to
do, what should be true afterwards, and what is waiting on it. See reorg/compile.py.

The Plan and DryRunReport shapes stay in contracts.py because the design is worked out. Nothing
calls this file, and no test claims it works.
"""
from __future__ import annotations

from .contracts import DryRunReport, Plan


def dry_run(plan: Plan, state: dict) -> DryRunReport:
    raise NotImplementedError(
        "Execution is designed but not built — the prototype stops at an approved plan. "
        "See the note at the top of this file.")
