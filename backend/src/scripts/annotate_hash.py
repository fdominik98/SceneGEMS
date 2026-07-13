import os
from multiprocessing import Pool, cpu_count
from tqdm import tqdm

from concrete_level.concrete_scene_abstractor import ConcreteSceneAbstractor
from concrete_level.data_parser import EvalDataParser
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.file_folder_opener import get_default_file_opener
from utils.file_system_utils import GEN_DATA_FOLDER

# Ensure deterministic hashing across processes (equivalent to `export PYTHONHASHSEED=0`)
os.environ.setdefault("PYTHONHASHSEED", "0")

# for eval_data in eval_datas:
#     pass
#     eval_data.save_to_json(path2=eval_data.path)
#     done += 1
#     print(f'Config Group: {eval_data.config_group}. Done {done}, Skipped: {skipped} / {len(eval_datas)}')
# exit(0)#-------------------------------------------------------


def annotate_hash(eval_data: EvaluationData) -> EvaluationData | None:
    # skipped = 0
    # done = 0
    eval_data.path = None
    if not eval_data.is_valid:
        return eval_data
        # skipped += 1
        # print('Not optimal solution, skipped.')
    scenario = ConcreteSceneAbstractor.get_abstractions_from_eval(eval_data)
    # fsm_level_hash = scenario.functional_scenario.fsm_shape_hash()
    fec_level_hash = scenario.functional_scenario.fec_shape_hash()
    is_relevant_by_fec = scenario.functional_scenario.is_relevant_by_fec
    # is_relevant_by_fsm = scenario.functional_scenario.is_relevant_by_fsm
    is_ambiguous_by_fec = scenario.functional_scenario.is_ambiguous_by_fec
    # is_ambiguous_by_fsm = scenario.functional_scenario.is_ambiguous_by_fsm
    eval_data.best_scene = SceneBuilder(eval_data.best_scene).build(
                                                    second_level_hash=fec_level_hash,
                                                    is_relevant_by_fec=is_relevant_by_fec,
                                                    is_ambiguous_by_fec=is_ambiguous_by_fec)
    if not eval_data.best_scene.is_relevant_by_fec:
        print(f"WARNING: Not relevant by FEC: {eval_data.aggregate_strat}, {eval_data.measurement_name}, {eval_data.config_group}, {eval_data.algorithm_desc}, {eval_data.random_seed}")
    # done += 1
    # eval_data.save_to_json()
    # info(eval_data, done, skipped, len(eval_datas))
    return eval_data

def main():
    opener = get_default_file_opener()
    dp = EvalDataParser(opener)
    # Ask for file name:
    file = opener.ask_save_file(initialdir=GEN_DATA_FOLDER, filetypes=[("gz files", "*.gz")])
    if file is None:
        print("No file selected")
        exit()
    eval_datas = dp.load_pkl_gzip_compressed_eval_data()
    
    # random.seed(time.time())
    # random.shuffle(eval_datas)

    # core_count = cpu_count()

    # eval_data_batches = np.array_split(eval_datas, core_count)

    # Use multiple processes for CPU-bound hashing
    with Pool(cpu_count() or 1) as pool:
        processed = list(
            tqdm(
                pool.imap_unordered(annotate_hash, eval_datas),
                total=len(eval_datas),
                desc="Hashing eval datas",
            )
        )

    # Filter out any None results (invalid eval_datas)
    processed_eval_datas = [e for e in processed if e is not None]

    dp.dump_eval_datas_to_gz(processed_eval_datas, file)
            
if __name__ == '__main__':
    main()
