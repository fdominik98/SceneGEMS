"""The stack options the workbench offers: every triple of the resolver's matrix, and whether the workbench can run it.

The browser asks with query_stack_options and builds its simulator, ASV system and control
layer choices from the answer, disabling every combination the resolver rules out and showing
its reason. A combination counts per vessel; the instance's environment and speedup are checked
when its vessel models are generated (SocketSession._accept_simulation_config).

simulatorTypes are the simulators an instance runs on. A real agent's choices are the rows whose
simulatorType is "Real vessel" (control layer real_vessel); they are workbench only.
"""

import math
from typing import Any, Dict, List, Optional

from scenegems_tool.gateway.protocol import StackOptionsMessage
from scenegems_tool.gateway.workbench_stack_mapping import INSTANCE_SIMULATION_LAYERS, simulator_type_label
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import ChainResolution, StackResolver


def _combination(chain: ChainResolution) -> Dict[str, Any]:
    capabilities = chain.capabilities
    max_speedup: Optional[float] = capabilities.max_speedup if capabilities is not None else None
    return {
        "simulatorType": simulator_type_label(chain.stack.simulation_layer),
        "asvSystem": chain.stack.asv_system.value,
        "controlLayer": chain.stack.control_layer.value,
        "available": chain.available,
        "status": chain.status,
        "reason": chain.reason,
        "interactiveOnly": bool(capabilities and capabilities.interactive_only),
        "repeatabilityTier": capabilities.repeatability_tier.value if capabilities is not None else None,
        # JSON has no infinity: no limit of its own is sent as null, like an unmeasured one, with the flag telling them apart.
        "maxSpeedup": None if max_speedup is None or math.isinf(max_speedup) else max_speedup,
        "speedupUnlimited": max_speedup is not None and math.isinf(max_speedup),
        "wind": capabilities.wind.value if capabilities is not None else None,
        "waves": capabilities.waves.value if capabilities is not None else None,
    }


def stack_options_message(resolver: Optional[StackResolver] = None) -> StackOptionsMessage:
    resolver = resolver or default_resolver()
    combinations: List[Dict[str, Any]] = [_combination(chain) for chain in resolver.availability_matrix()]
    return StackOptionsMessage(
        type="stack_options",
        simulatorTypes=[simulator_type_label(layer) for layer in INSTANCE_SIMULATION_LAYERS],
        asvSystem=[software.value for software in AsvSystemId],
        controlLayers=[layer.value for layer in ControlLayerId],
        combinations=combinations,
    )
