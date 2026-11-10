"""The architecture documents of the system, built from the specs in code.

Five documents, in the order of the chain: the design space exploration, the scene generation and the trajectory generation
(read from their *_specs.py modules), the vessel stack that simulates (read from the adapter registry) and the monitoring
that judges the outputs of the steps. A new implementation is declared where it lives, and the next
build shows it; nothing here lists implementations.
"""

from typing import Dict, Mapping, Optional

from scenegems_tool.architecture.architecture_model import ArchitectureDocument
from scenegems_tool.architecture.vessel_stack_description import vessel_stack_document
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_specs import design_space_exploration_document
from scenegems_tool.subsystems.monitoring.monitoring_specs import monitoring_document
from scenegems_tool.subsystems.scene_generation.scene_generation_specs import scene_generation_document
from scenegems_tool.subsystems.subsystem_spec import MeasuredFacts, check_measured_ids, default_measured_facts
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_specs import trajectory_generation_document


def build_architecture_documents(measurements: Optional[Mapping[str, MeasuredFacts]] = None) -> Dict[str, ArchitectureDocument]:
    """The documents by id, in the order the page shows them. measurements are the subsystem measured facts (the file's by default)."""
    measurements = default_measured_facts() if measurements is None else measurements
    exploration = design_space_exploration_document(measurements)
    scenes = scene_generation_document(measurements)
    trajectories = trajectory_generation_document(measurements)
    monitoring = monitoring_document(measurements)
    subsystems = (exploration, scenes, trajectories, monitoring)
    check_measured_ids(measurements, (item.id for document in subsystems for item in (*document.nodes, *document.edges)))
    documents = (exploration, scenes, trajectories, vessel_stack_document(), monitoring)
    return {document.id: document for document in documents}
