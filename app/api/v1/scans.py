from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, UploadFile

from app.api.deps import DB, LLM, ClassifierDep, CurrentUser, SettingsDep, StorageDep
from app.api.v1.docs import AI, AUTH, errors
from app.core.rate_limit import ai_limit, limiter
from app.core.responses import ok
from app.schemas.common import Envelope, MealType, Page
from app.schemas.intake import IntakeEntryOut
from app.schemas.scan import ScanItemsPatch, ScanLogIn, ScanResult, ScanSummary
from app.services import intake_service, scan_service

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post(
    "",
    status_code=201,
    response_model=Envelope[ScanResult],
    summary="Scan a food photo",
    description=(
        "Multipart upload. Pipeline: validate & normalise image → transfer-learned classifier hints "
        "(ViT/Food-101) → Gemini vision per-item analysis → server-side totals → deterministic health score "
        "and flags (+ Gemini tips). `meal_type` defaults from the user's local time. Non-food images return "
        "`422 NOT_FOOD` (the rejected scan is stored; its id is in `details.scan_id`)."
    ),
    responses=errors(*AUTH, "INVALID_IMAGE", "FILE_TOO_LARGE", "NOT_FOOD", "VALIDATION_ERROR", *AI),
)
@limiter.limit(ai_limit)
async def create_scan(
    request: Request,
    user: CurrentUser,
    db: DB,
    llm: LLM,
    classifier: ClassifierDep,
    storage: StorageDep,
    settings: SettingsDep,
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP, ≤ MAX_UPLOAD_MB")],
    description: Annotated[str | None, Form(max_length=300, description="Optional hint, e.g. 'hostel lunch'")] = None,
    meal_type: Annotated[MealType | None, Form(description="Defaults from local time")] = None,
) -> dict:
    scan = await scan_service.create_scan(
        db,
        user,
        upload=image,
        description=description,
        meal_type=meal_type,
        llm=llm,
        classifier=classifier,
        storage=storage,
        settings=settings,
    )
    return ok(scan_service.to_result(scan, storage), "SCAN_CREATED", "Food analysed")


@router.get(
    "",
    response_model=Envelope[Page[ScanSummary]],
    summary="List scans",
    description="Newest first. Optional `date` (YYYY-MM-DD, user's timezone) filter.",
    responses=errors(*AUTH, "VALIDATION_ERROR"),
)
async def list_scans(
    user: CurrentUser,
    db: DB,
    storage: StorageDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    date: Annotated[date | None, Query(description="YYYY-MM-DD in the user's timezone")] = None,
) -> dict:
    scans, total = await scan_service.list_scans(db, user, page=page, page_size=page_size, day=date)
    data = {
        "items": [scan_service.to_summary(s, storage) for s in scans],
        "page": page,
        "page_size": page_size,
        "total": total,
    }
    return ok(data)


@router.get(
    "/{scan_id}",
    response_model=Envelope[ScanResult],
    summary="Get a scan",
    description="Full `ScanResult` for one of your scans (other users' scans return 404).",
    responses=errors(*AUTH, "NOT_FOUND"),
)
async def get_scan(scan_id: str, user: CurrentUser, db: DB, storage: StorageDep) -> dict:
    scan = await scan_service.get_scan(db, user, scan_id)
    return ok(scan_service.to_result(scan, storage))


@router.patch(
    "/{scan_id}/items",
    response_model=Envelope[ScanResult],
    summary="Edit scan items",
    description=(
        "Apply edits in order. `{id, quantity_g}` rescales nutrients linearly; `{id, name}` renames and "
        "re-estimates that item (Gemini text); `{id, remove: true}` removes; `{name, quantity_g?}` without an id "
        "adds a new item (Gemini text). Totals, score and flags are recomputed; tips are kept "
        "(regenerate with `POST /scans/{id}/tips`)."
    ),
    responses=errors(*AUTH, "NOT_FOUND", "NOT_FOOD", "VALIDATION_ERROR", *AI),
)
@limiter.limit(ai_limit)
async def edit_items(
    request: Request, scan_id: str, body: ScanItemsPatch, user: CurrentUser, db: DB, llm: LLM, storage: StorageDep
) -> dict:
    scan = await scan_service.get_scan(db, user, scan_id)
    scan = await scan_service.edit_items(db, user, scan, body.items, llm)
    return ok(scan_service.to_result(scan, storage), "SCAN_UPDATED", "Scan updated")


@router.post(
    "/{scan_id}/tips",
    response_model=Envelope[ScanResult],
    summary="Regenerate tips",
    description="Ask Gemini for fresh tips for the current items, totals and flags.",
    responses=errors(*AUTH, "NOT_FOUND", *AI),
)
@limiter.limit(ai_limit)
async def regenerate_tips(
    request: Request, scan_id: str, user: CurrentUser, db: DB, llm: LLM, storage: StorageDep
) -> dict:
    scan = await scan_service.get_scan(db, user, scan_id)
    scan = await scan_service.regenerate_tips(db, user, scan, llm)
    return ok(scan_service.to_result(scan, storage), "TIPS_UPDATED", "Tips updated")


@router.post(
    "/{scan_id}/log",
    status_code=201,
    response_model=Envelope[IntakeEntryOut],
    summary="Add scan to today's intake",
    description="Creates an intake entry (source `scan`) from the scan's current items. Logging twice → 409.",
    responses=errors(*AUTH, "NOT_FOUND", "ALREADY_LOGGED", "VALIDATION_ERROR"),
)
async def log_scan(scan_id: str, user: CurrentUser, db: DB, body: ScanLogIn | None = None) -> dict:
    body = body or ScanLogIn()
    scan = await scan_service.get_scan(db, user, scan_id)
    entry = await scan_service.log_scan(db, user, scan, meal_type=body.meal_type, eaten_at=body.eaten_at)
    return ok(intake_service.to_out(entry), "INTAKE_LOGGED", "Added to your intake")


@router.delete(
    "/{scan_id}",
    response_model=Envelope[None],
    summary="Delete a scan",
    description="Deletes the scan and its image. Intake entries created from it are kept.",
    responses=errors(*AUTH, "NOT_FOUND"),
)
async def delete_scan(scan_id: str, user: CurrentUser, db: DB, storage: StorageDep) -> dict:
    scan = await scan_service.get_scan(db, user, scan_id)
    await scan_service.delete_scan(db, user, scan, storage)
    return ok(None, "DELETED", "Scan deleted")
