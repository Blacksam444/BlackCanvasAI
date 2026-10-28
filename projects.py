"""Persistent studio work, linked to existing Prompt Library ideas."""

import json
import re
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

import storage

router = APIRouter()
ProjectStatus = Literal["planned", "in_progress", "paused", "completed"]


class ProjectStep(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    text: str = Field(min_length=1, max_length=2000)
    done: bool = False

    @field_validator("text", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProjectSeedPayload(BaseModel):
    materials: list[str] = Field(default_factory=list, max_length=30)
    surface: str = Field(default="", max_length=240)
    checklist: list[ProjectStep] = Field(default_factory=list, max_length=60)
    notes: str = Field(default="", max_length=5000)

    @field_validator("surface", "notes", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("materials")
    @classmethod
    def clean_materials(cls, values):
        values = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(value) > 240 for value in values):
            raise ValueError("Keep each material under 240 characters")
        return values

    @field_validator("checklist")
    @classmethod
    def unique_steps(cls, values):
        if len({step.id for step in values}) != len(values):
            raise ValueError("Checklist items need unique IDs")
        return values


class ProjectUpdatePayload(ProjectSeedPayload):
    title: str = Field(min_length=1, max_length=200)
    status: ProjectStatus = "planned"
    revision: int = Field(ge=1)

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProjectCreatePayload(BaseModel):
    prompt_id: int = Field(ge=1)
    seed: ProjectSeedPayload | None = None


class ProjectBackupPayload(ProjectUpdatePayload):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    source_prompt_id: int | None = Field(default=None, ge=1)
    created_at: datetime
    updated_at: datetime


def seed_project(text: str) -> dict:
    """Read the known Think Tank plan format; ordinary prompts start blank."""
    header, separator, plan = text.partition("\nSTUDIO PLAN\n")
    if not separator or not text.startswith("ART THINK TANK · PHYSICAL ART\n"):
        return {"materials": [], "surface": "", "checklist": [], "notes": ""}
    plan = re.split(r"\n(?:STUDIO NOTES|OPTIONAL IMAGE REFERENCE PROMPT)\n", plan, maxsplit=1)[0]
    steps = re.findall(r"(?m)^\d+\. (.+(?:\n(?!\d+\. ).+)*)", plan)
    material = re.search(r"(?m)^Materials: (.+)$", header)
    surface = re.search(r"(?m)^Surface: (.+)$", header)
    notes = re.search(r"\nSTUDIO NOTES\n(.*?)(?:\nOPTIONAL IMAGE REFERENCE PROMPT\n|$)", text, re.DOTALL)
    return {
        "materials": [value.strip()[:240] for value in (material.group(1).split(",") if material else []) if value.strip()][:30],
        "surface": surface.group(1)[:240] if surface else "",
        "checklist": [{"id": uuid.uuid4().hex, "text": value.strip()[:2000], "done": False} for value in steps[:60] if value.strip()],
        "notes": notes.group(1).strip()[:5000] if notes else "",
    }


def project_record(row) -> dict:
    result = dict(row)
    result["materials"] = json.loads(result["materials"])
    result["checklist"] = json.loads(result["checklist"])
    total = len(result["checklist"])
    done = sum(bool(step["done"]) for step in result["checklist"])
    result["progress"] = {"done": done, "total": total, "percent": round(done / total * 100) if total else 0}
    return result


def get_project(project_id: str) -> dict:
    with closing(storage.connect()) as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        result = project_record(row)
        source = db.execute("SELECT id, title, category, text, trashed FROM prompts WHERE id = ?", (row["source_prompt_id"],)).fetchone()
        result["source_prompt"] = dict(source) if source else None
    return result


@router.get("/projects")
def projects_page() -> FileResponse:
    return FileResponse(storage.BASE_DIR / "templates" / "projects.html")


@router.get("/api/projects")
def list_projects() -> list[dict]:
    with closing(storage.connect()) as db:
        result = []
        for row in db.execute("SELECT * FROM projects ORDER BY updated_at DESC, id"):
            item = project_record(row)
            del item["checklist"]
            result.append(item)
        return result


@router.post("/api/projects")
def create_project(payload: ProjectCreatePayload) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    project_id = uuid.uuid4().hex
    with closing(storage.connect()) as db, db:
        # Opening an existing project remains possible when its source is in Trash.
        existing = db.execute("SELECT id FROM projects WHERE source_prompt_id = ?", (payload.prompt_id,)).fetchone()
        if existing:
            project_id = existing["id"]
            created = False
        else:
            source = db.execute("SELECT title, text FROM prompts WHERE id = ? AND trashed = 0", (payload.prompt_id,)).fetchone()
            if not source:
                raise HTTPException(status_code=404, detail="Save an idea in the Prompt Library before starting a project")
            seed = payload.seed.model_dump() if payload.seed else seed_project(source["text"])
            cursor = db.execute(
                "INSERT OR IGNORE INTO projects(id, source_prompt_id, title, materials, surface, checklist, notes, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, payload.prompt_id, source["title"].strip()[:200] or "Untitled project", json.dumps(seed["materials"]),
                 seed["surface"], json.dumps(seed["checklist"]), seed["notes"], now, now),
            )
            created = cursor.rowcount > 0
            project_id = db.execute("SELECT id FROM projects WHERE source_prompt_id = ?", (payload.prompt_id,)).fetchone()["id"]
    return {"project": get_project(project_id), "created": created}


@router.get("/api/projects/{project_id}")
def project_detail(project_id: str) -> dict:
    return get_project(project_id)


@router.put("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdatePayload) -> dict:
    with closing(storage.connect()) as db, db:
        cursor = db.execute(
            "UPDATE projects SET title = ?, status = ?, materials = ?, surface = ?, checklist = ?, notes = ?, "
            "revision = revision + 1, updated_at = ? WHERE id = ? AND revision = ?",
            (payload.title, payload.status, json.dumps(payload.materials), payload.surface,
             json.dumps([step.model_dump() for step in payload.checklist]), payload.notes,
             datetime.now(timezone.utc).isoformat(), project_id, payload.revision),
        )
        if not cursor.rowcount:
            exists = db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
            raise HTTPException(status_code=409 if exists else 404, detail=(
                "This project changed on another device. Your edits are still here; reload the saved version before trying again."
                if exists else "Project not found"
            ))
    return get_project(project_id)


def validate_project_backups(manifest: dict) -> list[ProjectBackupPayload]:
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=400, detail="The backup manifest is invalid")
    values = manifest.get("projects", [])
    if not isinstance(values, list):
        raise HTTPException(status_code=400, detail="The backup project list is invalid")
    try:
        return [ProjectBackupPayload.model_validate(value) for value in values]
    except ValidationError as error:
        raise HTTPException(status_code=400, detail="A project in this backup is invalid; no projects were restored") from error


def restore_projects(db, projects: list[ProjectBackupPayload], manifest: dict, normalize_text) -> int:
    """Resolve old prompt IDs by saved content; retain existing project progress."""
    prompt_map = {}
    for source in manifest.get("prompts", []):
        match = db.execute("SELECT id FROM prompts WHERE title = ? AND text = ?", (
            source.get("title", "Restored prompt"), normalize_text(str(source.get("text", "")).strip()),
        )).fetchone()
        if match and source.get("id") is not None:
            prompt_map[source["id"]] = match["id"]
    restored = 0
    for item in projects:
        cursor = db.execute(
            "INSERT OR IGNORE INTO projects(id, source_prompt_id, title, status, materials, surface, checklist, notes, revision, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, prompt_map.get(item.source_prompt_id), item.title, item.status, json.dumps(item.materials), item.surface,
             json.dumps([step.model_dump() for step in item.checklist]), item.notes, item.revision,
             item.created_at.isoformat(), item.updated_at.isoformat()),
        )
        restored += max(cursor.rowcount, 0)
    return restored
