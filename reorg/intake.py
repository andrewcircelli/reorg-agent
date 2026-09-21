"""1. Intake — capture the message exactly as it arrived. No interpretation."""
from __future__ import annotations

import uuid
from pathlib import Path

from .contracts import SourceRecord, now_iso, sha256_of


def capture(path: str | Path, channel: str = "slack", author: str = "jordan.hrbp") -> SourceRecord:
    raw = Path(path).read_text()
    return SourceRecord(
        id=f"src_{uuid.uuid4().hex[:8]}",
        channel=channel,
        author=author,
        ts=now_iso(),
        raw_text=raw,
        sha256=sha256_of(raw),
    )
