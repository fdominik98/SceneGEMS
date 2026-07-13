import os
from typing import List, Set, Tuple
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from visualization.plotting_utils import EvalPlot
from utils.evaluation_config import DC_SB_II, DC_SB_III, DC_RS, MSR_SB_III, MSR_CDRS, MSR_CDRS_PS, DC_RS_PS
from utils.file_system_utils import GEN_DATA_FOLDER

import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

class RareScenarioPlot(EvalPlot):
    def __init__(self, eval_datas : List[EvaluationData]):
        self.base_approach = MSR_CDRS_PS
        self.approaches_to_exclude = [MSR_CDRS_PS]
        self.threshold = 1
        super().__init__(eval_datas)

    @property
    def config_groups(self) -> List[str]:
        return [DC_SB_II, DC_SB_III, DC_RS, DC_RS_PS, MSR_CDRS_PS]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        #return [(2, 0), (2, 1), (3, 0), (3, 1), (4, 0), (5, 0), (6, 0)]
        return [(6, 0)]

    def _hashes_covered_in_at_least_half_seeds(
        self, actor_numbers_by_type: Tuple[int, int], comparison_group: str
    ) -> Set[int]:
        """Set of second_level_hashes that appear in at least half of the seeds for this (vessel, comparison_group)."""
        seed_to_data = self.measurements[actor_numbers_by_type].get(comparison_group, {})
        if not seed_to_data:
            return set()
        hash_seed_count = {}
        for seed, data_list in seed_to_data.items():
            hashes_in_seed = set()
            for eval_data in data_list:
                if eval_data.best_scene is not None and eval_data.best_scene.second_level_hash is not None:
                    hashes_in_seed.add(eval_data.best_scene.second_level_hash)
            for h in hashes_in_seed:
                hash_seed_count[h] = hash_seed_count.get(h, 0) + 1
        return {h for h, c in hash_seed_count.items() if c >= self.threshold}

    def _base_hashes_sorted_by_half_covered_time(
        self, actor_numbers_by_type: Tuple[int, int]
    ) -> List[int]:
        """Base-approach hashes that appear in at least half of the seeds, sorted by when each hash reached half coverage (threshold-th earliest last-seen timestamp among seeds)."""
        base_data = self.measurements[actor_numbers_by_type].get(self.base_approach, {})
        if not base_data:
            return []
        # Per seed: last timestamp at which each hash appears (data_list is in chronological order)
        seed_last_ts_per_hash: List[dict] = []
        for seed, data_list in base_data.items():
            last_ts = {}
            for eval_data in data_list:
                h = (
                    eval_data.best_scene.second_level_hash
                    if eval_data.best_scene is not None
                    else None
                )
                if h is not None and eval_data.timestamp:
                    last_ts[h] = datetime.fromisoformat(eval_data.timestamp)
            seed_last_ts_per_hash.append(last_ts)
            
        hash_last_ts_list = {}  # hash -> list of last-seen timestamps (one per seed that has it)
        for last_ts in seed_last_ts_per_hash:
            for h, ts in last_ts.items():
                if h not in hash_last_ts_list:
                    hash_last_ts_list[h] = []
                hash_last_ts_list[h].append(ts)
        half_covered_hashes = {
            h for h, ts_list in hash_last_ts_list.items()
            if len(ts_list) >= self.threshold
        }
        # For each hash: time when it reached half coverage = threshold-th earliest last-seen (0-indexed: threshold-1)
        hash_to_half_ts = {}
        for h in half_covered_hashes:
            sorted_ts = sorted(hash_last_ts_list[h])
            hash_to_half_ts[h] = sorted_ts[self.threshold - 1]
        return sorted(hash_to_half_ts.keys(), key=lambda h: hash_to_half_ts[h])

    def create_fig(self) -> plt.Figure:
        fig, axes = plt.subplots(self.comparison_group_count, self.vessel_num_count, figsize=(2.5 * 4, 3.8), constrained_layout=True,
                                 gridspec_kw={'wspace': 0, 'hspace': 0})
        axes = np.atleast_2d(axes)

        other_approaches = [g for g in self.comparison_groups if g not in self.approaches_to_exclude]
        num_other = len(other_approaches)

        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            base_hashes_ordered = self._base_hashes_sorted_by_half_covered_time(actor_number_by_type)
            hashes_half_by_approach = {
                cg: self._hashes_covered_in_at_least_half_seeds(actor_number_by_type, cg)
                for cg in other_approaches
            }
            # For each base hash in order: how many other approaches also have it (in at least half of seeds)
            counts_in_order = [
                sum(1 for cg in other_approaches if h in hashes_half_by_approach.get(cg, set()))
                for h in base_hashes_ordered
            ]
            # Base hashes that no other approach covers (in at least half of seeds)
            zero_count_hashes = {
                base_hashes_ordered[i] for i in range(len(counts_in_order)) if counts_in_order[i] == 0
            }
            if zero_count_hashes:
                self._save_rare_scenario_eval_datas(actor_number_by_type, zero_count_hashes)

            print(f'{actor_number_by_type[0]} vessels: base ({self.config_group_map.get(self.base_approach, self.base_approach)}) hashes in at least half of seeds (ordered by half-covered time, last-seen): {len(base_hashes_ordered)} hashes')
            print(f'  Number of other approaches covering each base hash (in order): {counts_in_order}')
            print(f'  (max {num_other} other approaches; zeros: {counts_in_order.count(0)} / {len(counts_in_order)})')
            last_10pct = counts_in_order[-max(1, len(counts_in_order) // 10):]
            print(f'  Last 10%: {last_10pct}')
            print(f'  Last 10% zeros: {last_10pct.count(0)} / {len(last_10pct)}')
        return fig

    def _save_rare_scenario_eval_datas(
        self, actor_numbers_by_type: Tuple[int, int], zero_count_hashes: Set[int]
    ) -> None:
        """Save all EvaluationData from the base approach whose second_level_hash is in zero_count_hashes."""
        base_data = self.measurements[actor_numbers_by_type].get(self.base_approach, {})
        to_save: List[EvaluationData] = []
        to_save_hashes: Set[int] = set()
        for seed, data_list in base_data.items():
            for eval_data in data_list:
                h = (
                    eval_data.best_scene.second_level_hash
                    if eval_data.best_scene is not None
                    else None
                )
                if h is not None and h in zero_count_hashes and h not in to_save_hashes:
                    to_save_hashes.add(h)
                    to_save.append(eval_data)
        if not to_save:
            return
        out_dir = os.path.join(
            GEN_DATA_FOLDER,
            'rare_scenario_eval_data',
            f'{actor_numbers_by_type[0]}v_{actor_numbers_by_type[1]}obs',
        )
        os.makedirs(out_dir, exist_ok=True)
        for i, ed in enumerate(to_save):
            safe_ts = (ed.timestamp or '').replace(':', '-')
            name = f"hash_{ed.best_scene.second_level_hash}_seed_{ed.random_seed}_{safe_ts}_{i}.json"
            path = os.path.join(out_dir, name)
            ed.save_to_json(path2=path)
        print(f'  Saved {len(to_save)} rare-scenario eval datas to {out_dir}')
