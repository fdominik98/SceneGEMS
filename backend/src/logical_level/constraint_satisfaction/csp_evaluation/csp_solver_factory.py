from logical_level.constraint_satisfaction.csp_evaluation.csp_solver import CSPSolver
from logical_level.constraint_satisfaction.evolutionary_computation.pygad_ga_algorithm import (
    PyGadGAAlgorithm,
)
from logical_level.constraint_satisfaction.evolutionary_computation.pymoo_nsga2_algorithm import (
    PyMooNSGA2Algorithm,
)
from logical_level.constraint_satisfaction.evolutionary_computation.pymoo_nsga3_algorithm import (
    PyMooNSGA3Algorithm,
)
from logical_level.constraint_satisfaction.evolutionary_computation.pyswarm_pso_algorithm import (
    PySwarmPSOAlgorithm,
)
from logical_level.constraint_satisfaction.evolutionary_computation.scipy_de_algorithm import (
    SciPyDEAlgorithm,
)
from logical_level.constraint_satisfaction.rejection_sampling.rejection_sampling_pipeline import (
    BaseRejectionSampling,
    CDRejectionSampling,
    TwoStepCDRejectionSampling,
    TwoStepRejectionSampling,
)


class CPSSolverFactory:
    @staticmethod
    def factory(algorithm_desc: str, verbose) -> CSPSolver:
        # Map algorithm descriptions to their corresponding classes
        algorithm_map = {
            PyGadGAAlgorithm.algorithm_desc(): PyGadGAAlgorithm,
            PyMooNSGA2Algorithm.algorithm_desc(): PyMooNSGA2Algorithm,
            PyMooNSGA3Algorithm.algorithm_desc(): PyMooNSGA3Algorithm,
            SciPyDEAlgorithm.algorithm_desc(): SciPyDEAlgorithm,
            PySwarmPSOAlgorithm.algorithm_desc(): PySwarmPSOAlgorithm,
            BaseRejectionSampling.algorithm_desc(): BaseRejectionSampling,
            TwoStepRejectionSampling.algorithm_desc(): TwoStepRejectionSampling,
            TwoStepCDRejectionSampling.algorithm_desc(): TwoStepCDRejectionSampling,
            CDRejectionSampling.algorithm_desc(): CDRejectionSampling,
        }

        algo_class = algorithm_map.get(algorithm_desc)
        if algo_class is not None:
            return algo_class(verbose)
        else:
            raise Exception("Unknown algorithm desc")
