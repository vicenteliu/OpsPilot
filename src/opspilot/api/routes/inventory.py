"""Inventory routes — Asset CRUD + event log (ADR-0017).

OpsPilot is the system of record for Assets, so unlike every other route
family these endpoints own their data: writes append Asset events, the
row is a projection, the log is the history.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ...auth import require_role
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
    ApiProcurement,
    ApiProcurementCreate,
    ApiProcurementDetail,
    ApiProcurementListResponse,
    ApiProcurementUpdate,
)

router = APIRouter()

_META = {"actor", "note"}

# Role gates (ADR-0020): reads need viewer, writes need operator.
_viewer = Depends(require_role("viewer"))
_operator = Depends(require_role("operator"))


@router.post("/inventory", response_model=ApiAsset, status_code=201, dependencies=[_operator])
def create_asset(body: ApiAssetCreate, request: Request) -> ApiAsset:
    store = request.app.state.inventory
    try:
        row = store.create(body.model_dump(exclude=_META), actor=body.actor, note=body.note)
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
    dependencies=[_operator],
)
def create_procurement(body: ApiProcurementCreate, request: Request) -> ApiProcurement:
    """Group existing Assets; the Procurement adopts their common fields."""
    try:
        row = request.app.state.inventory.create_procurement(body.asset_ids, actor=body.actor)
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
    dependencies=[_operator],
)
def update_procurement(
    procurement_id: str, body: ApiProcurementUpdate, request: Request
) -> ApiProcurement:
    """Update procurement fields; changes sync to every member Asset."""
    changes = {k: v for k, v in body.model_dump(exclude={"actor"}).items() if v is not None}
    try:
        row = request.app.state.inventory.update_procurement(
            procurement_id, changes, actor=body.actor
        )
    except ProcurementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no procurement {procurement_id}") from exc
    return ApiProcurement(**row)


@router.delete(
    "/inventory/procurements/{procurement_id}", status_code=204, dependencies=[_operator]
)
def delete_procurement(procurement_id: str, request: Request) -> Response:
    """Ungroup members (their fields stay) and delete the Procurement."""
    if not request.app.state.inventory.delete_procurement(procurement_id):
        raise HTTPException(status_code=404, detail=f"no procurement {procurement_id}")
    return Response(status_code=204)


@router.get("/inventory/{asset_id}", response_model=ApiAssetDetail, dependencies=[_viewer])
def get_asset(asset_id: str, request: Request) -> ApiAssetDetail:
    store = request.app.state.inventory
    row = store.get(asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no asset {asset_id}")
    return ApiAssetDetail(**row, events=store.events(asset_id))


@router.patch("/inventory/{asset_id}", response_model=ApiAsset, dependencies=[_operator])
def update_asset(asset_id: str, body: ApiAssetUpdate, request: Request) -> ApiAsset:
    store = request.app.state.inventory
    changes = {k: v for k, v in body.model_dump(exclude=_META).items() if v is not None}
    try:
        row = store.update(asset_id, changes, actor=body.actor, note=body.note)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no asset {asset_id}") from exc
    except UnknownStatusError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateSerialError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiAsset(**row)


@router.delete("/inventory/{asset_id}", status_code=204, dependencies=[_operator])
def delete_asset(asset_id: str, request: Request) -> Response:
    """Hard delete for data-entry mistakes — retirement is a status."""
    if not request.app.state.inventory.delete(asset_id):
        raise HTTPException(status_code=404, detail=f"no asset {asset_id}")
    return Response(status_code=204)
