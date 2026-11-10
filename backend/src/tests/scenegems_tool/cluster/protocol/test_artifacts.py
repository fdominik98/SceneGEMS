"""Artifact references: their shape, payload fields that take one, and the pure walk, resolve and store helpers."""

import hashlib
import json
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.protocol.artifacts import (
    ArtifactContent,
    ArtifactField,
    ArtifactKind,
    ArtifactRef,
    artifact_or,
    encode_document,
    find_references,
    is_reference,
    json_pointer,
    resolve_references,
    store_results,
)
from scenegems_tool.cluster.protocol.model_base import ProtocolModel

DOCUMENT = {"trajectories": {"time_step": 1, "scene_list": [{"a": 1}]}, "random_seed": 7}


def _reference(document: Any, kind: ArtifactKind = ArtifactKind.TRAJECTORY_DATA, **fields) -> ArtifactRef:
    data = encode_document(document, ArtifactContent.JSON)
    return ArtifactRef(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), kind=kind, **fields)


class _Payload(ProtocolModel):
    document: artifact_or(Dict[str, Any])
    text: artifact_or(str) = ""
    many: List[artifact_or(Dict[str, Any])] = []


def test_a_reference_names_a_sha256_in_lowercase_hex():
    reference = ArtifactRef(sha256="ab" * 32, size_bytes=10, kind="trajectories")
    assert reference.media_type == "application/json" and reference.pointer is None
    for sha256 in ("AB" * 32, "ab" * 31, "zz" * 32):
        with pytest.raises(ValidationError):
            ArtifactRef(sha256=sha256, size_bytes=10, kind="trajectories")
    with pytest.raises(ValidationError):
        ArtifactRef(sha256="ab" * 32, size_bytes=-1, kind="trajectories")
    with pytest.raises(ValidationError):
        ArtifactRef(sha256="ab" * 32, size_bytes=1, kind="video")
    with pytest.raises(ValidationError):
        ArtifactRef(sha256="ab" * 32, size_bytes=1, kind="scene", pointer="trajectories")


def test_the_kinds_are_stable_wire_values():
    assert {kind.value for kind in ArtifactKind} == {"functional_scenario", "scene", "trajectory_data", "trajectories", "frames", "calibration"}


def test_a_field_takes_inline_data_or_a_reference():
    reference = _reference(DOCUMENT)
    inline = _Payload.model_validate({"document": DOCUMENT, "text": "{}"})
    referenced = _Payload.model_validate({"document": reference.model_dump(mode="json"), "text": reference.model_dump(mode="json")})
    assert inline.document == DOCUMENT and inline.text == "{}"
    assert referenced.document == reference and referenced.text == reference
    assert referenced.model_dump(mode="json")["document"]["sha256"] == reference.sha256


def test_a_reference_shaped_value_is_checked_as_a_reference():
    with pytest.raises(ValidationError, match="reference"):
        _Payload.model_validate({"document": {"sha256": "not hex", "size_bytes": 1, "kind": "scene"}})
    with pytest.raises(ValidationError):
        _Payload.model_validate({"document": {"sha256": "ab" * 32, "size_bytes": 1, "kind": "scene", "extra": 1}})


def test_find_references_walks_dicts_lists_and_models():
    first, second = _reference({"x": 1}), _reference({"x": 2}, pointer="/x")
    payload = {"document": first.model_dump(mode="json"), "nested": {"list": [1, second.model_dump(mode="json")]}, "plain": {"time_step": 1}}
    assert find_references(payload) == [(("document",), first), (("nested", "list", 1), second)]
    assert find_references(_Payload.model_validate({"document": first.model_dump(mode="json"), "many": [{"a": 1}, second.model_dump(mode="json")]})) == [
        (("document",), first),
        (("many", 1), second),
    ]
    assert find_references({"document": DOCUMENT}) == []
    assert is_reference(first) and not is_reference(DOCUMENT)


def test_json_pointer():
    document = {"a": {"b/c": [10, {"~d": 4}]}}
    assert json_pointer(document, None) is document and json_pointer(document, "") is document
    assert json_pointer(document, "/a/b~1c/0") == 10
    assert json_pointer(document, "/a/b~1c/1/~0d") == 4
    with pytest.raises(KeyError):
        json_pointer(document, "/missing")


