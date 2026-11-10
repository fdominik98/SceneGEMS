"""Specs of the on_board ASV system: the vessel's own software, which SceneGEMS does not run.

A layer that brings the vessel's own ASV system declares LayerSpec.on_board_asv_system,
and only such a layer may be the target of an adapter from on_board (the registry checks it).
Today that is the real vessel's control layer, whose autonomy may run on the vessel itself;
a simulator with its own controllers and physics, such as the COLAV simulator, would declare
it too. The adapters from on_board belong to the layer that hosts the software.
"""

from scenegems_tool.vessel_stack.contracts.adapter_spec import LayerSpec
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, LayerRef

ON_BOARD_LAYER = LayerSpec(
    layer=LayerRef.of(AsvSystemId.ON_BOARD),
    description="The vessel's own ASV system, running on the vessel or inside the integration below it. SceneGEMS runs none and only observes the vessel.",
)
