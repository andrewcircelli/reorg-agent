"""ModelClient — the seam. Prototype: Anthropic SDK. Production: the platform's gateway.

LiveClient   real call; schema-constrained to ExtractionResult (model-facing schema only). Three
             outcomes are not an extraction and each raises rather than passing a half-filled
             result on: the model refused, the output was truncated, or the contract rejected the
             answer. Only the last one carries the model's own words back (see
             ExtractionRejected) — a refusal and a truncation fail as invalid JSON inside the SDK's
             own validation, which runs before any stop_reason is visible here.
ReplayClient returns a recorded real response. A recording is bound to the input text, the system
             prompt, and the SCHEMA ITSELF — not to a version string someone has to remember to
             bump. A different input, prompt, or schema has no recording and fails clearly instead
             of replaying an answer given under different conditions.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from .contracts import ExtractionResult, now_iso, sha256_of

MODEL_ID = "claude-opus-5"
SCHEMA_VERSION = "extraction-v1"                              # human label, for the audit trail
SCHEMA_SHA256 = sha256_of(ExtractionResult.model_json_schema())  # what actually binds a recording


def _load_dotenv() -> None:
    p = Path(".env")
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def recording_key(system: str, user: str) -> str:
    """The schema hash is in here deliberately. A hand-maintained version string is a promise to
    remember something, and it broke twice in one session: the extraction schema changed shape
    (a map became a list, then the field order changed) while `extraction-v1` sat still, and the
    replay guard would have served an answer given under a schema that no longer existed."""
    return sha256_of(f"{SCHEMA_VERSION}\n{SCHEMA_SHA256}\n{system}\n{user}")[:16]


class ModelClient(Protocol):
    def extract(self, system: str, user: str) -> tuple[ExtractionResult, dict]: ...


class LiveClient:
    def __init__(self, model: str = MODEL_ID):
        _load_dotenv()
        import anthropic  # here so replay mode needs neither key nor network
        self._client = anthropic.Anthropic()
        self.model = model

    def extract(self, system: str, user: str) -> tuple[ExtractionResult, dict]:
        try:
            resp = self._client.messages.parse(
                model=self.model, max_tokens=16000, system=system,
                messages=[{"role": "user", "content": user}],
                output_format=ExtractionResult,
            )
        except ValidationError as e:
            # Reached whenever the response is not a contract-valid ExtractionResult — including a
            # refusal or a truncation, which parse() rejects as invalid JSON before the stop_reason
            # checks below can run. The raw text is in the error, so the prompt loop stays debuggable.
            raise ExtractionRejected.from_validation_error(e) from e
        if resp.stop_reason == "refusal":
            raise ExtractionUnavailable(f"model declined to answer (stop_details={resp.stop_details})")
        if resp.stop_reason == "max_tokens":
            raise ExtractionUnavailable("output hit max_tokens — the extraction is truncated, not partial")
        if resp.parsed_output is None:
            raise ExtractionUnavailable(f"no parsed output (stop_reason={resp.stop_reason})")
        result: ExtractionResult = resp.parsed_output
        meta = {
            "key": recording_key(system, user), "schema_version": SCHEMA_VERSION,
            "schema_sha256": SCHEMA_SHA256,
            "input_sha256": sha256_of(user), "prompt_sha256": sha256_of(system),
            "model": resp.model, "ts": now_iso(),
            "usage": resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage),
            "raw": result.model_dump(mode="json"),
        }
        return result, meta


class ExtractionUnavailable(RuntimeError):
    """The call returned, but not an extraction. Never silently treated as an empty result."""


class ExtractionRejected(ExtractionUnavailable):
    """The model answered and the CONTRACT threw the answer out. Carries what it actually said."""

    @classmethod
    def from_validation_error(cls, e: ValidationError) -> "ExtractionRejected":
        """The SDK validates the response inside messages.parse(), so a violation arrives as a
        pydantic ValidationError and the ParsedMessage never exists. The offending value travels in
        each error's `input`, which is the whole response body when the model returned prose
        (a refusal) or stopped mid-object (a truncation), and the offending sub-object otherwise —
        so the failure is reported with the model's own words, not just a type name."""
        lines = [f"{'.'.join(str(p) for p in err['loc']) or '(whole response)'}: {err['msg']}\n"
                 f"      model sent: {err['input']!r}"[:600] for err in e.errors()[:5]]
        return cls("the model's output does not satisfy the extraction contract:\n    "
                   + "\n    ".join(lines))


class ReplayMismatch(ExtractionUnavailable):
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
        for label, recorded, current in (("input", rec.get("input_sha256"), sha256_of(user)),
                                         ("prompt", rec.get("prompt_sha256"), sha256_of(system)),
                                         ("schema", rec.get("schema_sha256"), SCHEMA_SHA256),
                                         ("schema_version", rec.get("schema_version"), SCHEMA_VERSION)):
            if recorded != current:
                raise ReplayMismatch(
                    f"recording {path} was made under a different {label} "
                    f"({recorded} != {current}) — re-record with --live --record")
        meta = {k: rec[k] for k in ("model", "ts", "usage", "key") if k in rec}
        meta["replayed_from"] = str(path)
        return ExtractionResult.model_validate(rec["raw"]), meta


def record(meta: dict, directory: str | Path = "fixtures/recorded") -> Path:
    d = Path(directory); d.mkdir(parents=True, exist_ok=True)
    p = d / f"{meta['key']}.json"
    p.write_text(json.dumps(meta, indent=2))
    return p
