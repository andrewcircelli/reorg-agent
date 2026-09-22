"""Stage 2 · Redactor — take the pay figures out before anything else sees the message.

What this does and does not do, stated plainly. It replaces pay figures in the formats matched
below. It is not general-purpose personal-data removal. Names and team relationships stay in the
text on purpose, because the model needs them to work out what the message is asking for.

WHERE THE FIGURE STILL EXISTS, STATED EXACTLY

It is removed from everything downstream — the model call, the extraction, the resolved request, the
review packet and the plan. It is not removed from the machine. Two local artifacts still hold it:
`01_source.json`, because Intake stores the message exactly as it arrived and provenance depends on
that, and `02_redaction_map.local.json`, the token map.

Nothing reads the map. It exists so a figure could be put back if a change kind ever arrived whose
approval turned on one — for a named role, in one place. No such kind is built, so the figure is
removed once and never restored.
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
