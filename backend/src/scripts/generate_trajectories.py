from concrete_level.data_parser import EvalDataParser
from concrete_level.trajectory_generation.trajectory_generator import TrajectoryGenerator
from utils.colregs_approximations import COLREGSConstraints


def main() -> None:
    dp = EvalDataParser()
    data_models = dp.load_data_models()

    if len(data_models) == 0:
        exit(0)

    eval_data = data_models[0]
    # ScenarioPlotManager(trajectory_manager)

    traj_gen = TrajectoryGenerator.generate_trajectories(eval_data, eval_data.best_scene, COLREGSConstraints.default_general_maritime())

    # ScenarioPlotManager(TrajectoryManager(traj_gen.trajectories))


if __name__ == "__main__":
    main()
