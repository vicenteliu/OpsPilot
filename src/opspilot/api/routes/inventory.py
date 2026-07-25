"""Inventory routes — Asset CRUD + event log (ADR-0017).

OpsPilot is the system of record for Assets, so unlike every other route
family these endpoints own their data: writes append Asset events, the
row is a projection, the log is the history.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from ...inventory import AssetNotFoundError, DuplicateSerialError, UnknownStatusError
from ..types import (
    ApiAsset,
    ApiAssetCreate,
    ApiAssetDetail,
    ApiAssetListResponse,
    ApiAssetUpdate,
)

router = APIRouter()

_META = {"actor", "note"}


@router.post("/inventory", response_model=ApiAsset, status_code=201)
def create_asset(body: ApiAssetCreate, request: Request) -> ApiAsset:
    store = request.app.state.inventory
    try:
        row = store.create(body.model_dump(exclude=_META), actor=body.actor, note=body.note)
    except UnknownStatusError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateSerialError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiAsset(**row)


@router.get("/inventory", response_model=ApiAssetListResponse)
def list_assets(
    request: Request,
    status: str | None = None,
    assignee: str | None = None,
    q: str | None = None,
) -> ApiAssetListResponse:
    rows = request.app.state.inventory.list(status=status, assignee=assignee, q=q)
    return ApiAssetListResponse(assets=[ApiAsset(**r) for r in rows])


@router.get("/inventory/{asset_id}", response_model=ApiAssetDetail)
def get_asset(asset_id: str, request: Request) -> ApiAssetDetail:
    store = request.app.state.inventory
    row = store.get(asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no asset {asset_id}")
    return ApiAssetDetail(**row, events=store.events(asset_id))


@router.patch("/inventory/{asset_id}", response_model=ApiAsset)
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


@router.delete("/inventory/{asset_id}", status_code=204)
def delete_asset(asset_id: str, request: Request) -> Response:
    """Hard delete for data-entry mistakes — retirement is a status."""
    if not request.app.state.inventory.delete(asset_id):
        raise HTTPException(status_code=404, detail=f"no asset {asset_id}")
    return Response(status_code=204)
