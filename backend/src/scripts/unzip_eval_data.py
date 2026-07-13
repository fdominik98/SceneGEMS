import os
import tkfilebrowser
from concrete_level.data_parser import EvalDataParser
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from typing import List

from utils.file_system_utils import GEN_DATA_FOLDER


def main() -> None:
    dp = EvalDataParser()
    eval_datas = dp.load_pkl_gzip_compressed_eval_data()

    # Select a folder from the file browser
    folder = tkfilebrowser.askopendirnames(initialdir=GEN_DATA_FOLDER)[0]

    for eval_data in eval_datas:
        asset_folder = f"{folder}/{eval_data.measurement_name}/{eval_data.config_group.upper()}/{eval_data.algorithm_desc}_{eval_data.aggregate_strat}/{eval_data.random_seed}"
        print(f"Saving {eval_data.path}")
        if not os.path.exists(asset_folder):
            os.makedirs(asset_folder)
        eval_data.path = f"{asset_folder}/{eval_data.scenario_name}_{eval_data.timestamp.replace(':','-')}.json"
        eval_data.save_to_json()


if __name__ == "__main__":
    main()
