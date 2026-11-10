"""What the engine knows of one campaign while it works on it: its record, its config, its stage graph and payload builder, the input per class."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Union

from sqlalchemy.orm import Session

from scenegems_tool.assurance.campaign.campaign_config import CampaignConfig, CampaignStep, FunctionalScenarioInput, InputItem, campaign_config_from_dict
from scenegems_tool.assurance.campaign.campaign_inputs import input_of_class, input_source_of, is_explored_class
from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog
from scenegems_tool.assurance.pipeline.payload_builder import PayloadBuilder, environment_of, required_fingerprints, stack_key
from scenegems_tool.assurance.pipeline.stage_graph import StageGraph
from scenegems_tool.cluster.protocol.artifacts import TEXT_MEDIA_TYPE, ArtifactKind
from scenegems_tool.persistence.stores import EXPLORATION_CLASS_ID, AssuranceStores, CampaignRecord, CaseRecord


@dataclass
class CampaignContext:
    campaign: CampaignRecord
    config: CampaignConfig
    graph: StageGraph
    builder: PayloadBuilder
    content_hashes: Dict[str, str] = field(default_factory=dict)  # class id to the content hash the campaign pinned
    explored: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # explored class id to the reference of its functional scenario artifact
    exploration_case_id: Optional[int] = None  # the exploration case, once it exists: where the explored FECs came from

    @property
    def campaign_id(self) -> str:
        return self.campaign.campaign_id

    @property
    def pinned(self) -> Dict[str, str]:
        return self.campaign.pinned_fingerprints

    def scenario_name(self, case: CaseRecord) -> str:
        """The case as a calibration reference and post-hoc scenario id: <class id>#<case index>."""
        return f"{case.class_id}#{case.case_index}"

    def input_of(self, class_id: str) -> Optional[Union[FunctionalScenarioInput, InputItem]]:
        """The functional scenario or item a class stands for; None for a catalog class."""
        return input_of_class(self.config, class_id)

    def case_input(self, class_id: str) -> Tuple[Optional[str], Optional[Dict]]:
        """What a new case of the class records as its input: (input_artifact, input_source); (None, None) for a catalog class and for the exploration case."""
        if is_explored_class(class_id):
            source = None
            if self.exploration_case_id is not None:
                source = {"campaign_id": self.campaign_id, "case_id": self.exploration_case_id, "step": CampaignStep.DESIGN_SPACE_EXPLORATION.value}
            return self.content_hashes.get(class_id), source
        found = self.input_of(class_id)
        if found is None:
            return None, None
        return found.ref.sha256, input_source_of(found) if isinstance(found, InputItem) else None

    def stack(self, run_index: int) -> Dict:
        return stack_key(self.config, run_index)

    def environment(self, run_index: int) -> Dict:
        return environment_of(self.config, run_index)

    def run_fingerprints(self, run_index: int) -> Dict[str, str]:
        """The pinned fingerprints of the images of a run's components (scenario execution, and SITL and Gazebo on the ArduPilot layers): what calibration results are keyed by."""
        return required_fingerprints(self.graph.run_components(run_index), self.pinned)


class CampaignContexts:
    """Contexts per campaign and config version, with the parsed config kept across ticks."""

    def __init__(self, stores: AssuranceStores, catalog: Optional[ClassCatalog] = None):
        self._stores = stores
        self._catalog = catalog
        self._configs: Dict[Tuple[str, int], Tuple[CampaignConfig, StageGraph, PayloadBuilder]] = {}
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._explored: Dict[str, Tuple[Dict[str, Dict[str, Any]], Optional[int]]] = {}
        self._campaigns: Dict[str, CampaignRecord] = {}

    def refresh(self, campaigns) -> None:
        """The campaigns the engine works on in this step, as just read."""
        self._campaigns = {campaign.campaign_id: campaign for campaign in campaigns}

    def update(self, campaign: CampaignRecord) -> None:
        if campaign.campaign_id in self._campaigns:
            self._campaigns[campaign.campaign_id] = campaign

    def forget_classes(self, campaign_id: str) -> None:
        """The campaign's classes changed (an exploration added its FECs): they are read again for the next context."""
        self._hashes.pop(campaign_id, None)
        self._explored.pop(campaign_id, None)

    def campaign_ids(self):
        return list(self._campaigns)

    def get(self, campaign_id: str, session: Session, version: Optional[int] = None) -> Optional[CampaignContext]:
        """The context of an unfinished campaign, at the given config version (its current one by default)."""
        campaign = self._campaigns.get(campaign_id)
        if campaign is None:
            return None
        version = campaign.config_version if version is None else version
        cached = self._configs.get((campaign_id, version))
        if cached is None:
            record = self._stores.campaigns.config_version(campaign_id, version, session=session)
            config = campaign_config_from_dict(record.config)
            cached = (config, StageGraph(config), PayloadBuilder(config, self._catalog))
            self._configs[(campaign_id, version)] = cached
        hashes = self._hashes.get(campaign_id)
        if hashes is None:
            hashes = {record.class_id: record.content_hash for record in self._stores.cases.list_classes(campaign_id, session=session)}
            self._hashes[campaign_id] = hashes
        config, graph, builder = cached
        explored, exploration_case_id = self._explored_of(campaign_id, graph, hashes, session)
        return CampaignContext(campaign=campaign, config=config, graph=graph, builder=builder, content_hashes=hashes, explored=explored, exploration_case_id=exploration_case_id)

    def _explored_of(self, campaign_id: str, graph: StageGraph, hashes: Dict[str, str], session: Session) -> Tuple[Dict[str, Dict[str, Any]], Optional[int]]:
        """The references of the explored FECs' artifacts and the exploration case of a campaign that explores; kept once the FECs exist."""
        if not graph.explores:
            return {}, None
        cached = self._explored.get(campaign_id)
        if cached is not None:
            return cached
        case = self._stores.cases.find_case(campaign_id, EXPLORATION_CLASS_ID, 0, session=session)
        references: Dict[str, Dict[str, Any]] = {}
        for class_id, content_hash in hashes.items():
            if not is_explored_class(class_id):
                continue
            record = self._stores.artifacts.get(content_hash, session=session)
            if record is not None:
                references[class_id] = {"sha256": content_hash, "size_bytes": record.size_bytes, "kind": ArtifactKind.FUNCTIONAL_SCENARIO.value, "media_type": record.media_type or TEXT_MEDIA_TYPE}
        found = (references, None if case is None else case.case_id)
        if references:
            self._explored[campaign_id] = found  # complete from here on: an exploration adds its FECs once
        return found
