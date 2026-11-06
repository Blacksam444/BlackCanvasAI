"""Reusable visual preferences, applied explicitly to new Think Tank briefs."""

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, field_validator

import storage
from think_tank import USER_DIRECTION

router = APIRouter()


class CreativePreferences(BaseModel):
    materials: list[Literal["acrylic", "charcoal", "pastel", "collage", "ink"]] = Field(default_factory=list, max_length=5)
    surface: Literal["canvas", "paper", "panel"] = "canvas"
    collection: Literal["My own direction", "AfroNova", "Quiet Nova", "GraffitiX"] = USER_DIRECTION
    other_materials: str = Field(default="", max_length=240)
    style_direction: str = Field(default="", max_length=600)
    palette: str = Field(default="", max_length=2600)
    mood: str = Field(default="", max_length=2600)
    avoid: str = Field(default="", max_length=1200)

    @field_validator("other_materials", "style_direction", "palette", "mood", "avoid", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("materials")
    @classmethod
    def unique_materials(cls, value):
        return [name for name in ("acrylic", "collage", "ink", "charcoal", "pastel") if name in value]


class KitPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    preferences: CreativePreferences

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class KitUpdatePayload(KitPayload):
    revision: int = Field(ge=1)


class KitBackupPayload(KitUpdatePayload):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    created_at: datetime
    updated_at: datetime


def kit_record(row) -> dict:
    item = dict(row)
    item.pop("name_key", None)
    item["preferences"] = json.loads(item["preferences"])
    return item


@router.get("/api/creative-kits")
def list_kits() -> list[dict]:
    with closing(storage.connect()) as db:
        return [kit_record(row) for row in db.execute("SELECT * FROM creative_kits ORDER BY name_key, id")]


@router.post("/api/creative-kits")
def create_kit(payload: KitPayload) -> dict:
    preferences = payload.preferences.model_dump()
    now = datetime.now(timezone.utc).isoformat()
    kit_id = uuid.uuid4().hex
    with closing(storage.connect()) as db, db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO creative_kits(id, name, name_key, preferences, revision, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            (kit_id, payload.name, payload.name.casefold(), json.dumps(preferences), now, now),
        )
        existing = kit_record(db.execute("SELECT * FROM creative_kits WHERE name_key = ?", (payload.name.casefold(),)).fetchone())
        if not cursor.rowcount and existing["preferences"] != preferences:
            raise HTTPException(status_code=409, detail="That kit name is already saved with different preferences. Choose another name, or select and update that kit.")
    return {"kit": existing, "created": cursor.rowcount > 0}


@router.put("/api/creative-kits/{kit_id}")
def update_kit(kit_id: str, payload: KitUpdatePayload) -> dict:
    try:
        with closing(storage.connect()) as db, db:
            cursor = db.execute(
                "UPDATE creative_kits SET name = ?, name_key = ?, preferences = ?, revision = revision + 1, updated_at = ? "
                "WHERE id = ? AND revision = ?",
                (payload.name, payload.name.casefold(), json.dumps(payload.preferences.model_dump()),
                 datetime.now(timezone.utc).isoformat(), kit_id, payload.revision),
            )
            if not cursor.rowcount:
                exists = db.execute("SELECT 1 FROM creative_kits WHERE id = ?", (kit_id,)).fetchone()
                raise HTTPException(status_code=409 if exists else 404, detail=(
                    "This kit changed on another device. Refresh saved kits and review it before updating. Your Think Tank fields are still here."
                    if exists else "Kit not found. Refresh saved kits before trying again."
                ))
            return kit_record(db.execute("SELECT * FROM creative_kits WHERE id = ?", (kit_id,)).fetchone())
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Another kit already uses that name. Choose a different name.") from error


@router.delete("/api/creative-kits/{kit_id}")
def delete_kit(kit_id: str, revision: int = Query(ge=1)) -> dict:
    with closing(storage.connect()) as db, db:
        cursor = db.execute("DELETE FROM creative_kits WHERE id = ? AND revision = ?", (kit_id, revision))
        if not cursor.rowcount:
            exists = db.execute("SELECT 1 FROM creative_kits WHERE id = ?", (kit_id,)).fetchone()
            raise HTTPException(status_code=409 if exists else 404, detail=(
                "This kit changed on another device. Refresh saved kits and review it before removing it."
                if exists else "Kit not found. Refresh saved kits before trying again."
            ))
    return {"status": "removed"}


def validate_kit_backups(manifest: dict) -> list[KitBackupPayload]:
    values = manifest.get("creative_kits", [])
    if not isinstance(values, list):
        raise HTTPException(status_code=400, detail="The backup creative kit list is invalid")
    try:
        return [KitBackupPayload.model_validate(value) for value in values]
    except ValidationError as error:
        raise HTTPException(status_code=400, detail="A creative kit in this backup is invalid") from error


def restore_kits(db, kits: list[KitBackupPayload]) -> int:
    restored = 0
    for item in kits:
        cursor = db.execute(
            "INSERT OR IGNORE INTO creative_kits(id, name, name_key, preferences, revision, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.id, item.name, item.name.casefold(), json.dumps(item.preferences.model_dump()), item.revision,
             item.created_at.isoformat(), item.updated_at.isoformat()),
        )
        restored += max(cursor.rowcount, 0)
    return restored
