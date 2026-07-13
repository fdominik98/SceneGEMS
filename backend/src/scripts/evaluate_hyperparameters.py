from collections import Counter

from concrete_level.data_parser import EvalDataParser
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData


def get_config_key(obj: EvaluationData) -> tuple:
    return (
        obj.population_size,
        obj.mutate_eta,
        obj.mutate_prob,
        obj.crossover_eta,
        obj.crossover_prob,
    )


def main() -> None:
    dp = EvalDataParser()
    eval_datas = dp.load_dirs_merged_as_models()

    # Step 2: Count all configurations
    config_counter = Counter(get_config_key(obj) for obj in eval_datas if obj.is_valid)

    # Step 3: Find the most common config
    for most_common_config, count in config_counter.most_common():
        # Step 4: Get all objects with this config
        grouped_objects = [
            obj
            for obj in eval_datas
            if get_config_key(obj) == most_common_config and obj.is_valid
        ]

        # Print results
        total_eval_time = sum(obj.evaluation_time for obj in grouped_objects)
        print(
            f"Total eval time: {total_eval_time}. Configuration appears {count} times. {most_common_config}"
        )


if __name__ == "__main__":
    main()
