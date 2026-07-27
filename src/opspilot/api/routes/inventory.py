"""Inventory routes — Asset CRUD + event log (ADR-0017).

OpsPilot is the system of record for Assets, so unlike every other route
family these endpoints own their data: writes append Asset events, the
row is a projection, the log is the history.

The event actor is always taken from the caller's resolved **Identity**, never
from the request body. An actor a client can choose is not evidence of who
acted, and the physical doer already has a home in the Asset's ``handler``
field, so nothing is lost by making this one system-derived.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ...auth import Identity, require_role
from ...inventory import (
    AssetNotFoundError,
    DuplicateSerialError,
    ProcurementNotFoundError,
    UnknownStatusError,
)
from ..types import (
    ApiAsset,
    ApiAssetCreate,
    ApiAssetDetail,
    ApiAssetListResponse,
    ApiAssetUpdate,
    ApiInventoryEvent,
    ApiInventoryEventListResponse,
    ApiProcurement,
    ApiProcurementCreate,
    ApiProcurementDetail,
    ApiProcurementListResponse,
    ApiProcurementUpdate,
)

router = APIRouter()

_META = {"note"}

# Role gates (ADR-0020): reads need viewer, writes need operator.
_viewer = Depends(require_role("viewer"))
_operator = Depends(require_role("operator"))


@router.post("/inventory", response_model=ApiAsset, status_code=201)
def create_asset(
    body: ApiAssetCreate, request: Request, identity: Identity = _operator
) -> ApiAsset:
    store = request.app.state.inventory
    try:
        row = store.create(body.model_dump(exclude=_META), actor=identity.name, note=body.note)
    except UnknownStatusError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateSerialError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiAsset(**row)


@router.get("/inventory", response_model=ApiAssetListResponse, dependencies=[_viewer])
def list_assets(
    request: Request,
    status: str | None = None,
    assignee: str | None = None,
    q: str | None = None,
    expiring_days: int | None = None,
) -> ApiAssetListResponse:
    store = request.app.state.inventory
    if expiring_days is not None:
        rows = store.expiring_warranties(expiring_days)
    else:
        rows = store.list(status=status, assignee=assignee, q=q)
    return ApiAssetListResponse(assets=[ApiAsset(**r) for r in rows])


# Procurement routes are registered before /inventory/{asset_id} so the
# literal "procurements" segment is never captured as an asset id (#87).


@router.post(
    "/inventory/procurements",
    response_model=ApiProcurement,
    status_code=201,
)
def create_procurement(
    body: ApiProcurementCreate, request: Request, identity: Identity = _operator
) -> ApiProcurement:
    """Group existing Assets; the Procurement adopts their common fields."""
    try:
        row = request.app.state.inventory.create_procurement(body.asset_ids, actor=identity.name)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no asset {exc}") from exc
    return ApiProcurement(**row)


@router.get(
    "/inventory/procurements", response_model=ApiProcurementListResponse, dependencies=[_viewer]
)
def list_procurements(request: Request) -> ApiProcurementListResponse:
    rows = request.app.state.inventory.list_procurements()
    return ApiProcurementListResponse(procurements=[ApiProcurement(**r) for r in rows])


@router.get(
    "/inventory/procurements/{procurement_id}",
    response_model=ApiProcurementDetail,
    dependencies=[_viewer],
)
def get_procurement(procurement_id: str, request: Request) -> ApiProcurementDetail:
    store = request.app.state.inventory
    row = store.get_procurement(procurement_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no procurement {procurement_id}")
    members = [ApiAsset(**m) for m in store.procurement_members(procurement_id)]
    return ApiProcurementDetail(**row, members=members)


@router.patch(
    "/inventory/procurements/{procurement_id}",
    response_model=ApiProcurement,
)
def update_procurement(
    procurement_id: str,
    body: ApiProcurementUpdate,
    request: Request,
    identity: Identity = _operator,
) -> ApiProcurement:
    """Update procurement fields; changes sync to every member Asset."""
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        row = request.app.state.inventory.update_procurement(
            procurement_id, changes, actor=identity.name
        )
    except ProcurementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no procurement {procurement_id}") from exc
    return ApiProcurement(**row)


@router.delete("/inventory/procurements/{procurement_id}", status_code=204)
def delete_procurement(
    procurement_id: str, request: Request, identity: Identity = _operator
) -> Response:
    """Ungroup members (their fields stay) and delete the Procurement."""
    if not request.app.state.inventory.delete_procurement(procurement_id, actor=identity.name):
        raise HTTPException(status_code=404, detail=f"no procurement {procurement_id}")
    return Response(status_code=204)


@router.get(
    "/inventory/events", response_model=ApiInventoryEventListResponse, dependencies=[_viewer]
)
def list_events(
    request: Request,
    asset_id: str | None = None,
    actor: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> ApiInventoryEventListResponse:
    """The cross-Asset event feed, newest first.

    This is the only read that reaches a deleted Asset's history: its detail
    endpoint 404s once the row is gone. Gated at viewer, matching the per-asset
    events already visible in the detail response — same data, wider window.
    """
    rows = request.app.state.inventory.all_events(
        asset_id=asset_id or "",
        actor=actor or "",
        since=since or "",
        until=until or "",
        limit=limit,
    )
    return ApiInventoryEventListResponse(events=[ApiInventoryEvent(**r) for r in rows])


@router.get("/inventory/{asset_id}", response_model=ApiAssetDetail, dependencies=[_viewer])
def get_asset(asset_id: str, request: Request) -> ApiAssetDetail:
    store = request.app.state.inventory
    row = store.get(asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no asset {asset_id}")
    return ApiAssetDetail(**row, events=store.events(asset_id))


@router.patch("/inventory/{asset_id}", response_model=ApiAsset)
def update_asset(
    asset_id: str, body: ApiAssetUpdate, request: Request, identity: Identity = _operator
) -> ApiAsset:
    store = request.app.state.inventory
    changes = {k: v for k, v in body.model_dump(exclude=_META).items() if v is not None}
    try:
        row = store.update(asset_id, changes, actor=identity.name, note=body.note)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no asset {asset_id}") from exc
    except UnknownStatusError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateSerialError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiAsset(**row)


@router.delete("/inventory/{asset_id}", status_code=204)
def delete_asset(asset_id: str, request: Request, identity: Identity = _operator) -> Response:
    """Hard delete for data-entry mistakes — retirement is a status.

    The Asset's events survive it; read them back through
    ``GET /api/inventory/events``.
    """
    if not request.app.state.inventory.delete(asset_id, actor=identity.name):
        raise HTTPException(status_code=404, detail=f"no asset {asset_id}")
    return Response(status_code=204)
