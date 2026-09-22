"""Everything that talks to the AI model, kept in one file.

The rest of the project never calls the model directly. It asks for a ModelClient and uses that.
Swapping this file for a client that calls Coinbase's own gateway would not change anything else.

There are two of them.

LiveClient makes a real call. It sends the message, the instructions, and a description of the
shape of answer we accept, so the model is forced to reply in that shape.

Getting a reply back is not the same as getting an extraction. Three things can come back instead,
and each one raises an error rather than being passed along as a half-filled result:

    the model declined to answer;
    the answer was cut off before it finished;
    the answer arrived but broke one of our rules, so the contract threw it out.

The third case hands back the model's own words, which is what makes the instructions fixable. See
ExtractionRejected for why the first two arrive the same way.

ReplayClient returns a real answer that was recorded earlier, so the demo and the tests run with no
API key and no network. It is a recording of a genuine call, never a hand-written answer.

A recording is filed under a key made from three things: the message, the instructions, and the
shape we asked for. Change any of them and there is no recording under the new key, so replay
stops and says to re-record. It can never quietly answer a question it was not asked.
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

    The key covers the instructions and the message, which is obvious, and also a hash of the
    shape we asked the model for, which is less obvious and was added after this went wrong.

    SCHEMA_VERSION above is a label a person types. It stayed at "extraction-v1" through two real
    changes to the shape in a single afternoon: a dictionary became a list, and then the field
    order changed. Had replay relied on that label, it would have handed back an answer produced
    under a shape that no longer exists, and the test would have passed. Hashing the shape itself
    removes the need for anyone to remember."""
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
            # We land here whenever the reply is not something our contract accepts.
            #
            # That covers more than a broken answer. The library checks the reply against our
            # classes inside the call above, so a refusal (plain prose) and a cut-off answer (half
            # a sentence of JSON) both fail here as "that is not valid JSON" before the
            # stop_reason checks further down ever get to run.
            #
            # The error carries the text the model actually sent, so we can see what happened.
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

        The library checks the reply against our classes inside the call itself, so when the reply
        breaks a rule we never get a response object to inspect. What we get is a validation error.

        That error is more useful than it looks: it carries the value that failed. When the model
        returned prose instead of an answer, that value is the whole reply. When the answer was cut
        off, it is the partial text. When a single field broke a rule, it is that field. So the
        message below can always show what the model actually said, not just which rule it broke."""
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
