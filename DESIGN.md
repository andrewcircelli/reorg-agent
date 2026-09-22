# Agentic Reorg Automation — Design

_(Their six sections. Assembled from prep `00`–`06` after the build. Nothing copied without a read-through.)_

## Summary
## Goals and non-goals

<!-- Written first, because it is the reasoning that `reorg/execute.py` used to carry. That file was a
     module whose entire content was this argument, which made it look like an unfinished subsystem.
     The argument belongs here. -->

### Where this stops, and why

The prototype ends at an **approved execution plan**, plus a task card for the one step no system can
do on its own. It writes to no HR or finance system, and — deliberately — it does not simulate writing
to one either.

That second half is the real decision. Simulating the downstream systems would have been quick, and it
would have demonstrated nothing, because writing to them correctly depends on three things this
prototype has no access to: how each system treats an effective date, what it does with a write that
arrives twice, and what it can be asked afterwards to confirm the change actually took. A simulated
adapter answers all three the way I imagined them. It would have shown my assumptions back to me with
a green tick next to them.

So the prototype demonstrates the part that can be demonstrated honestly: the request is captured from
the message it already arrives in, every value is quoted from that message or raised as a question,
the ambiguities are resolved against reference data or escalated, the rules are checked, the approvals
are bound to exactly what was approved, and the plan is ordered by declared dependencies rather than
by memory.

**What execution would take, in the order I would do it.** Real access and real semantics first. Run
in preview or shadow mode against each system and compare what it says would happen to what the plan
says. Establish how every step is verified, including the one a person keys in by hand, because "the
API returned 200" and "the person said done" are both claims rather than evidence. Only then enable a
narrow write path, with a human watching, and with an answer ready for the case that matters most:
what happens when step three of five succeeds and step four does not.

**What the prototype does instead of pretending.** The plan names every step, its system, its
prerequisites and its timing rule; and for the step with no API it emits a card saying who is
responsible, what to do with which approved values, what should be true afterwards, and how that would
be confirmed — stated as a requirement, and explicitly not performed here. A printed requirement is a
design demonstration. It is not evidence that anything was verified, and the card says so.

## Approach and design
## Alternatives considered
## Risks and failure modes
## Assumptions and open questions
