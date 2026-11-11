"""How a per-job runner container receives its job and hands back its result.

The launcher copies the job document into the created container before it starts and
copies the result document out after it stops, so the caller needs only the Docker CLI,
not a volume shared with the container. While it runs, the container writes status lines
to stdout with STATUS_LINE_PREFIX; every other line is a log line. A status may carry a detail:
a small object that says more than the message, such as the phase of an attended simulation
or the ports its stack published (the keys are in cluster/protocol/messages.py).

Observation (live simulations), with the container still without network:
    in   the launcher copies OBSERVE_DOCUMENT into JOB_FOLDER whenever the control node's request
         changes (observe on or off, a speed, the operator's Start of an attended simulation); the
         runner reads it between steps and while it waits for the Start, at most a few times a second;
    out  while observed, the runner writes each frame as one stdout line with FRAME_LINE_PREFIX,
         which the launcher's log follower takes out of the log and hands to the job's
         observation. Nothing is written while nobody observes.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

JOB_FOLDER = "/job"
JOB_DOCUMENT = "job.json"  # {"job": JobSpec}
RESULT_DOCUMENT = "result.json"  # {"result": {...}} or {"error": "...", "retryable": bool}
JOB_CONTAINER_MAIN = "scenegems_tool.cluster.worker_node.jobs.in_container.job_container_main"
STATUS_LINE_PREFIX = "scenegems-status "
OBSERVE_DOCUMENT = "observe.json"  # {"active": bool, "speed": float, "revision": int, "started": bool}
FRAME_LINE_PREFIX = "scenegems-frame "


def format_status_line(message: str, progress: Optional[float] = None, detail: Optional[Dict[str, Any]] = None) -> str:
    status: Dict[str, Any] = {"message": message, "progress": progress}
    if detail:
        status["detail"] = detail
    return STATUS_LINE_PREFIX + json.dumps(status)


def parse_status_line(line: str) -> Optional[Tuple[str, Optional[float]]]:
    """(message, progress) of a status line, None for a log line."""
    if not line.startswith(STATUS_LINE_PREFIX):
        return None
    try:
        status = json.loads(line[len(STATUS_LINE_PREFIX) :])
        return str(status["message"]), status.get("progress")
    except (ValueError, KeyError, TypeError):
        return None


def parse_status(line: str) -> Optional[Tuple[str, Optional[float], Optional[Dict[str, Any]]]]:
    """(message, progress, detail) of a status line, None for a log line; the detail is None unless it is an object."""
    if not line.startswith(STATUS_LINE_PREFIX):
        return None
    try:
        status = json.loads(line[len(STATUS_LINE_PREFIX) :])
        detail = status.get("detail")
        return str(status["message"]), status.get("progress"), detail if isinstance(detail, dict) else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


@dataclass(frozen=True)
class ObservationControl:
    """What the runner of an observable job is asked: observe (active) at speed times real time, and, for an attended
    simulation, to start its run (started); revision counts the requests."""

    active: bool = False
    speed: float = 1.0
    revision: int = 0
    started: bool = False

    def to_document(self) -> str:
        return json.dumps({"active": self.active, "speed": self.speed, "revision": self.revision, "started": self.started})

    @classmethod
    def from_document(cls, text: str) -> "ObservationControl":
        """Raises ValueError for anything but a complete document (a copy in progress, for example)."""
        try:
            document = json.loads(text)
            control = cls(active=bool(document["active"]), speed=float(document["speed"]), revision=int(document["revision"]), started=bool(document.get("started", False)))
        except (TypeError, KeyError, AttributeError) as error:
            raise ValueError(f"not an observation document: {error}") from error
        if not control.speed > 0.0:
            raise ValueError(f"the speed must be positive, got {control.speed}")
        return control


def format_frame_line(frame_json: str) -> str:
    """The stdout line of one frame, already encoded as JSON on one line."""
    return FRAME_LINE_PREFIX + frame_json


def parse_frame_line(line: str) -> Optional[Dict[str, Any]]:
    """The frame of a frame line; None for any other line or a frame that does not decode."""
    if not line.startswith(FRAME_LINE_PREFIX):
        return None
    try:
        frame = json.loads(line[len(FRAME_LINE_PREFIX) :])
    except ValueError:
        return None
    return frame if isinstance(frame, dict) else None
