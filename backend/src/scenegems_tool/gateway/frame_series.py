"""A series of monitored frames written without what repeats from frame to frame.

A monitored frame is a mapping of sections (actors, statesByActorId, situationContexts,
colregsStates, ruleResults, maneuverStates, metrics, ...; gateway/serialization.py). Most of a
long series is the same from one frame to the next: the vessels never change, and the rule
results change in a few frames of a run. In the frames of a run of 1600 scenes with three vessels
the rule results are 44 of 59 MB, and 99.8 % of them equal the previous frame's.

encode_frames leaves out of every frame after the first the sections that equal the previous
frame's, and wraps the list so that a reader knows:

    {"encoding": "carry_forward", "encoded_frames": [first frame, {changed sections}, ...]}

decode_frames carries the sections forward again and gives the frames as they were. Nothing is
lost. A series the encoding does not fit (fewer than two frames, a frame that is no mapping, or
frames that do not all have the same sections, where a section left out could not be told from a
section that is not there) stays the plain list of its frames, which decode_frames takes as well.

Two things are written this way: the frames of a monitoring job (monitoring_post_hoc_job.py, its
result's frames, an artifact of kind frames) and the monitor frames of planned trajectories
(trajectory_generation_worker.py, monitor_frames of a result and of a preview). The frames of a
run that is watched go out one batch at a time and are not encoded. The console decodes with
frontend/src/domain/simulation/frameSeries.ts, which must agree with this module.
"""

from typing import Any, Dict, List, Mapping, Sequence, Union

ENCODING_KEY = "encoding"
ENCODED_FRAMES_KEY = "encoded_frames"
CARRY_FORWARD = "carry_forward"

EncodedFrames = Union[List[Any], Dict[str, Any]]


def encode_frames(frames: Sequence[Any]) -> EncodedFrames:
    """The series with every section left out that equals the previous frame's; the plain list when the encoding does not fit it."""
    series = list(frames)
    if len(series) < 2 or not all(isinstance(frame, Mapping) for frame in series):
        return series
    sections = set(series[0])
    if any(set(frame) != sections for frame in series):
        return series
    encoded: List[Dict[str, Any]] = [dict(series[0])]
    for previous, frame in zip(series, series[1:]):
        encoded.append({section: value for section, value in frame.items() if previous[section] != value})
    return {ENCODING_KEY: CARRY_FORWARD, ENCODED_FRAMES_KEY: encoded}


def is_encoded(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get(ENCODING_KEY) == CARRY_FORWARD and isinstance(value.get(ENCODED_FRAMES_KEY), list)


def decode_frames(value: Any) -> List[Any]:
    """The frames of a series as encode_frames was given them, from its encoded form or from a plain list. ValueError for anything else."""
    if isinstance(value, list):
        return value
    if not is_encoded(value):
        raise ValueError("neither a list of frames nor a carry_forward series of frames")
    frames: List[Dict[str, Any]] = []
    carried: Dict[str, Any] = {}
    for changed in value[ENCODED_FRAMES_KEY]:
        if not isinstance(changed, Mapping):
            raise ValueError("a frame of a carry_forward series is a mapping of its changed sections")
        carried = {**carried, **changed}
        frames.append(carried)
    return frames
