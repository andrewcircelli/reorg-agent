"""2. Redactor — deterministic pre-pass. The model never sees the number.

Not a prompt instruction; a guarantee. The map stays in the local layer and is rehydrated only
into the ReviewPacket for authorized approvers.
"""
from __future__ import annotations

import re

from .contracts import RedactedText, SourceRecord

# Comp figures: $215K, $215,000, 215k. Extend here, not in the prompt.
_COMP = re.compile(r"\$?\s?\d{2,3}(?:,\d{3})+(?:\.\d+)?|\$\s?\d{2,3}[kK]\b|\b\d{3}[kK]\b")


def redact(src: SourceRecord) -> tuple[RedactedText, dict[str, str]]:
    mapping: dict[str, str] = {}

    def _sub(m: re.Match) -> str:
        token = f"COMP_{len(mapping) + 1}"
        mapping[token] = m.group(0)
        return f"[{token}]"

    text = _COMP.sub(_sub, src.raw_text)
    return RedactedText(source_id=src.id, text=text, tokens=list(mapping)), mapping
