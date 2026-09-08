import json
import os
import pprint
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from concrete_level.models.trajectories import Trajectories
from utils.file_system_utils import GEN_DATA_FOLDER
from utils.serializable import Serializable

# The trajectory generation result is a serialized TrajectoryData plus the monitor output
# recorded for each of its scenes. "monitor_frames" is index-aligned with
# trajectories.scene_list and is not a TrajectoryData field, so producer
# (trajectory_generation_worker._trajectory_payload) and consumer both go through these
# names rather than repeating the literal.
MONITOR_FRAMES_KEY = "monitor_frames"
TRAJECTORY_PAYLOAD_EXTRA_KEYS = frozenset({MONITOR_FRAMES_KEY})


@dataclass(frozen=False)
class TrajectoryData(Serializable):
    algorithm_desc: Optional[str] = None
    scene_path: Optional[str] = None
    config_name: Optional[str] = None
    random_seed: Optional[int] = None
    max_iter: Optional[int] = None
    goal_sample_rate: Optional[float] = None
    timestamp: Optional[str] = None
    measurement_name: Optional[str] = None
    path: Optional[str] = None
    iter_numbers: Optional[Dict[int, int]] = None
    error_message: Optional[str] = None
    rrt_evaluation_times: Optional[Dict[int, float]] = None
    overall_eval_time: Optional[float] = None
    trajectories: Optional[Trajectories] = None

    def save_to_json(self, path2=None):
        if self.path is None:
            if path2 is None:
                raise Exception("No path provided")
            with open(path2, "w") as file:
                json.dump(self.to_dict(), file, indent=4)
        else:
            with open(self.path, "w") as file:
                json.dump(self.to_dict(), file, indent=4)

    @classmethod
    def load_dict_from_json(cls, file_path: str) -> dict:
        with open(file_path, "r") as file:
            return json.load(file)

    @classmethod
    def load_from_json(cls, file_path: str) -> "TrajectoryData":
        return cls.from_dict(TrajectoryData.load_dict_from_json(file_path))

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> "TrajectoryData":
        """
        Deserialize a trajectory generation payload, dropping the envelope keys that ride
        alongside the TrajectoryData fields but are not part of them.

        Use this instead of from_dict for anything that came out of
        _trajectory_payload, including a planned_trajectory.json the frontend exported or
        handed straight back through load_scenario_file. from_dict stays strict so genuine
        schema drift still fails loudly.
        """
        return cls.from_dict({key: value for key, value in data.items() if key not in TRAJECTORY_PAYLOAD_EXTRA_KEYS})

    def __str__(self) -> str:
        return pprint.pformat(dict(sorted(self.to_dict().items())))

    def __repr__(self) -> str:
        return pprint.pformat(dict(sorted(self.to_dict().items())))

    def save_as_measurement(self):
        measurement_id = f"{self.measurement_name} - {datetime.now().isoformat().replace(':','-')}"
        asset_folder = f"{GEN_DATA_FOLDER}/{self.algorithm_desc}/{self.config_name}/{measurement_id}"
        if not os.path.exists(asset_folder):
            os.makedirs(asset_folder)
        file_path = f"{asset_folder}/{self.timestamp.replace(':','-')}.json"
        self.path = file_path
        self.save_to_json()
