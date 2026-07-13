import json
import os
import pprint
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from concrete_level.models.trajectories import Trajectories
from utils.file_system_utils import GEN_DATA_FOLDER
from utils.serializable import Serializable


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
