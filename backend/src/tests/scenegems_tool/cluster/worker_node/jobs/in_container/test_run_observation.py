"""The runner's side of live observation, on a fake clock whose sleep only moves the time: no wall-clock waits."""

import io
import json

import pytest

from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation, ControlFile, Pacer, RunObserver, frame_stride
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import FRAME_LINE_PREFIX, OBSERVE_DOCUMENT, ObservationControl, parse_frame_line


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Requests:
    """The request as the control file would give it, changed by the test (or at given times)."""

    def __init__(self, control: ObservationControl = ObservationControl()):
        self.control = control
        self.at = []  # (time, control): the request changes once the fake time reaches it
        self.time = None

    def __call__(self) -> ObservationControl:
        while self.at and self.time is not None and self.time() >= self.at[0][0]:
            self.control = self.at.pop(0)[1]
        return self.control


def on(speed: float, revision: int = 1) -> ObservationControl:
    return ObservationControl(active=True, speed=speed, revision=revision)


@pytest.fixture
def fake_time():
    return FakeTime()


def observer(requests, fake_time, frames, dt=1.0, **options) -> RunObserver:
    requests.time = fake_time
    return RunObserver(requests, frames.append, lambda index, states: {"index": index, "states": states}, dt, clock=fake_time, sleep=fake_time.sleep, **options)


def run(observer: RunObserver, steps: int, fake_time=None, step_cost_s: float = 0.0) -> None:
    for index in range(steps + 1):
        if fake_time is not None:
            fake_time.now += step_cost_s  # the step's own computing time
        observer.step(index, (index,))


def test_frame_stride_keeps_the_frame_rate_bounded():
    assert frame_stride(10.0, 1.0) == 1  # 10 steps a second
    assert frame_stride(20.0, 1.0) == 1
    assert frame_stride(21.0, 1.0) == 2
    assert frame_stride(100.0, 1.0) == 5
    assert frame_stride(1000.0, 0.5) == 100
    assert frame_stride(1.0, 0.01) == 5  # 100 steps a second of a fine-grained run
    for speed, dt in ((10.0, 1.0), (55.0, 1.0), (1000.0, 0.1), (3.0, 0.05)):
        assert (speed / dt) / frame_stride(speed, dt) <= 20.0


def test_an_unobserved_run_neither_sleeps_nor_writes(fake_time):
    frames = []
    run(observer(Requests(), fake_time, frames), 100)
    assert frames == [] and fake_time.sleeps == []


def test_an_observed_run_follows_the_speed_in_wall_time(fake_time):
    frames = []
    paced = observer(Requests(on(10.0)), fake_time, frames)
    start = fake_time.now
    run(paced, 100, fake_time, step_cost_s=0.01)
    assert fake_time.now - start == pytest.approx(100 / 10.0 + 0.01)  # 100 s of scenario time at ten times real time, from the first step
    assert [frame["index"] for frame in frames] == list(range(101))  # 10 steps a second: every step is a frame
    assert max(fake_time.sleeps) <= 0.25  # sliced, so a change is seen within a quarter of a second


def test_frames_are_decimated_at_high_speed_and_the_last_step_is_kept(fake_time):
    frames = []
    fast = observer(Requests(on(100.0)), fake_time, frames, last_index=103)
    run(fast, 103, fake_time)
    assert [frame["index"] for frame in frames] == list(range(0, 101, 5)) + [103]
    seconds = fake_time.now - 1000.0
    assert len(frames) - 1 <= 20.0 * seconds + 1  # at most 20 a second, plus the last step's


def test_a_run_that_falls_behind_is_not_hurried(fake_time):
    frames = []
    paced = observer(Requests(on(10.0)), fake_time, frames)
    paced.step(0, ())
    fake_time.now += 5.0  # a slow step: 5 s of wall time for 0.1 s of scenario time
    paced.step(1, ())
    before = fake_time.now
    paced.step(2, ())
    assert fake_time.now - before == pytest.approx(0.1)  # the pace starts again from step 1


