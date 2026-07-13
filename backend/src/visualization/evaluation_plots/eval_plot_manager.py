import os
import tkinter as tk
from datetime import datetime
from typing import Dict, List

from matplotlib import pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.file_system_utils import EXPORTED_PLOTS_FOLDER
from visualization.evaluation_plots.coverage_evolution_plot import RelevantCoverageEvolutionPlot
from visualization.evaluation_plots.coverage_plot import RelevantCoveragePlot
from visualization.evaluation_plots.rare_scenario_plot import RareScenarioPlot
from visualization.evaluation_plots.time_to_full_coverage_plot import RelevantTimeToFullCoveragePlot
from visualization.evaluation_plots.time_per_eq_class_plot import TimePerEqvClassForValidPlot, TimePerEqvClassPlot, TimePerScenePlot
from visualization.plotting_utils import DummyEvalPlot, EvalPlot
class PlotWrapper():
    def __init__(self, plot_class, args):
        self.plot_class = plot_class
        self.args = args
        self.plot = None

    def get(self) -> EvalPlot:
        if self.plot is None:
            self.plot = self.plot_class(**self.args)
        return self.plot

class EvalPlotManager():
    def __init__(self, eval_datas : List[EvaluationData]):
        self.eval_datas = eval_datas
        self.plots: Dict[str, PlotWrapper] = {
            ".---------------------------------------.": PlotWrapper(DummyEvalPlot, {"eval_datas": self.eval_datas}),
            # "Scenario Type Statistics" : PlotWrapper(ScenarioTypeStatisticsPlot, {'eval_datas': self.eval_datas}),
            # "First-level Abstraction Diversity -relevant" : PlotWrapper(DiversityPlot, {'eval_datas': self.eval_datas, 'is_second_level_abstraction' : False, 'is_relevant' : True}),
            # "First-level Abstraction Diversity -all" : PlotWrapper(DiversityPlot, {'eval_datas': self.eval_datas, 'is_second_level_abstraction' : False, 'is_relevant' : False}),
            # "Ambiguous Diversity" : PlotWrapper(AmbiguousDiversityPlot, {'eval_datas': self.eval_datas, 'is_second_level_abstraction' : False}),
            # "Coverage Distribution" : PlotWrapper(DiversityPlot, {'eval_datas': self.eval_datas}),
            # "Second-level Abstraction Diversity, -all" : PlotWrapper(DiversityPlot, {'eval_datas': self.eval_datas, 'is_second_level_abstraction' : True, 'is_relevant' : False}),
            # "Higher Abstraction Ambiguous Diversity" : PlotWrapper(AmbiguousDiversityPlot, {'eval_datas': self.eval_datas, 'is_second_level_abstraction' : True}),
            # 'First-level Abstraction Coverage Evolution' : PlotWrapper(CoverageEvolutionPlot, {'eval_datas': self.eval_datas, 'is_second_level_abstraction' : False}),
            'Relevant Coverage Evolution' : PlotWrapper(RelevantCoverageEvolutionPlot, {'eval_datas': self.eval_datas}),
            'Relevant Coverage' : PlotWrapper(RelevantCoveragePlot, {'eval_datas': self.eval_datas}),
            'Time to 100% Coverage' : PlotWrapper(RelevantTimeToFullCoveragePlot, {'eval_datas': self.eval_datas}),
            # 'Ambiguous Coverage Evolution' : PlotWrapper(AmbiguousCoverageEvolutionPlot, {'eval_datas': self.eval_datas}),
            # 'Scene relevance ratio' : PlotWrapper(RelevantRatioPlot, {'eval_datas': self.eval_datas,}),

            "..-------------------------------------.." : PlotWrapper(DummyEvalPlot, {'eval_datas': self.eval_datas}),
            "Time Per Eqv Class" : PlotWrapper(TimePerEqvClassPlot, {'eval_datas': self.eval_datas, 'is_all': True, 'is_algo': False}),
            "Time Per Eqv Class For Valid Scenes" : PlotWrapper(TimePerEqvClassForValidPlot, {'eval_datas': self.eval_datas, 'is_all': True, 'is_algo': False}),
            "Time Per Scene" : PlotWrapper(TimePerScenePlot, {'eval_datas': self.eval_datas, 'is_all': True, 'is_algo': False}),
            # "Success Rate" : PlotWrapper(SuccessRatePlot, {'eval_datas': self.eval_datas, 'is_algo': False}),
            # "Runtime (successful)" : PlotWrapper(RuntimePlot, {'eval_datas': self.eval_datas, 'is_all': False, 'is_algo': False}),
            # "Runtime (all)" : PlotWrapper(RuntimePlot, {'eval_datas': self.eval_datas, 'is_all': True, 'is_algo': False}),
            # "Average Time per Scene" : PlotWrapper(AverageTimePerScenePlot, {'eval_datas': self.eval_datas, 'is_all': True, 'is_algo': False}),
            # "...-----------------------------------..." : PlotWrapper(DummyEvalPlot, {'eval_datas': self.eval_datas}),
            # "Risk Vector Proximity index" : PlotWrapper(RiskVectorPlot, {'eval_datas': self.eval_datas, 'metric' : 'proximity'}),
            # "Risk Vector DS index" : PlotWrapper(RiskVectorPlot, {'eval_datas': self.eval_datas, 'metric' : 'ds'}),
            # "Risk Vector DCPA" : PlotWrapper(RiskVectorPlot, {'eval_datas': self.eval_datas, 'metric' : 'dcpa'}),
            # "Risk Vector TCPA" : PlotWrapper(RiskVectorPlot, {'eval_datas': self.eval_datas, 'metric' : 'tcpa'}),
            "....---------------------------------....": PlotWrapper(DummyEvalPlot, {"eval_datas": self.eval_datas}),
            # "First-level Abstraction Diversity Statistics Test" : PlotWrapper(DiversityStatisticsTable, {'eval_datas': self.eval_datas, 'is_second_level_abstraction' : False}),
            # "Second-level Abstraction Diversity Statistics Test" : PlotWrapper(DiversityStatisticsTable, {'eval_datas': self.eval_datas, 'is_second_level_abstraction' : True}),
            #"Ambiguous Diversity Statistics Test" : PlotWrapper(AmbiguousDiversityStatisticsTable, {'eval_datas': self.eval_datas, 'is_second_level_abstraction' : False}),
            "Rare Scenario Plot" : PlotWrapper(RareScenarioPlot, {'eval_datas': self.eval_datas}),
        }

        self.root = tk.Tk()
        self.root.resizable(True, True)

        self.root.option_add("*Font", ("Times New Roman", 14))

        self.root.title(f"Evaluation - {list(self.plots.keys())[0]}")

        # CANVAS FRAME
        self.canvas_frame = tk.Frame(master=self.root)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        ## PLOT FRAME
        self.plot_frame = tk.Frame(master=self.canvas_frame)
        self.plot_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = FigureCanvasTkAgg(list(self.plots.values())[0].get().fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # TOOLBAR FRAME
        self.toolbar_frame = tk.Frame(master=self.root, height=50)
        self.toolbar_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.toolbar_frame.pack_propagate(False)

        ## TOOLBAR
        self.navigation_frame = tk.Frame(self.toolbar_frame)
        self.navigation_frame.pack(fill=tk.BOTH, side=tk.LEFT)
        self.navigation_toolbar = NavigationToolbar2Tk(self.canvas, self.navigation_frame)
        self.navigation_toolbar.update()
        self.navigation_toolbar.pack(fill=tk.BOTH, side=tk.LEFT)

        ## PLOT SELECTION
        self.plot_options = list(self.plots.keys())
        self.selected_plot = tk.StringVar()
        self.selected_plot.set(self.plot_options[0])  # Set the default value
        # Create the dropdown menu
        self.plot_dropdown = tk.OptionMenu(
            self.toolbar_frame,
            self.selected_plot,
            *self.plot_options,
            command=self.on_select_plot,
        )
        self.plot_dropdown.pack(side=tk.LEFT, padx=5)

        self.to_pdf_button = tk.Button(self.toolbar_frame, text="PDF", command=self.to_pdf)
        self.to_pdf_button.pack(side=tk.LEFT, padx=5)
        self.root.bind('<e>', lambda event: self.to_pdf())

        ## EXIT BUTTONS
        exit_button = tk.Button(self.toolbar_frame, text="Exit", command=self.exit_application)
        exit_button.pack(side=tk.RIGHT, padx=5)
        continue_button = tk.Button(self.toolbar_frame, text="Continue", command=self.continue_application)
        continue_button.pack(side=tk.RIGHT, padx=5)

        self.root.wait_window()


    def sort_dict(self, dicts : List[Dict[str, plt.Artist]]) -> List[List[plt.Artist]]:
        artists = []
        for dict in dicts:
            artists.append([value for key, value in sorted(dict.items())])
        return artists

    def exit_application(self):
        self.root.destroy()
        os._exit(0)

    def continue_application(self):
        self.root.destroy()

    def to_pdf(self):
        file_name = f'{self.selected_plot.get()}_{datetime.now().isoformat().replace(":","-")}'
        self.canvas.figure.savefig(f'{EXPORTED_PLOTS_FOLDER}/{file_name}.svg', format='svg', bbox_inches='tight', dpi=350)
        self.canvas.figure.savefig(f'{EXPORTED_PLOTS_FOLDER}/{file_name}.pdf', format='pdf', bbox_inches='tight', dpi=350)
        print('image saved')


    def on_select_plot(self, value):
        plot = self.plots[value].get()
        self.navigation_toolbar.destroy()
        self.canvas.get_tk_widget().destroy()

        self.canvas = FigureCanvasTkAgg(plot.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.navigation_toolbar = NavigationToolbar2Tk(self.canvas, self.navigation_frame)
        self.navigation_toolbar.update()
        self.navigation_toolbar.pack(fill=tk.BOTH, side=tk.LEFT)

        self.root.title(f"Evaluation - {value}")
