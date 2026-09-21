"""ModelClient — the seam. Prototype: Anthropic SDK. Production: the platform's gateway.

LiveClient   real call; schema-constrained to ExtractionResult (model-facing schema only).
ReplayClient returns a recorded real response. A recording is bound to sha256(input text + system
             prompt + schema version); a different input or prompt has no recording and fails
             clearly instead of replaying someone else's answer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from .contracts import ExtractionResult, now_iso, sha256_of

MODEL_ID = "claude-opus-5"
SCHEMA_VERSION = "extraction-v1"


def _load_dotenv() -> None:
    p = Path(".env")
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def recording_key(system: str, user: str) -> str:
    return sha256_of(f"{SCHEMA_VERSION}\n{system}\n{user}")[:16]


class ModelClient(Protocol):
    def extract(self, system: str, user: str) -> tuple[ExtractionResult, dict]: ...


class LiveClient:
    def __init__(self, model: str = MODEL_ID):
        _load_dotenv()
        import anthropic  # here so replay mode needs neither key nor network
        self._client = anthropic.Anthropic()
        self.model = model

    def extract(self, system: str, user: str) -> tuple[ExtractionResult, dict]:
        resp = self._client.messages.parse(
            model=self.model, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": user}],
            output_format=ExtractionResult,
        )
        result: ExtractionResult = resp.parsed_output
        meta = {
            "key": recording_key(system, user), "schema_version": SCHEMA_VERSION,
            "input_sha256": sha256_of(user), "prompt_sha256": sha256_of(system),
            "model": resp.model, "ts": now_iso(),
            "usage": resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage),
            "raw": result.model_dump(mode="json"),
        }
        return result, meta


class ReplayMismatch(RuntimeError):
    pass


class ReplayClient:
    def __init__(self, directory: str | Path = "fixtures/recorded"):
        self.dir = Path(directory)

    def extract(self, system: str, user: str) -> tuple[ExtractionResult, dict]:
        key = recording_key(system, user)
        path = self.dir / f"{key}.json"
        if not path.exists():
            raise ReplayMismatch(
                f"no recording for this input/prompt/schema (key {key}). "
                f"Run with --live --record to create one; replay never substitutes another message's answer.")
        rec = json.loads(path.read_text())
        if rec.get("input_sha256") != sha256_of(user) or rec.get("prompt_sha256") != sha256_of(system) \
                or rec.get("schema_version") != SCHEMA_VERSION:
            raise ReplayMismatch(f"recording {path} does not match current input/prompt/schema")
        meta = {k: rec[k] for k in ("model", "ts", "usage", "key") if k in rec}
        meta["replayed_from"] = str(path)
        return ExtractionResult.model_validate(rec["raw"]), meta


def record(meta: dict, directory: str | Path = "fixtures/recorded") -> Path:
    d = Path(directory); d.mkdir(parents=True, exist_ok=True)
    p = d / f"{meta['key']}.json"
    p.write_text(json.dumps(meta, indent=2))
    return p
