"""
Endpoints for announcement management.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementPayload(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    start_date: Optional[str] = None
    expiration_date: str


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be in YYYY-MM-DD format"
        ) from exc


def _validate_dates(start_date: Optional[str], expiration_date: str) -> None:
    start = _parse_iso_date(start_date, "start_date") if start_date else None
    expiration = _parse_iso_date(expiration_date, "expiration_date")

    if start and start > expiration:
        raise HTTPException(
            status_code=400,
            detail="start_date must be earlier than or equal to expiration_date"
        )


def _require_teacher(username: Optional[str]) -> Dict[str, Any]:
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    teacher = teachers_collection.find_one({"_id": username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


def _serialize_announcement(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "message": doc["message"],
        "start_date": doc.get("start_date"),
        "expiration_date": doc["expiration_date"]
    }


def _is_active(doc: Dict[str, Any], today: date) -> bool:
    start_raw = doc.get("start_date")
    expiration_raw = doc.get("expiration_date")

    if not expiration_raw:
        return False

    expiration = _parse_iso_date(expiration_raw, "expiration_date")
    if expiration < today:
        return False

    if start_raw:
        start = _parse_iso_date(start_raw, "start_date")
        if start > today:
            return False

    return True


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def list_active_announcements() -> List[Dict[str, Any]]:
    """Return currently active announcements for public display."""
    today = date.today()
    docs = announcements_collection.find().sort("expiration_date", 1)

    active_announcements: List[Dict[str, Any]] = []
    for doc in docs:
        if _is_active(doc, today):
            active_announcements.append(_serialize_announcement(doc))

    return active_announcements


@router.get("/manage", response_model=List[Dict[str, Any]])
def list_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Return all announcements for authenticated management UI."""
    _require_teacher(teacher_username)

    docs = announcements_collection.find().sort("expiration_date", 1)
    return [_serialize_announcement(doc) for doc in docs]


@router.post("", response_model=Dict[str, Any])
def create_announcement(
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Create a new announcement with expiration date and optional start date."""
    _require_teacher(teacher_username)
    _validate_dates(payload.start_date, payload.expiration_date)

    announcement = {
        "message": payload.message.strip(),
        "start_date": payload.start_date,
        "expiration_date": payload.expiration_date
    }

    if not announcement["message"]:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    result = announcements_collection.insert_one(announcement)
    created = announcements_collection.find_one({"_id": result.inserted_id})

    if not created:
        raise HTTPException(status_code=500, detail="Failed to create announcement")

    return _serialize_announcement(created)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement."""
    _require_teacher(teacher_username)
    _validate_dates(payload.start_date, payload.expiration_date)

    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    result = announcements_collection.update_one(
        {"_id": object_id},
        {
            "$set": {
                "message": payload.message.strip(),
                "start_date": payload.start_date,
                "expiration_date": payload.expiration_date
            }
        }
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated = announcements_collection.find_one({"_id": object_id})
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to load updated announcement")

    return _serialize_announcement(updated)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an announcement."""
    _require_teacher(teacher_username)

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    result = announcements_collection.delete_one({"_id": object_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}
