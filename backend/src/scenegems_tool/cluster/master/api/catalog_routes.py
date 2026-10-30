"""The operator's catalog routes: what a campaign may run (P5.1).

They are read-only and need no database, so the master mounts them whether or not it has the
campaign stores. Like the other operator routes they have no authentication yet.

    GET CATALOG_PATH/fecs?folder=&pattern=&limit=&offset=   the catalog's FECs (functional equivalence classes) in catalog order:
                                           fec_id, folder, vessel and obstacle counts, content hash. folder is a catalog folder, pattern a
                                           scope pattern (a folder pattern without a slash, an FEC id pattern with one); both narrow the
                                           list. The number of matching FECs is in X-Total-Count. 503 when the master has no catalog folder
    GET CATALOG_PATH/fecs/<fec id>         the FEC's functional scenario (.problem text, LF line endings, text/plain): the preset the
                                           workbench's scene generation loads into its editor. 404 for an unknown FEC, 503 without a catalog
    GET CATALOG_PATH/domain-presets        the domain presets of backend/assets/domain_config/: {"colregs_constants": [...],
                                           "vessel_types": [...], "obstacle_types": [...]}, each preset {"name", "default", "content"}
    GET CATALOG_PATH/stacks                the stack options a campaign config accepts with their repeatability tier and parameters,
                                           the monitors, the trajectory generators with their parameter keys and defaults, the run
                                           fields, and the resolver's other stacks with the reasons a campaign cannot use them
                                           (catalog_views.py describes the shape)
    GET CATALOG_PATH/architecture          the architecture documents of the Capabilities page: the vessel stack and the trajectory
                                           generation, scene generation and monitoring subsystems, each with its metamodel and its
                                           concrete implementations (architecture/architecture_model.py describes the shape). Served
                                           from the files written at startup, or built on request when they are missing
"""

from typing import Optional

import anyio
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import PlainTextResponse

from scenegems_tool.architecture.architecture_files import architecture_view
from scenegems_tool.cluster.master.api.catalog_views import class_view, domain_presets_view, stacks_view
from scenegems_tool.cluster.protocol.routes import CATALOG_PATH

MAX_LISTED = 1000


def catalog_router() -> APIRouter:
    router = APIRouter()
    router.include_router(_class_routes())

    @router.get(CATALOG_PATH + "/domain-presets")
    async def list_domain_presets() -> dict:
        return await anyio.to_thread.run_sync(domain_presets_view)

    @router.get(CATALOG_PATH + "/stacks")
    async def list_stacks() -> dict:
        return await anyio.to_thread.run_sync(stacks_view)

    @router.get(CATALOG_PATH + "/architecture")
    async def get_architecture() -> dict:
        return await anyio.to_thread.run_sync(architecture_view)

    return router


def classes(folder: Optional[str], pattern: Optional[str]) -> list:
    # Imported here: the catalog module is part of the campaign package, whose config model the master keeps out of its startup
    from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog

    catalog = ClassCatalog.default()
    found = catalog.classes() if not pattern else catalog.expand(pattern)
    return [scenario_class for scenario_class in found if folder is None or scenario_class.folder == folder]


def class_content(class_id: str) -> str:
    from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog, UnknownClassId

    try:
        return ClassCatalog.default().get(class_id).read_content()
    except UnknownClassId:
        raise HTTPException(status_code=404, detail=f"no FEC {class_id} in the catalog")


def _class_routes() -> APIRouter:
    router = APIRouter()

    @router.get(CATALOG_PATH + "/fecs")
    async def list_fecs(response: Response, folder: Optional[str] = None, pattern: Optional[str] = None, limit: int = 100, offset: int = 0) -> list:
        try:
            found = await anyio.to_thread.run_sync(classes, folder, pattern)
        except FileNotFoundError as error:
            raise HTTPException(status_code=503, detail=str(error))
        response.headers["X-Total-Count"] = str(len(found))
        start = max(0, offset)
        return [class_view(scenario_class) for scenario_class in found[start : start + max(1, min(limit, MAX_LISTED))]]

    @router.get(CATALOG_PATH + "/fecs/{fec_id:path}", response_class=PlainTextResponse)
    async def get_fec_content(fec_id: str) -> PlainTextResponse:
        try:
            content = await anyio.to_thread.run_sync(class_content, fec_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=503, detail=str(error))
        return PlainTextResponse(content, media_type="text/plain; charset=utf-8")

    return router
