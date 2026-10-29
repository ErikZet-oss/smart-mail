"""Person mail UI prefs (SETTINGS 01a / 01b) used by W2 / W2o (Phase 1d)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.models import UserSettings

SortField = Literal["date_received", "date_sent", "subject", "from", "size"]
SortDir = Literal["asc", "desc"]
ListMode = Literal["list", "conversations"]
Density = Literal["compact", "comfortable"]
Theme = Literal["light", "dark", "system"]


class ListPrefs(BaseModel):
    sort: SortField = "date_received"
    sort_dir: SortDir = "desc"
    mode: ListMode = "list"
    density: Density = "compact"
    page_size: int = Field(default=50, ge=25, le=200)
    show_ai_summary: bool = True
    mark_read: Literal["immediate", "delay3", "never"] = "delay3"
    after_delete: Literal["next", "previous", "list"] = "next"


class UiPrefs(BaseModel):
    theme: Theme = "system"
    classic: bool = False
    remote_images: Literal["never", "known", "always"] = "known"
    prefer_html: bool = True


DEFAULT_LIST = ListPrefs()
DEFAULT_UI = UiPrefs()


async def _load(db: AsyncSession, person_id: uuid.UUID, section: str) -> dict[str, Any]:
    row = await db.scalar(
        select(UserSettings).where(UserSettings.person_id == person_id, UserSettings.section == section)
    )
    return dict(row.data) if row else {}


async def get_list_prefs(db: AsyncSession, person_id: uuid.UUID | None) -> ListPrefs:
    if person_id is None:
        return DEFAULT_LIST.model_copy()
    return ListPrefs.model_validate({**DEFAULT_LIST.model_dump(), **(await _load(db, person_id, "prefs.list"))})


async def get_ui_prefs(db: AsyncSession, person_id: uuid.UUID | None) -> UiPrefs:
    if person_id is None:
        return DEFAULT_UI.model_copy()
    return UiPrefs.model_validate({**DEFAULT_UI.model_dump(), **(await _load(db, person_id, "prefs.ui"))})


async def shortcuts_enabled(db: AsyncSession, person_id: uuid.UUID | None) -> bool:
    """Settings 01e `shortcuts_enabled` (default on), stored in the `prefs.shortcuts` section."""
    if person_id is None:
        return True
    data = await _load(db, person_id, "prefs.shortcuts")
    return data.get("shortcuts_enabled", data.get("enabled", True)) is not False


async def save_section(db: AsyncSession, person_id: uuid.UUID, section: str, data: dict[str, Any]) -> dict[str, Any]:
    row = await db.scalar(
        select(UserSettings).where(UserSettings.person_id == person_id, UserSettings.section == section)
    )
    if row is None:
        row = UserSettings(person_id=person_id, section=section, data=data)
        db.add(row)
    else:
        row.data = {**row.data, **data}
    await db.flush()
    return dict(row.data)