def test_observation_starting_mid_run_picks_up_at_the_current_step_and_stops_at_once(fake_time):
    frames = []
    requests = Requests()
    paced = observer(requests, fake_time, frames)
    for index in range(30):
        if index == 10:
            requests.control = on(5.0)
        if index == 20:
            requests.control = ObservationControl(active=False, speed=5.0, revision=2)
        paced.step(index, ())
    assert [frame["index"] for frame in frames] == list(range(10, 20))
    assert sum(fake_time.sleeps) == pytest.approx(9 / 5.0)  # paced from step 10 to step 19 only


def test_a_speed_change_or_a_stop_cuts_a_long_sleep_short(fake_time):
    frames = []
    requests = Requests(on(0.1))  # one step every 10 s of wall time
    paced = observer(requests, fake_time, frames)
    paced.step(0, ())
    requests.at = [(fake_time.now + 1.0, on(10.0, revision=2))]
    paced.step(1, ())
    assert fake_time.now - 1000.0 == pytest.approx(1.0)  # the sleep for step 1 ended with the new speed
    paced.step(2, ())  # re-anchored at the new speed: no wait for the step it picked up at
    paced.step(3, ())
    assert fake_time.now - 1000.0 == pytest.approx(1.1)
    requests.control = on(0.1, revision=3)
    paced.step(4, ())
    requests.at = [(fake_time.now + 0.5, ObservationControl(active=False, speed=0.1, revision=4))]
    paced.step(5, ())  # due 10 s later; the stop half a second in ends the wait, and the step writes no frame
    assert fake_time.now - 1000.0 == pytest.approx(1.6)
    assert [frame["index"] for frame in frames] == [0, 1, 2, 3, 4]


def test_an_unpaced_run_writes_bounded_frames_at_its_own_pace(fake_time):
    frames = []
    sitl = observer(Requests(on(1.0)), fake_time, frames, pace=False, stride_speed=40.0)
    run(sitl, 40, fake_time, step_cost_s=1.0 / 40)
    assert fake_time.sleeps == [] and [frame["index"] for frame in frames] == list(range(0, 41, 2))


def test_pacer_anchors_at_the_first_step_and_at_each_new_speed(fake_time):
    pacer = Pacer(fake_time)
    assert pacer.delay(0.0, 2.0) == 0.0
    assert pacer.delay(4.0, 2.0) == pytest.approx(2.0)
    assert pacer.delay(4.0, 4.0) == 0.0  # new speed: new anchor
    assert pacer.delay(8.0, 4.0) == pytest.approx(1.0)


def test_the_control_file_is_read_at_a_bounded_rate_and_a_partial_copy_keeps_the_last_request(tmp_path, fake_time):
    path = tmp_path / OBSERVE_DOCUMENT
    control = ControlFile(str(path), fake_time, check_interval_s=0.25)
    assert control() == ObservationControl()  # no file: not observed
    path.write_text(on(30.0).to_document(), encoding="utf-8")
    assert control() == ObservationControl()  # read again only after the interval
    fake_time.now += 0.25
    assert control() == on(30.0)
    for _ in range(100):
        control()
    assert control.reads == 1
    path.write_text('{"active": true, "spe', encoding="utf-8")  # a copy in progress
    fake_time.now += 0.25
    assert control() == on(30.0) and control.reads == 2


def test_the_container_writes_each_frame_as_one_json_line(tmp_path, fake_time):
    out = io.StringIO()
    observation = ContainerObservation(str(tmp_path), out=out, clock=fake_time, sleep=fake_time.sleep)
    observation.write_frame({"timestamp": 3, "x": float("nan"), "items": (1, 2)})
    line = out.getvalue()
    assert line.startswith(FRAME_LINE_PREFIX) and line.endswith("\n") and line.count("\n") == 1
    assert parse_frame_line(line.rstrip("\n")) == {"timestamp": 3, "x": None, "items": [1, 2]}
    assert json.loads(line[len(FRAME_LINE_PREFIX) :])["timestamp"] == 3