def test_resolve_replaces_declared_references_with_their_content():
    whole = _reference(DOCUMENT)
    part = _reference(DOCUMENT, pointer="/trajectories")
    store = {whole.sha256: encode_document(DOCUMENT, ArtifactContent.JSON)}
    fields = (ArtifactField("document", ArtifactKind.TRAJECTORIES), ArtifactField("text", ArtifactKind.SCENE, ArtifactContent.TEXT), ArtifactField("many", ArtifactKind.TRAJECTORIES, many=True))
    loaded = []

    def load(reference: ArtifactRef) -> bytes:
        loaded.append(reference)
        return store[reference.sha256]

    payload = {"document": part.model_dump(mode="json"), "text": whole.model_dump(mode="json"), "many": [DOCUMENT, whole], "other": whole.model_dump(mode="json")}
    resolved = resolve_references(payload, fields, load)
    assert resolved["document"] == DOCUMENT["trajectories"]
    assert json.loads(resolved["text"]) == DOCUMENT  # a text field gets the document as a string
    assert resolved["many"] == [DOCUMENT, DOCUMENT]
    assert resolved["other"] == payload["other"]  # not declared: stays, so parsing reports it
    assert len(loaded) == 3
    assert payload["document"] == part.model_dump(mode="json")  # the input is not changed


def test_a_text_field_gets_the_stored_text_unchanged():
    text = '{"best_scene": {"x": 1.50}}'
    data = text.encode("utf-8")
    reference = ArtifactRef(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), kind="scene")
    resolved = resolve_references({"text": reference.model_dump(mode="json")}, (ArtifactField("text", ArtifactKind.SCENE, ArtifactContent.TEXT),), lambda _: data)
    assert resolved["text"] == text


def test_store_results_puts_declared_fields_and_leaves_the_rest():
    stored: Dict[str, bytes] = {}

    def put(field: ArtifactField, data: bytes) -> ArtifactRef:
        sha256 = hashlib.sha256(data).hexdigest()
        stored[sha256] = data
        return ArtifactRef(sha256=sha256, size_bytes=len(data), kind=field.kind)

    fields = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES), ArtifactField("frames", ArtifactKind.FRAMES))
    result = {"trajectories": {"b": 2, "a": 1}, "state_digest": "d", "frames": None}
    replaced = store_results(result, fields, put)
    reference = ArtifactRef.model_validate(replaced["trajectories"])
    assert stored[reference.sha256] == b'{"a":1,"b":2}'  # canonical: compact, sorted keys
    assert replaced["state_digest"] == "d" and replaced["frames"] is None
    assert store_results(replaced, fields, put) == replaced  # a reference is not stored again


def test_encoding_is_canonical_and_refuses_non_finite_numbers():
    assert encode_document({"b": 1, "a": [1.5]}, ArtifactContent.JSON) == encode_document({"a": [1.5], "b": 1}, ArtifactContent.JSON)
    assert encode_document("text", ArtifactContent.TEXT) == b"text"
    with pytest.raises(ValueError):
        encode_document({"a": float("nan")}, ArtifactContent.JSON)


def test_store_results_puts_each_item_of_a_list_field_as_an_artifact_of_its_own():
    stored: Dict[str, bytes] = {}

    def put(field: ArtifactField, data: bytes) -> ArtifactRef:
        sha256 = hashlib.sha256(data).hexdigest()
        stored[sha256] = data
        return ArtifactRef(sha256=sha256, size_bytes=len(data), kind=field.kind)

    fields = (ArtifactField("functional_scenarios", ArtifactKind.FUNCTIONAL_SCENARIO, ArtifactContent.TEXT, many=True),)
    kept = _reference("class C.", ArtifactKind.FUNCTIONAL_SCENARIO)
    replaced = store_results({"functional_scenarios": ["class A.\n", kept, "class B.\n"], "models_found": 3}, fields, put)
    references = [ArtifactRef.model_validate(item) for item in replaced["functional_scenarios"]]
    assert [stored.get(reference.sha256) for reference in references] == [b"class A.\n", None, b"class B.\n"]  # a reference in the list stays as it is
    assert references[1] == kept and replaced["models_found"] == 3
    assert store_results(replaced, fields, put) == replaced
    assert store_results({"functional_scenarios": []}, fields, put) == {"functional_scenarios": []}
    # resolving gives the texts back, item by item
    assert resolve_references(replaced, fields, lambda reference: stored.get(reference.sha256, b"class C."))["functional_scenarios"] == ["class A.\n", "class C.", "class B.\n"]
