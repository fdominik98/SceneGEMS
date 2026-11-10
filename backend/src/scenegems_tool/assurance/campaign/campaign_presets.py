"""Campaign presets: campaign configs to start the wizard from, for campaign runs that come up again and again.

The presets shipped with the control node are the config files under backend/assets/campaign_presets/
(in the control node image with the other assets). A file's name without .yaml is the preset's id; the
leading number only orders the list. Its name and description are the config's own. Operators save
more presets on the control node (persistence/stores/setting_stores.py); both kinds follow the same rule:

    a preset is a campaign config that loads, and it has no input section. Picked history outputs
    and uploaded files belong to one campaign, so the operator picks them when starting from a preset.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple, Union

import yaml

from scenegems_tool.assurance.campaign.campaign_config import CampaignConfig, CampaignConfigError, campaign_config_from_dict, parse_campaign_config
from scenegems_tool.assurance.campaign.class_catalog import natural_key
from utils.file_system_utils import CAMPAIGN_PRESETS_FOLDER

PRESET_SUFFIX = ".yaml"
NO_INPUT_REASON = "input: a preset has no input section; pick the input when you start a campaign from the preset"


@dataclass(frozen=True)
class BuiltinPreset:
    preset_id: str  # the file name without .yaml
    name: str
    description: str
    config: Dict[str, Any]  # as the file states it, defaults left out


def preset_config(config: Union[str, Mapping[str, Any]]) -> Tuple[Dict[str, Any], CampaignConfig]:
    """A preset's config as given (YAML text or a mapping) and as the model; CampaignConfigError with every reason when it is not a preset."""
    if isinstance(config, str):
        model = parse_campaign_config(config)
        data = yaml.safe_load(config)
    else:
        data = dict(config)
        model = campaign_config_from_dict(data)
    if "input" in data:
        raise CampaignConfigError([NO_INPUT_REASON])
    return data, model


def builtin_presets(folder: Union[str, Path] = CAMPAIGN_PRESETS_FOLDER) -> Tuple[BuiltinPreset, ...]:
    """The presets shipped with the control node, in file name order; none when the folder is missing."""
    root = Path(folder)
    if not root.is_dir():
        return ()
    presets = []
    for path in sorted(root.glob(f"*{PRESET_SUFFIX}"), key=lambda item: natural_key(item.stem)):
        data, model = preset_config(path.read_text(encoding="utf-8"))
        presets.append(BuiltinPreset(path.stem, model.name, model.description, data))
    return tuple(presets)
