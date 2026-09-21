"""8. Dry-run Executor — per-step diff via adapters; HumanTask for human_keyed steps. (Phase 7)

Adapter interface (reorg/adapters/*.py):  diff(step, state) -> str · apply(step) [not built] · verify(step, state) -> bool
The human adapter's apply() is a person; its verify() runs after they say "done" — same as an API step.
"""
from __future__ import annotations

from .contracts import DryRunReport, Plan


def dry_run(plan: Plan, state: dict) -> DryRunReport:
    raise NotImplementedError("Phase 7")
