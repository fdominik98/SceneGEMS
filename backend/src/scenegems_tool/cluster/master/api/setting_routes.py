"""The operator's routes for the cluster's settings: its domain configuration and the campaign presets.

The domain configuration is global for the cluster: every workbench run and every campaign that
leaves the COLREGS constants, vessel types or obstacle types out of its config uses it (campaign
create fills them in, so the stored config holds what ran). The master keeps it in its database;
until it is saved once it is the default presets of backend/assets/domain_config/. Campaign presets
are the files the master image ships (campaign_presets.py) and the ones operators saved here.
Without the campaign stores the master serves the defaults and the shipped presets, read-only.

    GET  DOMAIN_PATH                       {"colregs_constants", "vessel_types", "obstacle_types", "saved", "updated_at", "editable"}:
                                           the saved configuration, or the default presets with saved false
    POST DOMAIN_PATH                       {"colregs_constants", "vessel_types", "obstacle_types"} replaces it; 200 with the view, 422
                                           with {"message", "reasons"} for a text that is not a YAML mapping, 503 without the stores
    GET  CAMPAIGN_PRESETS_PATH             the shipped presets in file order, then the saved ones by name: {"preset_id", "name",
                                           "description", "builtin", "steps", "config", "created_at", "updated_at"}
    POST CAMPAIGN_PRESETS_PATH             {"name", "description", "config" (an object or YAML text), "replace"} saves a preset; 201 with
                                           it (200 when it replaced one), 409 when the name is taken (by a shipped preset, or by a saved
                                           one without replace), 422 for a config that does not load or has an input section
    DELETE CAMPAIGN_PRESETS_PATH/<id>      deletes a saved preset: 204, 404, or 409 for a shipped one
"""

from functools import partial
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import anyio
from fastapi import APIRouter, Body, HTTPException, Response

from scenegems_tool.cluster.master.api.campaign_views import config_steps, iso
from scenegems_tool.cluster.protocol.routes import CAMPAIGN_PRESETS_PATH, DOMAIN_PATH
from scenegems_tool.persistence.schema.setting_tables import PRESET_NAME_LENGTH
from scenegems_tool.persistence.stores import AssuranceStores, PresetNameTaken, UnknownPreset

PRESET_FIELDS = {"name", "description", "config", "replace"}


async def _run(function: Callable[..., Any], *arguments: Any) -> Any:
    return await anyio.to_thread.run_sync(partial(function, *arguments))


def _problem(message: str, reasons: List[str]) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": message, "reasons": list(reasons)})


def _without_stores() -> HTTPException:
    return HTTPException(status_code=503, detail="this master runs without the campaign stores, so it keeps no settings")


def domain_view(stores: Optional[AssuranceStores]) -> Dict[str, Any]:
    from scenegems_tool.assurance.campaign.domain_presets import default_domain

    saved = stores.domain.current() if stores is not None else None
    contents = default_domain() if saved is None else saved.contents()
    return {**contents, "saved": saved is not None, "updated_at": None if saved is None else iso(saved.updated_at), "editable": stores is not None}


