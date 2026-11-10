"""Plain JSON values from what in-container runs return: numpy values, tuples, enums and non-finite floats."""

import math
from enum import Enum
from typing import Any

import numpy as np


def json_safe(value: Any) -> Any:
    """Plain JSON values: numpy values become numbers and lists, tuples lists, enums their values, non-finite floats None."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
