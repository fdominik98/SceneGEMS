"""Campaign configs, the class catalog, and their validation.

campaign_config.py    the config model (scope, domain, trajectories, execution, resources, policy),
                      YAML loading, the config hash, case seeds
class_catalog.py      the functional scenarios under assets/generated_functional_models/all/ as classes
config_validation.py  a config against the catalog and the vessel stack resolver, with every reason
"""

from scenegems_tool.assurance.campaign.campaign_config import (
    CampaignConfig,
    CampaignConfigError,
    RetentionPolicy,
    RunConfig,
    campaign_config_from_dict,
    case_seed,
    load_campaign_config,
    parse_campaign_config,
)
from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog, ScenarioClass, UnknownClassId
from scenegems_tool.assurance.campaign.config_validation import CampaignConfigRejected, RunStacks, ValidatedCampaign, validate_campaign_config

__all__ = [
    "CampaignConfig",
    "CampaignConfigError",
    "CampaignConfigRejected",
    "ClassCatalog",
    "RetentionPolicy",
    "RunConfig",
    "RunStacks",
    "ScenarioClass",
    "UnknownClassId",
    "ValidatedCampaign",
    "campaign_config_from_dict",
    "case_seed",
    "load_campaign_config",
    "parse_campaign_config",
    "validate_campaign_config",
]
