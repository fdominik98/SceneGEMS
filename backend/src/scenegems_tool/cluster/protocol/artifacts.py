"""Artifact references: large job data stored once, by content hash, and named in payloads and results.

A payload field that holds large data (trajectories, a scene) takes either the data inline
or an ArtifactRef. The master checks a reference's shape only; the node downloads the
artifact, checks its hash, puts the content in place of the reference (resolve_references)
and only then validates the content with the job type's payload model.

Each job type module declares its fields with ArtifactField:

    ARTIFACT_INPUT_FIELDS   payload fields that may hold a reference
    ARTIFACT_RESULT_FIELDS  result fields large enough to be uploaded and replaced by a reference

A reference may point into its document (pointer, RFC 6901), so a stage can take the
trajectories out of a trajectory generation result without storing them a second time.
Everything here is pure: the store and the transport are injected (load, put).
"""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, Discriminator, Field, Tag, field_validator

from scenegems_tool.cluster.protocol.model_base import ProtocolModel

SHA256_PATTERN = r"^[0-9a-f]{64}$"
JSON_MEDIA_TYPE = "application/json"
TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"

PayloadPath = Tuple[Union[str, int], ...]  # keys and list indices from the payload's top level


class ArtifactKind(str, Enum):
    FUNCTIONAL_SCENARIO = "functional_scenario"  # a functional scenario (.problem text)
    SCENE = "scene"  # a scene or the scene generation's EvaluationData
    TRAJECTORY_DATA = "trajectory_data"  # trajectory generation's TrajectoryData payload
    TRAJECTORIES = "trajectories"  # Trajectories: generated trajectories or a run's state log
    FRAMES = "frames"  # monitored frames in the workbench's wire format
    CALIBRATION = "calibration"  # a calibration result


class ArtifactRef(ProtocolModel):
    sha256: str = Field(pattern=SHA256_PATTERN)  # of the stored bytes before compression, 64 lowercase hex characters
    size_bytes: int = Field(ge=0)
    kind: ArtifactKind
    media_type: str = JSON_MEDIA_TYPE
    pointer: Optional[str] = None  # JSON pointer into the document, such as "/trajectories"; the whole document when None

    @field_validator("pointer")
    @classmethod
    def _pointer_syntax(cls, pointer: Optional[str]) -> Optional[str]:
        if pointer is not None and pointer != "" and not pointer.startswith("/"):
            raise ValueError("a JSON pointer starts with '/'")
        return pointer


class ArtifactContent(str, Enum):
    JSON = "json"  # the field holds the parsed JSON document
    TEXT = "text"  # the field holds the document as a string


@dataclass(frozen=True)
class ArtifactField:
    """A top-level payload or result field that holds large data."""

    name: str
    kind: ArtifactKind
    content: ArtifactContent = ArtifactContent.JSON
    many: bool = False  # a list whose items are each inline data or a reference


def is_reference(value: Any) -> bool:
    """A reference as a model or in its wire form; inline data never has a sha256 key."""
    return isinstance(value, ArtifactRef) or (isinstance(value, Mapping) and "sha256" in value)


def _reference_or_inline(value: Any) -> str:
    return "reference" if is_reference(value) else "inline"


def artifact_or(inline: Any) -> Any:
    """The type of a payload field that takes inline data of type `inline` or an ArtifactRef.

    A reference is recognized by its sha256 key and checked for shape only; inline data gets
    the inline type's own checks.
    """
    return Annotated[Union[Annotated[ArtifactRef, Tag("reference")], Annotated[inline, Tag("inline")]], Discriminator(_reference_or_inline)]


def find_references(value: Any, path: PayloadPath = ()) -> List[Tuple[PayloadPath, ArtifactRef]]:
    """Every reference in a payload or result, with its path, in document order."""
    if isinstance(value, BaseModel) and not isinstance(value, ArtifactRef):
        value = value.model_dump(mode="json")
    if is_reference(value):
        return [(path, value if isinstance(value, ArtifactRef) else ArtifactRef.model_validate(value))]
    if isinstance(value, Mapping):
        return [found for key, item in value.items() for found in find_references(item, path + (key,))]
    if isinstance(value, (list, tuple)):
        return [found for index, item in enumerate(value) for found in find_references(item, path + (index,))]
    return []


def json_pointer(document: Any, pointer: Optional[str]) -> Any:
    """The part of a JSON document a pointer names (RFC 6901)."""
    if not pointer:
        return document
    value = document
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        elif isinstance(value, Mapping):
            value = value[token]
        else:
            raise KeyError(f"JSON pointer {pointer} goes past a value")
    return value


def decode_reference(reference: ArtifactRef, data: bytes, content: ArtifactContent) -> Any:
    """The value a field gets in place of the reference, from the artifact's bytes."""
    if content == ArtifactContent.TEXT and reference.pointer is None:
        return data.decode("utf-8")
    value = json_pointer(json.loads(data.decode("utf-8")), reference.pointer)
    if content == ArtifactContent.TEXT and not isinstance(value, str):
        return json.dumps(value)
    return value


def encode_document(value: Any, content: ArtifactContent) -> bytes:
    """The bytes an artifact stores for a field value: compact JSON with sorted keys, or the text itself."""
    if content == ArtifactContent.TEXT and isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def resolve_references(payload: Mapping[str, Any], fields: Sequence[ArtifactField], load: Callable[[ArtifactRef], bytes]) -> Dict[str, Any]:
    """A copy of the payload with every reference in a declared field replaced by its content.

    load returns the artifact's bytes after the hash check. A reference outside the declared
    fields stays, so parsing the payload afterwards reports it.
    """
    resolved = dict(payload)
    for field in fields:
        if field.name not in resolved:
            continue
        value = resolved[field.name]
        if field.many and isinstance(value, (list, tuple)):
            resolved[field.name] = [_resolved(item, field, load) for item in value]
        else:
            resolved[field.name] = _resolved(value, field, load)
    return resolved


def _resolved(value: Any, field: ArtifactField, load: Callable[[ArtifactRef], bytes]) -> Any:
    if not is_reference(value):
        return value
    reference = value if isinstance(value, ArtifactRef) else ArtifactRef.model_validate(value)
    return decode_reference(reference, load(reference), field.content)


def store_results(result: Mapping[str, Any], fields: Sequence[ArtifactField], put: Callable[[ArtifactField, bytes], ArtifactRef]) -> Dict[str, Any]:
    """A copy of a job result with every declared field present stored and replaced by its reference (wire form).

    A field declared many holds a list: each item that is not a reference already is stored as an artifact of its own.
    """
    stored = dict(result)
    for field in fields:
        value = stored.get(field.name)
        if value is None or is_reference(value):
            continue
        if field.many and isinstance(value, (list, tuple)):
            stored[field.name] = [item if is_reference(item) else put(field, encode_document(item, field.content)).model_dump(mode="json") for item in value]
        else:
            stored[field.name] = put(field, encode_document(value, field.content)).model_dump(mode="json")
    return stored
