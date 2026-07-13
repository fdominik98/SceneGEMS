from concrete_level.data_parser import EvalDataParser
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from concrete_level.trajectory_generation.trajectory_generator import TrajectoryGenerator
from utils.global_constants import ONE_HOUR_IN_SEC, ONE_SECOND
from visualization.colreg_scenarios.scenario_plot_manager import ScenarioPlotManager

dp = EvalDataParser()
data_models = dp.load_data_models()

if len(data_models) == 0:
    exit(0)

eval_data = data_models[0]
trajectories = TrajectoryBuilder.default_trajectory_from_scene(eval_data.best_scene, ONE_SECOND, ONE_HOUR_IN_SEC)
trajectory_manager = TrajectoryManager(trajectories)
ScenarioPlotManager(trajectory_manager)
