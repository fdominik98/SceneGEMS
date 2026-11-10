"""A control socket that records what the control node sends, for tests without a WebSocket."""

from typing import List, Optional, Type, TypeVar

from scenegems_tool.cluster.protocol.model_base import ProtocolFrame

Frame = TypeVar("Frame")


class RecordingSocket:
    def __init__(self, deliverable: bool = True):
        self.deliverable = deliverable
        self.frames: List[ProtocolFrame] = []
        self.closed_with: Optional[int] = None

    async def send(self, frame: ProtocolFrame) -> bool:
        if not self.deliverable:
            return False
        self.frames.append(frame)
        return True

    async def close(self, code: int, reason: str) -> None:
        self.closed_with = code

    def of_type(self, frame_type: Type[Frame]) -> List[Frame]:
        return [frame for frame in self.frames if isinstance(frame, frame_type)]