def checked_domain(body: Any) -> Dict[str, str]:
    """The three texts of a save request, as a campaign config's domain section would hold them; 422 with every reason otherwise."""
    from pydantic import ValidationError

    from scenegems_tool.assurance.campaign.campaign_config import DomainConfig
    from scenegems_tool.assurance.campaign.domain_presets import DOMAIN_KEYS

    if not isinstance(body, dict):
        raise _problem("the domain configuration is not valid", ["the body is an object with colregs_constants, vessel_types and obstacle_types"])
    reasons = [f"{key}: a text is required" for key in DOMAIN_KEYS if not isinstance(body.get(key), str)]
    reasons += [f"unknown fields in the body: {sorted(set(body) - set(DOMAIN_KEYS))}"] if set(body) - set(DOMAIN_KEYS) else []
    if reasons:
        raise _problem("the domain configuration is not valid", reasons)
    try:
        domain = DomainConfig(**{key: body[key] for key in DOMAIN_KEYS})
    except ValidationError as error:
        raise _problem("the domain configuration is not valid", [f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}" for issue in error.errors()])
    return {key: getattr(domain, key) for key in DOMAIN_KEYS}


def preset_view(preset: Any, builtin: bool) -> Dict[str, Any]:
    return {
        "preset_id": preset.preset_id,
        "name": preset.name,
        "description": preset.description,
        "builtin": builtin,
        "steps": config_steps(preset.config),
        "config": preset.config,
        "created_at": None if builtin else iso(preset.created_at),
        "updated_at": None if builtin else iso(preset.updated_at),
    }


def presets_view(stores: Optional[AssuranceStores]) -> List[Dict[str, Any]]:
    from scenegems_tool.assurance.campaign.campaign_presets import builtin_presets

    saved = stores.presets.list_presets() if stores is not None else []
    return [preset_view(preset, True) for preset in builtin_presets()] + [preset_view(preset, False) for preset in saved]


def checked_preset(body: Any) -> Dict[str, Any]:
    """The name, description, config and replace flag of a save request; 422 with the reasons otherwise."""
    from scenegems_tool.assurance.campaign.campaign_config import CampaignConfigError
    from scenegems_tool.assurance.campaign.campaign_presets import preset_config

    if not isinstance(body, dict) or "config" not in body:
        raise _problem("the preset is not valid", ['the body is an object with "name", "config" and optionally "description" and "replace"'])
    reasons = [f"unknown fields in the body: {sorted(set(body) - PRESET_FIELDS)}"] if set(body) - PRESET_FIELDS else []
    name = body.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > PRESET_NAME_LENGTH:
        reasons.append(f'"name" is a text of 1 to {PRESET_NAME_LENGTH} characters')
    description = body.get("description", "")
    if not isinstance(description, str):
        reasons.append('"description" is a text')
    if not isinstance(body.get("replace", False), bool):
        reasons.append('"replace" is true or false')
    if not isinstance(body["config"], (str, dict)):
        reasons.append('"config" is a config object or YAML text')
    if reasons:
        raise _problem("the preset is not valid", reasons)
    try:
        config, _model = preset_config(body["config"])
    except CampaignConfigError as error:
        raise _problem("the preset's campaign config is not valid", list(error.reasons))
    return {"name": name.strip(), "description": description.strip(), "config": config, "replace": body.get("replace", False)}


def _builtin_ids_and_names() -> Mapping[str, str]:
    from scenegems_tool.assurance.campaign.campaign_presets import builtin_presets

    return {preset.preset_id: preset.name for preset in builtin_presets()}


def setting_router(stores: Optional[AssuranceStores] = None) -> APIRouter:
    router = APIRouter()
    router.include_router(_domain_routes(stores))
    router.include_router(_preset_routes(stores))
    return router


def _domain_routes(stores: Optional[AssuranceStores]) -> APIRouter:
    router = APIRouter()

    @router.get(DOMAIN_PATH)
    async def get_domain() -> dict:
        return await _run(domain_view, stores)

    @router.post(DOMAIN_PATH)
    async def save_domain(body: Any = Body(None)) -> dict:
        if stores is None:
            raise _without_stores()
        contents = await _run(checked_domain, body)
        await _run(lambda: stores.domain.save(contents["colregs_constants"], contents["vessel_types"], contents["obstacle_types"]))
        return await _run(domain_view, stores)

    return router


def saved_preset(stores: AssuranceStores, body: Any) -> Tuple[Dict[str, Any], bool]:
    """Saves the preset a request describes; its view and whether it replaced one, or the HTTP error to answer."""
    wanted = checked_preset(body)
    if wanted["name"] in set(_builtin_ids_and_names().values()):
        raise HTTPException(status_code=409, detail=f"a preset shipped with the master is named {wanted['name']!r}; choose another name")
    try:
        saved, replaced = stores.presets.save(wanted["name"], wanted["description"], wanted["config"], replace=wanted["replace"])
    except PresetNameTaken:
        raise HTTPException(status_code=409, detail=f"a saved preset is named {wanted['name']!r}; replace it or choose another name")
    return preset_view(saved, False), replaced


def deleted_preset(stores: Optional[AssuranceStores], preset_id: str) -> None:
    """Deletes a saved preset, or raises the HTTP error to answer."""
    if preset_id in _builtin_ids_and_names():
        raise HTTPException(status_code=409, detail="the presets shipped with the master cannot be deleted")
    if stores is None:
        raise _without_stores()
    try:
        stores.presets.delete(preset_id)
    except UnknownPreset:
        raise HTTPException(status_code=404, detail=f"no preset {preset_id}")


def _preset_routes(stores: Optional[AssuranceStores]) -> APIRouter:
    router = APIRouter()

    @router.get(CAMPAIGN_PRESETS_PATH)
    async def list_presets() -> list:
        return await _run(presets_view, stores)

    @router.post(CAMPAIGN_PRESETS_PATH)
    async def save_preset(response: Response, body: Any = Body(None)) -> dict:
        if stores is None:
            raise _without_stores()
        view, replaced = await _run(saved_preset, stores, body)
        response.status_code = 200 if replaced else 201
        return view

    @router.delete(CAMPAIGN_PRESETS_PATH + "/{preset_id}", status_code=204)
    async def delete_preset(preset_id: str) -> Response:
        await _run(deleted_preset, stores, preset_id)
        return Response(status_code=204)

    return router
