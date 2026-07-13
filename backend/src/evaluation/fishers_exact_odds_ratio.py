from itertools import combinations
from typing import Dict, List, Tuple

from scipy.stats import fisher_exact


class FisherExactOddsRatio:
    def __init__(self, samples: Dict[str, List[int]] = {}) -> None:
        self.samples = samples

        pairs = list(combinations(samples.items(), 2))

        self.odds_ratios: Dict[Tuple[str, str], float] = {}
        self.p_values: Dict[Tuple[str, str], float] = {}

        for algo1, algo2 in pairs:
            contingency_table_pair = [
                [
                    sum(algo1[1]),
                    len(algo1[1]) - sum(algo1[1]),
                ],  # [Success, Failure] for Algorithm 1
                [
                    sum(algo2[1]),
                    len(algo2[1]) - sum(algo2[1]),
                ],  # [Success, Failure] for Algorithm 2
            ]
            odds_ratio, p_value = fisher_exact(contingency_table_pair)
            self.odds_ratios[(algo1[0], algo2[0])] = odds_ratio
            self.p_values[(algo1[0], algo2[0])] = p_value
