"""Encoding and decoding of WebSocket frames.

decode_* checks the protocol version before anything else, so a frame from another
revision fails with ProtocolVersionMismatch and not with a list of field errors.
"""

import json
from typing import Any, Dict, Union

from pydantic import TypeAdapter, ValidationError

from scenegems_tool.cluster.protocol.messages import ControlNodeMessage, WorkerNodeMessage
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.cluster.protocol.version import ensure_compatible

_WORKER_NODE_MESSAGES: TypeAdapter = TypeAdapter(WorkerNodeMessage)
_CONTROL_NODE_MESSAGES: TypeAdapter = TypeAdapter(ControlNodeMessage)


class MalformedFrame(ValueError):
    """The frame is not JSON, has no known type, or does not match its type's fields."""


def encode(frame: ProtocolFrame) -> str:
    return frame.model_dump_json()


def decode_worker_node_message(text: Union[str, bytes]) -> WorkerNodeMessage:
    """Decode a frame the control node received from a worker node."""
    return _decode(text, _WORKER_NODE_MESSAGES)


def decode_control_node_message(text: Union[str, bytes]) -> ControlNodeMessage:
    """Decode a frame the worker node received from the control node."""
    return _decode(text, _CONTROL_NODE_MESSAGES)


def _decode(text: Union[str, bytes], adapter: TypeAdapter) -> Any:
    data = _parse_object(text)
    ensure_compatible(data.get("protocol_version"))
    try:
        return adapter.validate_python(data)
    except ValidationError as error:
        raise MalformedFrame(f"Invalid {data.get('type', 'untyped')!s} frame: {error}") from error


def _parse_object(text: Union[str, bytes]) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as error:
        raise MalformedFrame(f"Frame is not JSON: {error}") from error
    if not isinstance(data, dict):
        raise MalformedFrame(f"Frame must be a JSON object, got {type(data).__name__}")
    return data
