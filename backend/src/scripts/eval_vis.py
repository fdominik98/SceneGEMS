from concrete_level.data_parser import EvalDataParser
from visualization.evaluation_plots.eval_plot_manager import EvalPlotManager


def main() -> None:
    dp = EvalDataParser()
    eval_datas = dp.load_pkl_gzip_compressed_eval_data()
    # eval_datas = dp.load_dirs_merged_as_models()

    EvalPlotManager(eval_datas)


if __name__ == "__main__":
    main()
