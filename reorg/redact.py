"""2. Redactor — deterministic pre-pass for compensation figures.

Scope, stated plainly: this handles the compensation formats below, not PII in general. Names and
org relationships remain in the text by design (the Extractor needs them). The map stays local and
is rehydrated only into the ReviewPacket for permitted roles.
"""
from __future__ import annotations

import re

from .contracts import RedactedText, SourceRecord, sha256_of

_COMP = re.compile(r"\$?\s?\d{2,3}(?:,\d{3})+(?:\.\d+)?|\$\s?\d{2,3}[kK]\b|\b\d{3}[kK]\b")


def redact(src: SourceRecord) -> tuple[RedactedText, dict[str, str]]:
    mapping: dict[str, str] = {}

    def _sub(m: re.Match) -> str:
        token = f"COMP_{len(mapping) + 1}"
        mapping[token] = m.group(0)
        return f"[{token}]"

    text = _COMP.sub(_sub, src.raw_text)
    return RedactedText(source_id=src.id, text=text, tokens=list(mapping), sha256=sha256_of(text)), mapping
