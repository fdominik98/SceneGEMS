"""What the engine knows of one campaign while it works on it: its record, its config, its stage graph and payload builder, the input per class."""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Union

from sqlalchemy.orm import Session

from scenegems_tool.assurance.campaign.campaign_config import CampaignConfig, FunctionalScenarioInput, InputItem, campaign_config_from_dict
from scenegems_tool.assurance.campaign.campaign_inputs import input_of_class, input_source_of
from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog
from scenegems_tool.assurance.pipeline.payload_builder import PayloadBuilder, environment_of, required_fingerprints, stack_key
from scenegems_tool.assurance.pipeline.stage_graph import StageGraph
from scenegems_tool.persistence.stores import AssuranceStores, CampaignRecord, CaseRecord


@dataclass
class CampaignContext:
    campaign: CampaignRecord
    config: CampaignConfig
    graph: StageGraph
    builder: PayloadBuilder
    content_hashes: Dict[str, str] = field(default_factory=dict)  # class id to the content hash the campaign pinned

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
        """What a new case of the class records as its input: (input_artifact, input_source); (None, None) for a catalog class."""
        found = self.input_of(class_id)
        if found is None:
            return None, None
        return found.ref.sha256, input_source_of(found) if isinstance(found, InputItem) else None

    def stack(self, run_index: int) -> Dict:
        return stack_key(self.config, run_index)

    def environment(self, run_index: int) -> Dict:
        return environment_of(self.config, run_index)

    def run_fingerprints(self, run_index: int) -> Dict[str, str]:
        """The pinned fingerprints of the images a run's simulation job uses (kinematic, or SITL and Gazebo on the ArduPilot layers): what calibration results are keyed by."""
        return required_fingerprints(self.graph.run_job_type(run_index), self.pinned)


class CampaignContexts:
    """Contexts per campaign and config version, with the parsed config kept across ticks."""

    def __init__(self, stores: AssuranceStores, catalog: Optional[ClassCatalog] = None):
        self._stores = stores
        self._catalog = catalog
        self._configs: Dict[Tuple[str, int], Tuple[CampaignConfig, StageGraph, PayloadBuilder]] = {}
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._campaigns: Dict[str, CampaignRecord] = {}

    def refresh(self, campaigns) -> None:
        """The campaigns the engine works on in this step, as just read."""
        self._campaigns = {campaign.campaign_id: campaign for campaign in campaigns}

    def update(self, campaign: CampaignRecord) -> None:
        if campaign.campaign_id in self._campaigns:
            self._campaigns[campaign.campaign_id] = campaign

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
        return CampaignContext(campaign=campaign, config=config, graph=graph, builder=builder, content_hashes=hashes)
