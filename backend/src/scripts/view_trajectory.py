from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorStateSet
from concrete_level.data_parser import TrajDataParser
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from visualization.colreg_scenarios.scenario_plot_manager import ScenarioPlotManager

dp = TrajDataParser()
data_models = dp.load_data_models()

if len(data_models) == 0:
    exit(0)

trajectory_data = data_models[0]
if trajectory_data.trajectories is not None:
    # trajectories = (
    #     TrajectoryBuilder(trajectory_data.trajectories.time_step, trajectory_data.trajectories.scene_list)
    #     .convert_to_time_step(ONE_SECOND)
    #     .build()
    # )

    trajectories = trajectory_data.trajectories
    trajectory_manager = TrajectoryManager(trajectories)
    ScenarioPlotManager(trajectory_manager)
