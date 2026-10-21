"""Food scan pipeline (flow A) plus scan editing, tips and logging."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any

from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, not_found
from app.db.models import ChatSession, IntakeEntry, Scan, ScanItem, User
from app.schemas.scan import ItemEdit
from app.services import images, intake_service
from app.services.classifier import Classifier
from app.services.health_engine import compute_targets, score_meal
from app.services.llm.gemini_client import LLMClient
from app.services.llm.schemas import FoodAnalysisLLM, LLMFoodItem
from app.services.nutrition import aggregate, canonicalize, per_100g, round_nutrients, sanitize, scale
from app.services.nutrition_db import ground_items
from app.services.storage import Storage
from app.services.user_service import user_context
from app.utils.timeutil import day_bounds_utc, default_meal_type, get_tz, now_local

logger = logging.getLogger(__name__)

MAX_TIPS = 3
UNKNOWN_WEIGHT_G = 100.0  # reference portion when Gemini gives no weight for an item


# ---------------------------------------------------------------------- item helpers


def item_from_llm(item: LLMFoodItem, *, source: str = "ai") -> dict[str, Any]:
    """Validated LLM item → FoodItem dict with sanitised nutrients and per-100 g values.

    A missing weight (≤ 0 g) is treated as a 100 g reference portion with low confidence, so the per-100 g
    values stay consistent with the nutrients and later gram edits rescale them instead of zeroing them."""
    qty = round(max(float(item.quantity_g), 0.0), 1)
    serving = (item.serving_description or "").strip()[:200] or None
    confidence = item.confidence
    if qty <= 0:
        qty, confidence = UNKNOWN_WEIGHT_G, "low"
        serving = f"weight not estimated (~{UNKNOWN_WEIGHT_G:g} g assumed)"
    nutrients = round_nutrients(sanitize(item.nutrients.model_dump(), context=item.canonical_name))
    return {
        "name": item.name.strip()[:120] or "Food item",
        "canonical_name": canonicalize(item.canonical_name or item.name)[:120],
        "quantity_g": qty,
        "serving_description": serving,
        "confidence": confidence,
        "source": source,
        "nutrition_source": "estimate",  # set to "table" by ground_items when the food is in the foods table
        "nutrients": nutrients,
        "nutrients_per_100g": per_100g(nutrients, qty),
    }


def scan_item_dict(it: ScanItem) -> dict[str, Any]:
    return {
        "id": it.id,
        "name": it.name,
        "canonical_name": it.canonical_name,
        "quantity_g": it.quantity_g,
        "serving_description": it.serving_description,
        "confidence": it.confidence,
        "source": it.source,
        "nutrition_source": it.nutrition_source,
        "nutrients": it.nutrients,
    }


def _clean_tips(tips: list[str] | None) -> list[str]:
    return [t.strip() for t in (tips or []) if t and t.strip()][:MAX_TIPS]


# ---------------------------------------------------------------------- serialisers


def to_result(scan: Scan, storage: Storage) -> dict[str, Any]:
    classifier = None
    if scan.classifier_predictions is not None and scan.classifier_model:
        classifier = {"model": scan.classifier_model, "predictions": scan.classifier_predictions}
    return {
        "id": scan.id,
        "status": scan.status,
        "image_url": storage.url(scan.image_path),
        "meal_name": scan.meal_name,
        "meal_type": scan.meal_type,
        "description": scan.description,
        "classifier": classifier,
        "items": [scan_item_dict(i) for i in scan.items],
        "totals": scan.totals,
        "health": scan.health or None,
        "ai_model": scan.ai_model,
        "logged_intake_id": scan.logged_intake_id,
        "created_at": scan.created_at,
    }


def to_summary(scan: Scan, storage: Storage) -> dict[str, Any]:
    health = scan.health or None
    return {
        "id": scan.id,
        "status": scan.status,
        "image_url": storage.url(scan.image_path),
        "meal_name": scan.meal_name,
        "meal_type": scan.meal_type,
        "totals": {"calories": (scan.totals or {}).get("calories", 0.0)},
        "health": {"score": health["score"], "label": health["label"], "color": health["color"]} if health else None,
        "created_at": scan.created_at,
    }


# ---------------------------------------------------------------------- queries


async def get_scan(db: AsyncSession, user: User, scan_id: str) -> Scan:
    """Load a scan owned by the user (404 otherwise, including other users' scans)."""
    scan = await db.scalar(select(Scan).where(Scan.id == scan_id, Scan.user_id == user.id))
    if scan is None:
        raise not_found("Scan")
    return scan


async def list_scans(
    db: AsyncSession, user: User, *, page: int, page_size: int, day: date | None
) -> tuple[list[Scan], int]:
    conditions = [Scan.user_id == user.id]
    if day is not None:
        start, end = day_bounds_utc(day, get_tz(user.profile.timezone if user.profile else None))
        conditions += [Scan.created_at >= start, Scan.created_at < end]
    total = await db.scalar(select(func.count()).select_from(Scan).where(*conditions)) or 0
    rows = await db.scalars(
        select(Scan).where(*conditions).order_by(Scan.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return list(rows), total


# ---------------------------------------------------------------------- pipeline


async def create_scan(
    db: AsyncSession,
    user: User,
    *,
    upload: UploadFile,
    description: str | None,
    meal_type: str | None,
    llm: LLMClient,
    classifier: Classifier,
    storage: Storage,
    settings: Settings,
) -> Scan:
    """upload → normalise → save → classifier hints → Gemini analysis → totals → health → persist."""
    started = time.perf_counter()
    image = await images.validate_and_normalise(upload, settings.max_upload_bytes)
    tz = get_tz(user.profile.timezone if user.profile else None)
    meal_type_explicit = meal_type is not None  # user picked it → score against that meal's share
    meal_type = meal_type or default_meal_type(now_local(tz))  # a sensible label for display/logging
    description = description.strip()[:300] if description and description.strip() else None

    rel_path = await storage.save(image.data, "jpg")
    try:
        predictions = await classifier.predict(image.data)
        analysis: FoodAnalysisLLM = await llm.analyze_food_image(
            image.data,
            image.mime,
            hints=predictions or [],
            user_ctx=user_context(user),
            description=description,
        )
    except Exception:
        await storage.delete(rel_path)
        raise

    scan = Scan(
        user_id=user.id,
        image_path=rel_path,
        image_sha256=image.sha256,
        description=description,
        meal_type=meal_type,
        meal_type_explicit=meal_type_explicit,
        classifier_model=classifier.model_id if predictions is not None else None,
        classifier_predictions=predictions,
        ai_model=llm.last_model_used,
        raw_ai_response=analysis.model_dump(mode="json"),
    )

    if not analysis.is_food or not analysis.items:
        scan.status = "rejected"
        scan.totals = round_nutrients({})
        scan.health = {}
        scan.latency_ms = int((time.perf_counter() - started) * 1000)
        db.add(scan)
        await db.commit()
        reason = analysis.rejection_reason or "No food detected in the image."
        logger.info("scan rejected", extra={"scan_id": scan.id, "latency_ms": scan.latency_ms})
        raise AppError("NOT_FOOD", "No food detected in the image.", 422, {"scan_id": scan.id, "reason": reason})

    items = [item_from_llm(i) for i in analysis.items]
    await ground_items(db, items)  # replace estimates with foods-table values where the dish is known
    totals = aggregate(i["nutrients"] for i in items)
    targets = compute_targets(user.profile).nutrients
    scan.status = "completed"
    scan.meal_name = (analysis.meal_name or items[0]["name"]).strip()[:120]
    scan.totals = totals
    scan.health = score_meal(
        totals, targets, meal_type if meal_type_explicit else None, tips=_clean_tips(analysis.tips)
    )
    scan.items = [ScanItem(position=pos, **it) for pos, it in enumerate(items)]
    scan.latency_ms = int((time.perf_counter() - started) * 1000)
    db.add(scan)
    await db.commit()
    await db.refresh(scan, attribute_names=["items"])
    logger.info(
        "scan completed",
        extra={
            "scan_id": scan.id,
            "items": len(items),
            "score": scan.health["score"],
            "latency_ms": scan.latency_ms,
            "ai_model": scan.ai_model,
            "classifier": scan.classifier_model,
        },
    )
    return scan


def _recompute(scan: Scan, user: User) -> None:
    for pos, it in enumerate(scan.items):
        it.position = pos
    scan.totals = aggregate(i.nutrients for i in scan.items)
    tips = (scan.health or {}).get("tips", [])
    scan.health = score_meal(
        scan.totals,
        compute_targets(user.profile).nutrients,
        scan.meal_type if scan.meal_type_explicit else None,
        tips=tips,
    )


def _ensure_completed(scan: Scan) -> None:
    if scan.status != "completed":
        raise AppError("VALIDATION_ERROR", "This scan was rejected (no food), so it can't be edited or logged.", 422)


async def _estimate_single(
    db: AsyncSession, llm: LLMClient, user: User, name: str, grams: float | None
) -> dict[str, Any]:
    text = f"{grams:g} g {name}" if grams else name
    est = await llm.estimate_from_text(text, user_ctx=user_context(user))
    if not est.is_food or not est.items:
        raise AppError("NOT_FOOD", f"Couldn't recognise '{name}' as a food.", 422)
    item = item_from_llm(est.items[0])
    if grams:  # the estimate may report a different weight; rescale linearly to what the user asked for
        item["quantity_g"] = round(grams, 1)
    await ground_items(db, [item])  # prefer the foods table for this item too
    if grams:
        item["nutrients"] = scale(item["nutrients_per_100g"], grams)
    return item


async def edit_items(db: AsyncSession, user: User, scan: Scan, edits: list[ItemEdit], llm: LLMClient) -> Scan:
    """Apply gram changes, renames, removals and additions; recompute totals and health (tips kept)."""
    _ensure_completed(scan)
    by_id = {i.id: i for i in scan.items}
    for edit in edits:
        if edit.id is None:
            est = await _estimate_single(db, llm, user, edit.name or "", edit.quantity_g)
            scan.items.append(
                ScanItem(
                    position=len(scan.items),
                    name=(edit.name or est["name"]).strip()[:120],
                    canonical_name=est["canonical_name"],
                    quantity_g=est["quantity_g"],
                    serving_description=f"{est['quantity_g']:g} g (added)",
                    confidence=est["confidence"],
                    source="user_added",
                    nutrition_source=est.get("nutrition_source", "estimate"),
                    nutrients=est["nutrients"],
                    nutrients_per_100g=est["nutrients_per_100g"],
                )
            )
            continue

        item = by_id.get(edit.id)
        if item is None or item not in scan.items:
            raise AppError("NOT_FOUND", f"Item {edit.id} not found in this scan.", 404)
        if edit.remove:
            scan.items.remove(item)
            continue
        grams = edit.quantity_g if edit.quantity_g is not None else item.quantity_g
        if edit.name is not None and edit.name.strip() != item.name:
            est = await _estimate_single(db, llm, user, edit.name.strip(), grams)
            item.name = edit.name.strip()[:120]
            item.canonical_name = est["canonical_name"]
            item.confidence = est["confidence"]
            item.nutrition_source = est.get("nutrition_source", "estimate")
            item.nutrients_per_100g = est["nutrients_per_100g"]
            item.nutrients = est["nutrients"]
            item.quantity_g = est["quantity_g"]
        else:
            item.nutrients = scale(item.nutrients_per_100g, grams)
            item.quantity_g = round(grams, 1)
        item.serving_description = f"{item.quantity_g:g} g (edited)"
        item.source = "user_edit"

    if not scan.items:  # nothing is committed: the request's session is rolled back
        raise AppError(
            "VALIDATION_ERROR",
            "A scan needs at least one item. Delete the scan instead of removing every item.",
            422,
            [{"loc": ["body", "items"], "msg": "would remove every item", "type": "value_error"}],
        )
    _recompute(scan, user)
    scan.updated_at = datetime.now().astimezone()
    await db.commit()
    await db.refresh(scan, attribute_names=["items"])
    return scan


async def regenerate_tips(db: AsyncSession, user: User, scan: Scan, llm: LLMClient) -> Scan:
    """Ask Gemini for new tips for the current items, totals and flags."""
    _ensure_completed(scan)
    health = dict(scan.health or {})
    result = await llm.generate_tips(
        items=[{"name": i.name, "quantity_g": i.quantity_g} for i in scan.items],
        totals=scan.totals,
        flags=health.get("flags", []),
        user_ctx=user_context(user),
    )
    health["tips"] = _clean_tips(result.tips)
    scan.health = health
    scan.updated_at = datetime.now().astimezone()
    await db.commit()
    return scan


async def log_scan(
    db: AsyncSession,
    user: User,
    scan: Scan,
    *,
    meal_type: str | None,
    eaten_at: datetime | None,
    is_street_food: bool = False,
) -> IntakeEntry:
    """Create an intake entry from the scan. Logging twice (even concurrently) → ALREADY_LOGGED."""
    _ensure_completed(scan)
    if scan.logged_intake_id:
        raise _already_logged(scan.logged_intake_id)
    entry = intake_service.build_entry(
        user,
        source="scan",
        name=scan.meal_name or "Scanned meal",
        meal_type=meal_type or scan.meal_type,
        eaten_at=eaten_at,
        items=[scan_item_dict(i) for i in scan.items],
        scan_id=scan.id,
        is_street_food=is_street_food,
    )
    db.add(entry)
    await db.flush()
    # Claim the scan atomically: of two concurrent requests (a double-tap), only one matches the IS NULL guard.
    claimed = await db.execute(
        update(Scan)
        .where(Scan.id == scan.id, Scan.logged_intake_id.is_(None))
        .values(logged_intake_id=entry.id)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:  # another request logged it first; the uncommitted entry is rolled back with the request
        raise _already_logged(await db.scalar(select(Scan.logged_intake_id).where(Scan.id == scan.id)))
    scan.logged_intake_id = entry.id
    await db.commit()
    return entry


def _already_logged(intake_id: str | None) -> AppError:
    return AppError("ALREADY_LOGGED", "This scan is already logged to your intake.", 409, {"intake_id": intake_id})


async def delete_scan(db: AsyncSession, user: User, scan: Scan, storage: Storage) -> None:
    """Delete a scan and its image; linked intake entries and chat sessions are kept (unlinked)."""
    await db.execute(update(IntakeEntry).where(IntakeEntry.scan_id == scan.id).values(scan_id=None))
    await db.execute(update(ChatSession).where(ChatSession.scan_id == scan.id).values(scan_id=None))
    image_path = scan.image_path
    await db.delete(scan)
    await db.commit()
    await storage.delete(image_path)
