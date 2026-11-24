"""A series of monitored frames without what repeats from frame to frame: what is left out, and that nothing is lost."""

import json

import pytest

from scenegems_tool.gateway.frame_series import CARRY_FORWARD, ENCODED_FRAMES_KEY, ENCODING_KEY, decode_frames, encode_frames, is_encoded

ACTORS = [{"id": "0", "name": "os", "length": 30.0}, {"id": "1", "name": "ts1", "length": 50.0}]
RULES = [{"relationId": "0->1", "isFailed": False, "rules": [{"ruleId": "rule:16", "result": "PASSED", "description": "The give-way vessel acts early." * 4}]}]
FAILED = [{"relationId": "0->1", "isFailed": True, "rules": [{"ruleId": "rule:16", "result": "FAILED", "description": "The give-way vessel acts early." * 4}]}]


def frame(timestamp, rules=RULES, x=None):
    return {"timestamp": timestamp, "timeStep": 1, "actors": ACTORS, "statesByActorId": {"0": {"x": float(timestamp if x is None else x), "y": 0.0}}, "ruleResults": rules}


def test_a_section_that_equals_the_previous_frames_is_left_out():
    frames = [frame(0), frame(1), frame(2, FAILED), frame(3, FAILED)]
    encoded = encode_frames(frames)
    assert encoded[ENCODING_KEY] == CARRY_FORWARD
    first, second, third, fourth = encoded[ENCODED_FRAMES_KEY]
    assert first == frames[0], "the first frame is whole"
    assert set(second) == {"timestamp", "statesByActorId"}, "the vessels, the time step and the rule results did not change"
    assert set(third) == {"timestamp", "statesByActorId", "ruleResults"} and third["ruleResults"] == FAILED, "a section that changed is written whole"
    assert set(fourth) == {"timestamp", "statesByActorId"}


def test_decoding_gives_the_frames_as_they_were():
    frames = [frame(0), frame(1), frame(2, FAILED), frame(3, FAILED), frame(4), frame(5, x=4)]
    stored = json.loads(json.dumps(encode_frames(frames)))  # as an artifact holds it
    assert decode_frames(stored) == frames
    assert len(json.dumps(stored)) < len(json.dumps(frames)) / 2


def test_a_frame_in_which_nothing_changed_is_empty_and_comes_back_whole():
    still = {"timestamp": 7, "actors": ACTORS}
    encoded = encode_frames([still, dict(still), dict(still)])
    assert encoded[ENCODED_FRAMES_KEY] == [still, {}, {}]
    assert decode_frames(encoded) == [still, still, still]


def test_a_section_that_changes_to_null_or_empty_is_written():
    frames = [{"timestamp": 0, "metrics": {"dcpa": 1.0}, "ruleResults": RULES}, {"timestamp": 1, "metrics": None, "ruleResults": []}]
    encoded = encode_frames(frames)
    assert encoded[ENCODED_FRAMES_KEY][1] == {"timestamp": 1, "metrics": None, "ruleResults": []}
    assert decode_frames(encoded) == frames


@pytest.mark.parametrize(
    "frames",
    [
        [],
        [frame(0)],
        [frame(0), {"timestamp": 1, "actors": ACTORS}],  # a section is missing in the second frame: left out and not there would read the same
        [{"timestamp": 0}, {"timestamp": 1, "ruleResults": RULES}],  # a section appears later
        [frame(0), None],
        [[1, 2], [3, 4]],
    ],
)
def test_a_series_the_encoding_does_not_fit_stays_a_plain_list(frames):
    encoded = encode_frames(frames)
    assert encoded == frames and isinstance(encoded, list) and not is_encoded(encoded)
    assert decode_frames(encoded) == frames


def test_the_given_frames_are_not_changed():
    frames = [frame(0), frame(1)]
    before = json.dumps(frames)
    encode_frames(frames)
    decode_frames(encode_frames(frames))
    assert json.dumps(frames) == before


@pytest.mark.parametrize(
    "value",
    [None, "frames", {"frames": []}, {ENCODING_KEY: "delta", ENCODED_FRAMES_KEY: []}, {ENCODING_KEY: CARRY_FORWARD}, {ENCODING_KEY: CARRY_FORWARD, ENCODED_FRAMES_KEY: [{"timestamp": 0}, 5]}],
)
def test_what_is_no_series_of_frames_is_refused(value):
    with pytest.raises(ValueError):
        decode_frames(value)
