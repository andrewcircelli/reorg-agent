"""2. Redactor — deterministic pre-pass for compensation figures.

What this does and does not do, stated plainly. It replaces pay figures in the formats matched
below. It is not general-purpose personal-data removal. Names and team relationships stay in the
text on purpose, because the model needs them to work out what the message is asking for.

The list of what was replaced never leaves this machine. The real figures are put back only when
the review packet is shown to someone whose role is allowed to see them.
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
