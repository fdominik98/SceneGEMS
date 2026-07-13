from typing import List

import numpy as np
from scipy.stats import chi2_contingency, entropy


class ChiSquareKLDiv:
    def __init__(self, freq1: List[int], freq2: List[int]) -> None:
        list1len = sum(freq1)
        list2len = sum(freq2)
        freq1 = np.array(freq1) / list1len + 1e-10
        freq2 = np.array(freq2) / list2len + 1e-10

        # Expected frequencies: average of A and B
        expected = (freq1 + freq2) / 2

        # Compute Chi-square statistic
        # self.chi2_stat = np.sum((freq1 - expected) ** 2 / expected)
        self.p_value = chi2_contingency([freq1 * list1len, freq2 * list2len]).pvalue

        # Avoid zero probabilities by adding a small value
        freq1 += 1e-10
        freq2 += 1e-10

        # Normalize
        freq1 /= freq1.sum()
        freq2 /= freq2.sum()

        # Compute KL divergence
        self.kl_div = entropy(freq1, freq2)  # KL(A || B)
