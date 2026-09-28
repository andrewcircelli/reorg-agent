"""Stage 2 · Redactor — replace pay figures before the model sees the message.

Replace amounts matching the patterns below with tokens such as [COMP_1].
Return the redacted message and a token-to-original-value map; the CLI saves both.

This is not general-purpose PII removal. Unmatched amounts, names, and team relationships remain.
Original values remain locally in 01_source.json and 02_redaction_map.local.json.
No downstream stage reads the map or restores those values.
"""

from __future__ import annotations

import re

from .contracts import RedactedText, SourceRecord, sha256_of

_COMP = re.compile(
    r"\$?\s?\d{2,3}(?:,\d{3})+(?:\.\d+)?|\$\s?\d{2,3}[kK]\b|\b\d{3}[kK]\b"
)


def redact(src: SourceRecord) -> tuple[RedactedText, dict[str, str]]:
    mapping: dict[str, str] = {}

    def _sub(m: re.Match) -> str:
        token = f"COMP_{len(mapping) + 1}"
        mapping[token] = m.group(0)
        return f"[{token}]"

    text = _COMP.sub(_sub, src.raw_text)
    return RedactedText(
        source_id=src.id, text=text, tokens=list(mapping), sha256=sha256_of(text)
    ), mapping
