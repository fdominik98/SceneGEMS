"""One pipeline engine per database: the leader holds a Postgres advisory lock.

The engine that holds the session-level advisory lock ENGINE_LOCK on a connection of its
own leads and ticks. Any other engine on the database stands by and tries again every tick,
so a second control node process takes over once the first one's connection ends (the process
died or lost its database). The connection runs in autocommit, so holding the lock never
keeps a transaction open: an open transaction would hold back the cursor's snapshot horizon
(persistence/stores/pipeline_store.py).

Every tick checks again inside its own transaction, while it holds the cursor row, that the
lock is still held by this engine's connection (holds), so a tick never writes after
another engine took over. The term counts acquisitions: an engine that leads again after a
pause reconciles first, since another engine may have run in between.

Releasing invalidates the connection instead of returning it to the pool: a pooled
connection would keep the session lock for whoever checks it out next.
"""

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

# The lock's two keys (pg_try_advisory_lock(int, int)): SceneGEMS's lock space ("SGEM") and the engine
ENGINE_LOCK = (0x5347454D, 1)

_TRY_LOCK = text("SELECT pg_try_advisory_lock(:space, :key)")
_BACKEND = text("SELECT pg_backend_pid()")
# An advisory lock with two int keys shows in pg_locks as classid, objid and objsubid 2
_HELD_BY = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted AND pid = :pid"
    " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
    " AND classid = CAST(:space AS oid) AND objid = CAST(:key AS oid) AND objsubid = 2)"
)


class LeadershipLost(RuntimeError):
    """The engine lock is no longer held by this engine's connection."""


class EngineLeadership:
    def __init__(self, session_factory: sessionmaker[Session], lock: tuple = ENGINE_LOCK):
        self._sessions = session_factory  # its engine is looked up at the first acquire
        self._space, self._key = lock
        self._connection: Optional[Connection] = None
        self._pid: Optional[int] = None
        self._term = 0

    @property
    def held(self) -> bool:
        return self._connection is not None

    @property
    def term(self) -> int:
        """How often this engine has taken the lock; a new term means another engine may have run meanwhile."""
        return self._term

    def acquire(self) -> bool:
        """True while this engine leads: its lock connection is alive, or the lock was free and is now taken."""
        if self._connection is not None:
            try:
                if self._connection.execute(_BACKEND).scalar() == self._pid:
                    return True
            except Exception as error:
                logger.warning("The pipeline engine lost its lock connection: %s", error)
            self.release()
        connection = self._sessions.kw["bind"].connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            taken = bool(connection.execute(_TRY_LOCK, {"space": self._space, "key": self._key}).scalar())
            pid = connection.execute(_BACKEND).scalar() if taken else None
        except Exception:
            connection.invalidate()
            connection.close()
            raise
        if not taken:
            connection.close()  # it holds no lock, so the pool may have it back
            return False
        self._connection, self._pid = connection, pid
        self._term += 1
        return True

    def holds(self, session: Session) -> bool:
        """Inside a tick's transaction: the lock is held by this engine's connection right now."""
        if self._pid is None:
            return False
        return bool(session.execute(_HELD_BY, {"pid": self._pid, "space": self._space, "key": self._key}).scalar())

    def check(self, session: Session) -> None:
        if not self.holds(session):
            raise LeadershipLost("another pipeline engine holds the engine lock, or this engine's lock connection ended")

    def release(self) -> None:
        """Gives the lock up by closing its connection (the server drops the lock with it)."""
        connection, self._connection, self._pid = self._connection, None, None
        if connection is None:
            return
        try:
            connection.invalidate()
            connection.close()
        except Exception as error:
            logger.warning("Closing the pipeline engine's lock connection failed: %s", error)
