from typing import List

from concrete_level.concrete_scene_abstractor import ConcreteSceneAbstractor
from concrete_level.data_parser import EvalDataParser
from concrete_level.models.multi_level_scenario import MultiLevelScenario
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from evaluation.risk_evaluation import RiskVector
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData

dp = EvalDataParser()
eval_datas: List[EvaluationData] = dp.load_dirs_merged_as_models()
skipped = 0
done = 0

# for eval_data in eval_datas:
#     pass
#     eval_data.save_to_json(path2=eval_data.path)
#     done += 1
#     print(f'Config Group: {eval_data.config_group}. Done {done}, Skipped: {skipped} / {len(eval_datas)}')
# exit(0)#-------------------------------------------------------

START_FROM = 0


def info(data: EvaluationData):
    print(
        f"""Measurement: {data.measurement_name}, Algorithm: {data.algorithm_desc}, Config name: {data.scenario_name}
            Config Group: {data.config_group}. Done {done}, Skipped: {skipped}, ({done + skipped} / {len(eval_datas)}, {(done + skipped) / len(eval_datas) * 100:.1f} %)"""
    )


for i, eval_data in enumerate(eval_datas):
    if i < START_FROM:
        if eval_data.best_scene.has_risk_metrics:
            done += 1
        else:
            skipped += 1
        print("Before start, skipped.")
        info(eval_data)
        continue

    if not eval_data.is_valid:
        skipped += 1
        print("Not optimal solution, skipped.")
    else:
        risk_vector = RiskVector(ConcreteSceneAbstractor.get_abstractions_from_eval(eval_data))
        eval_data.best_scene = SceneBuilder(eval_data.best_scene).build(
            dcpa=risk_vector.min_dcpa,
            tcpa=risk_vector.min_tcpa,
            danger_sector=risk_vector.danger_sector,
            proximity_index=risk_vector.max_proximity_index,
        )
        done += 1
        eval_data.save_to_json()
    info(eval_data)
