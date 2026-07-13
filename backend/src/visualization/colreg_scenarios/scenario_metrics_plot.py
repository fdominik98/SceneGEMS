from typing import List

import matplotlib.pyplot as plt
from matplotlib import gridspec

from concrete_level.models.trajectories import Trajectories
from evaluation.risk_evaluation import TrajectoryRiskEvaluator
from visualization.colreg_scenarios.plot_components.metric_components.proximity_metrics_component import (
    DCPAAxesComponent,
    DistanceAxesComponent,
    TCPAAxesComponent,
)
from visualization.colreg_scenarios.plot_components.metric_components.risk_metric_component import RiskMetricComponent
from visualization.plotting_utils import PlotBase


class ScenarioMetricsPlot(PlotBase):
    def __init__(self, trajectories: Trajectories):
        PlotBase.__init__(self)

        self.trajectories = trajectories

        self.risk_evaluator = TrajectoryRiskEvaluator(self.trajectories)
        self.ref_risk_evaluator = TrajectoryRiskEvaluator(self.trajectories)

        DistanceAxesComponent(
            self.axes[0],
            self.trajectories.initial_scene,
            self.risk_evaluator.risk_vectors,
            self.ref_risk_evaluator.risk_vectors,
        ).draw()
        DCPAAxesComponent(
            self.axes[1],
            self.trajectories.initial_scene,
            self.risk_evaluator.risk_vectors,
            self.ref_risk_evaluator.risk_vectors,
        ).draw()
        TCPAAxesComponent(
            self.axes[2],
            self.trajectories.initial_scene,
            self.risk_evaluator.risk_vectors,
            self.ref_risk_evaluator.risk_vectors,
        ).draw()
        # RiskMetricComponent(self.axes[3], self.trajectories, self.risk_evaluator.proximity_metrics, 'Proximity index', True, self.ref_risk_evaluator.proximity_metrics).draw()
        RiskMetricComponent(
            self.axes[3],
            self.trajectories.initial_scene,
            self.risk_evaluator.risk_vectors,
            "DS-based index",
            True,
            self.ref_risk_evaluator.risk_vectors,
        ).draw()

        self.fig.tight_layout()

    def create_fig(self) -> plt.Figure:
        fig: plt.Figure = plt.figure(figsize=(12, 3))
        # Create a GridSpec with 2 rows and 2 columns
        gs = gridspec.GridSpec(2, 3, height_ratios=[1, 1], width_ratios=[1, 1, 1])

        ax4 = fig.add_subplot(gs[0, 2])
        # Create axes for the first column (occupying both rows)
        ax1 = fig.add_subplot(gs[1, 0])
        ax2 = fig.add_subplot(gs[1, 1])
        ax3 = fig.add_subplot(gs[1, 2])

        # ax5 = self.fig.add_subplot(gs[1, 3])

        fig.subplots_adjust(wspace=0.5)

        self.axes: List[plt.Axes] = [ax1, ax2, ax3, ax4]
        return fig
