from typing import List
from concrete_level.data_parser import EvalDataParser
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.file_folder_opener import get_default_file_opener
from utils.file_system_utils import GEN_DATA_FOLDER


def main() -> None:
    dp = EvalDataParser()
    # Ask for file name:
    file = get_default_file_opener().ask_save_file(
        initialdir=GEN_DATA_FOLDER, filetypes=[("gz files", "*.gz")]
    )
    if file is None:
        print("No file selected")
        exit()
    eval_datas: List[EvaluationData] = dp.load_eval_data_complex()

    for eval_data in eval_datas:
        eval_data.path = None

    dp.dump_eval_datas_to_gz(eval_datas, file)


if __name__ == "__main__":
    main()
