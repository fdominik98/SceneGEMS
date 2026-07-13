from typing import List

import numpy as np
from scipy.stats import chisquare, entropy, ks_2samp, permutation_test


class PermutationEvennessTest:
    def __init__(self, dist1: List[int], dist2: List[int], num_permutations=10000):
        """Perform a permutation test on Shannon Evenness Index"""
        self.evenness_1 = self.shannon_evenness(dist1)
        self.evenness_2 = self.shannon_evenness(dist2)
        self.observed_diff = self.evenness_1 - self.evenness_2

        def statistic(x, y):
            return self.shannon_evenness(x) - self.shannon_evenness(y)

        self.p_value = permutation_test(
            (dist1, dist2),
            statistic,
            n_resamples=num_permutations,
            alternative="two-sided",
        ).pvalue

    def shannon_evenness(self, dist):
        """Compute Shannon Evenness Index: J' = H' / log(N)"""
        dist = np.array(dist, dtype=np.float64)
        dist = dist / np.sum(dist)  # Normalize to probability distribution
        H = entropy(dist, base=np.e)  # Shannon entropy
        N = len(dist)  # Number of categories
        return H / np.log(N) if N > 1 else 0
