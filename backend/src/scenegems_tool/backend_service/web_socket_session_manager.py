from __future__ import annotations

from typing import Dict, Tuple

from fastapi import WebSocket

from scenegems_tool.backend_service.socket_message_processor import SocketMessageProcessor
from scenegems_tool.backend_service.socket_session import SocketSession


class WebSocketSessionManager:
    """Keeps per-WebSocket-connection `SocketSession` instances keyed by connection id."""

    def __init__(self) -> None:
        self._sessions_by_connection: Dict[str, Tuple[SocketSession, SocketMessageProcessor]] = {}

    def create_session(self, websocket: WebSocket) -> Tuple[SocketSession, SocketMessageProcessor]:
        session = SocketSession(websocket=websocket)
        message_processor = SocketMessageProcessor(session=session)
        self._sessions_by_connection[str(id(websocket))] = (session, message_processor)
        return session, message_processor

    def get_session(self, websocket: WebSocket) -> Tuple[SocketSession, SocketMessageProcessor]:
        if str(id(websocket)) not in self._sessions_by_connection:
            return self.create_session(websocket)
        return self._sessions_by_connection[str(id(websocket))]

    def remove_session(self, websocket: WebSocket) -> None:
        session, message_processor = self._sessions_by_connection.pop(str(id(websocket)), (None, None))
        if session is None or message_processor is None:
            return
        session.cancel()
        message_processor.cancel()
        self._sessions_by_connection.pop(str(id(websocket)), None)

    def shutdown_all(self) -> None:
        sessions = list(self._sessions_by_connection.values())
        self._sessions_by_connection.clear()
        for session, message_processor in sessions:
            if session is not None:
                session.cancel()
            if message_processor is not None:
                message_processor.cancel()
