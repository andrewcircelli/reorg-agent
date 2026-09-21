"""ModelClient — the seam. Prototype: Anthropic SDK. Production: the platform's gateway.

LiveClient   makes the real call with schema-constrained output.
ReplayClient returns a *recorded real response* (fixtures/recorded/*.json) so the demo runs keyless
             and tests run offline. It is not a hand-written response.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from .contracts import ReorgIntent, now_iso

MODEL_ID = "claude-opus-5"


def _load_dotenv() -> None:
    p = Path(".env")
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


class ModelClient(Protocol):
    def extract(self, system: str, user: str) -> tuple[ReorgIntent, dict]: ...


class LiveClient:
    def __init__(self, model: str = MODEL_ID):
        _load_dotenv()
        import anthropic  # imported here so replay mode needs no key and no network
        self._client = anthropic.Anthropic()
        self.model = model

    def extract(self, system: str, user: str) -> tuple[ReorgIntent, dict]:
        resp = self._client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=ReorgIntent,
        )
        meta = {
            "model": resp.model,
            "ts": now_iso(),
            "usage": resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage),
            "raw": resp.parsed_output.model_dump(mode="json"),
        }
        return resp.parsed_output, meta


class ReplayClient:
    def __init__(self, recording: str | Path):
        self.path = Path(recording)

    def extract(self, system: str, user: str) -> tuple[ReorgIntent, dict]:
        rec = json.loads(self.path.read_text())
        meta = {k: rec[k] for k in ("model", "ts", "usage") if k in rec}
        meta["replayed_from"] = str(self.path)
        return ReorgIntent.model_validate(rec["raw"]), meta


def record(meta: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(meta, indent=2))
