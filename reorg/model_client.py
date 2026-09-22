"""Not a stage · the model seam — everything that talks to the AI model, in one file.

The rest of the project never calls the model directly; it asks for a ModelClient. Swapping this
file for one that calls Coinbase's own gateway would change nothing else.

LiveClient makes a real call, sending the message, the instructions, and a description of the shape
of answer we accept, so the model is forced to reply in that shape.

Getting a reply is not the same as getting an extraction. Three things can come back instead, and
each raises rather than being passed on as a half-filled result:

    the model declined to answer;
    the answer was cut off before it finished;
    the answer arrived but broke one of our rules, so the contract threw it out.

The third hands back the model's own words, which is what makes the instructions fixable; see
ExtractionRejected for why the first two arrive the same way.

ReplayClient returns a real answer recorded earlier, so the demo and the tests run with no API key
and no network. It is a recording of a genuine call, never a hand-written answer. The recording is
filed under a key made from the message, the instructions and the shape asked for — change any of
them and there is no recording, so replay stops and says to re-record rather than quietly answering
a question it was not asked.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from .contracts import ExtractionResult, now_iso, sha256_of

MODEL_ID = "claude-opus-5"
SCHEMA_VERSION = "extraction-v1"  # human label, for the audit trail
SCHEMA_SHA256 = sha256_of(
    ExtractionResult.model_json_schema()
)  # what actually binds a recording


def _load_dotenv() -> None:
    p = Path(".env")
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def recording_key(system: str, user: str) -> str:
    """Build the filename a recording is stored under.

    Covers the instructions, the message, and — less obviously — a hash of the shape we asked for.
    SCHEMA_VERSION above is a label a person types and therefore forgets; hashing the schema itself
    means a recording cannot survive a change to the shape it was produced under."""
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
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=ExtractionResult,
            )
        except ValidationError as e:
            # Any reply the contract does not accept lands here — including a refusal (prose) and a
            # cut-off answer (half a sentence of JSON), both of which fail as invalid JSON inside
            # the library's own check, before the stop_reason tests below can run.
            raise ExtractionRejected.from_validation_error(e) from e
        if resp.stop_reason == "refusal":
            raise ExtractionUnavailable(
                f"model declined to answer (stop_details={resp.stop_details})"
            )
        if resp.stop_reason == "max_tokens":
            raise ExtractionUnavailable(
                "output hit max_tokens — the extraction is truncated, not partial"
            )
        if resp.parsed_output is None:
            raise ExtractionUnavailable(
                f"no parsed output (stop_reason={resp.stop_reason})"
            )
        result: ExtractionResult = resp.parsed_output
        meta = {
            "key": recording_key(system, user),
            "schema_version": SCHEMA_VERSION,
            "schema_sha256": SCHEMA_SHA256,
            "input_sha256": sha256_of(user),
            "prompt_sha256": sha256_of(system),
            "model": resp.model,
            "ts": now_iso(),
            "usage": resp.usage.model_dump()
            if hasattr(resp.usage, "model_dump")
            else dict(resp.usage),
            "raw": result.model_dump(mode="json"),
        }
        return result, meta


class ExtractionUnavailable(RuntimeError):
    """The call came back, but not with an extraction.

    Raised rather than returning an empty result, so nothing downstream can mistake "we got
    nothing" for "there was nothing to find"."""


class ExtractionRejected(ExtractionUnavailable):
    """The model answered, and our own rules threw the answer out.

    Carries the text the model actually sent, so the instructions can be fixed."""

    @classmethod
    def from_validation_error(cls, e: ValidationError) -> ExtractionRejected:
        """Turn the library's validation error into a readable one.

        The check happens inside the call, so a broken reply never becomes a response object we can
        inspect — but the validation error carries the value that failed: the whole reply for prose
        or a truncation, the offending field otherwise. So the message can always show what the
        model actually said, not just which rule it broke."""
        lines = [
            f"{'.'.join(str(p) for p in err['loc']) or '(whole response)'}: {err['msg']}\n"
            f"      model sent: {err['input']!r}"[:600]
            for err in e.errors()[:5]
        ]
        return cls(
            "the model's output does not satisfy the extraction contract:\n    "
            + "\n    ".join(lines)
        )


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
                f"Run with --live --record to create one; replay never substitutes another message's answer."
            )
        rec = json.loads(path.read_text())
        for label, recorded, current in (
            ("input", rec.get("input_sha256"), sha256_of(user)),
            ("prompt", rec.get("prompt_sha256"), sha256_of(system)),
            ("schema", rec.get("schema_sha256"), SCHEMA_SHA256),
            ("schema_version", rec.get("schema_version"), SCHEMA_VERSION),
        ):
            if recorded != current:
                raise ReplayMismatch(
                    f"recording {path} was made under a different {label} "
                    f"({recorded} != {current}) — re-record with --live --record"
                )
        meta = {k: rec[k] for k in ("model", "ts", "usage", "key") if k in rec}
        meta["replayed_from"] = str(path)
        return ExtractionResult.model_validate(rec["raw"]), meta


def record(meta: dict, directory: str | Path = "fixtures/recorded") -> Path:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{meta['key']}.json"
    p.write_text(json.dumps(meta, indent=2))
    return p
