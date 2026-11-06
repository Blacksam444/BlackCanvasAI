"""Persistent studio work, linked to existing Prompt Library ideas."""

import json
import re
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

import storage
from project_covers import clear_artwork_cover, cover_state

router = APIRouter()
ProjectStatus = Literal["planned", "in_progress", "paused", "completed"]
PhotoStage = Literal["reference", "progress", "finished"]


class ProjectArtworkPayload(BaseModel):
    artwork_id: int = Field(ge=1)
    stage: PhotoStage = "progress"


class ProjectArtworkStagePayload(BaseModel):
    stage: PhotoStage
    expected_stage: PhotoStage


class ProjectArtworkBackup(BaseModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    filename: str = Field(min_length=1, max_length=255)
    stage: PhotoStage
    created_at: datetime

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        if value in {".", ".."} or PurePosixPath(value).name != value or PureWindowsPath(value).name != value or ":" in value:
            raise ValueError("Photo backups need a plain filename")
        return value


def project_artworks(db, project_id: str) -> list[dict]:
    result = []
    for row in db.execute(
        "SELECT a.id, a.title, a.collection, a.notes, a.filename, pa.stage, pa.created_at "
        "FROM project_artworks pa JOIN artworks a ON a.id = pa.artwork_id "
        "WHERE pa.project_id = ? ORDER BY pa.created_at DESC, a.id DESC", (project_id,),
    ):
        item = dict(row)
        item["url"] = f"/uploads/{item['filename']}"
        result.append(item)
    return result


def attach_artwork(db, project_id: str, artwork_id: int, stage: PhotoStage) -> bool:
    if not db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Project not found")
    if not db.execute("SELECT 1 FROM artworks WHERE id = ?", (artwork_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Artwork not found")
    cursor = db.execute(
        "INSERT OR IGNORE INTO project_artworks(project_id, artwork_id, stage, created_at) VALUES (?, ?, ?, ?)",
        (project_id, artwork_id, stage, datetime.now(timezone.utc).isoformat()),
    )
    return cursor.rowcount > 0


@router.post("/api/projects/{project_id}/artworks")
def link_project_artwork(project_id: str, payload: ProjectArtworkPayload) -> dict:
    with closing(storage.connect()) as db, db:
        created = attach_artwork(db, project_id, payload.artwork_id, payload.stage)
        photos = project_artworks(db, project_id)
        cover = cover_state(db, project_id)
    return {"created": created, "artworks": photos, **cover}


@router.delete("/api/projects/{project_id}/artworks/{artwork_id}")
def unlink_project_artwork(project_id: str, artwork_id: int) -> dict:
    with closing(storage.connect()) as db, db:
        if not db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Project not found")
        db.execute("DELETE FROM project_artworks WHERE project_id = ? AND artwork_id = ?", (project_id, artwork_id))
        clear_artwork_cover(db, artwork_id, project_id)
        photos = project_artworks(db, project_id)
        cover = cover_state(db, project_id)
    return {"artworks": photos, **cover}


@router.put("/api/projects/{project_id}/artworks/{artwork_id}")
def update_project_artwork_stage(project_id: str, artwork_id: int, payload: ProjectArtworkStagePayload) -> dict:
    with closing(storage.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        photo = db.execute(
            "SELECT stage FROM project_artworks WHERE project_id = ? AND artwork_id = ?",
            (project_id, artwork_id),
        ).fetchone()
        if not photo:
            raise HTTPException(status_code=404, detail="This photo is no longer linked to the project. Refresh photos to see the saved gallery.")
        if photo["stage"] != payload.expected_stage:
            raise HTTPException(status_code=409, detail="The photo label changed on another device. Review the saved label before saving your choice.")
        db.execute(
            "UPDATE project_artworks SET stage = ? WHERE project_id = ? AND artwork_id = ?",
            (payload.stage, project_id, artwork_id),
        )
        photos = project_artworks(db, project_id)
        cover = cover_state(db, project_id)
    return {"artworks": photos, **cover}


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


class ProjectPlanPayload(ProjectSeedPayload):
    title: str = Field(min_length=1, max_length=200)
    status: ProjectStatus = "planned"

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProjectUpdatePayload(ProjectPlanPayload):
    revision: int = Field(ge=1)


class ProjectDirectCreatePayload(ProjectPlanPayload):
    id: str = Field(pattern=r"^direct_[a-f0-9]{32}$")


class ProjectArchivePayload(BaseModel):
    archived: bool = Field(strict=True)
    archive_revision: int = Field(ge=1, strict=True)


class ProjectCreatePayload(BaseModel):
    prompt_id: int = Field(ge=1)
    seed: ProjectSeedPayload | None = None


class ProjectBackupPayload(ProjectUpdatePayload):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    source_prompt_id: int | None = Field(default=None, ge=1)
    archived: bool = False
    archive_revision: int = Field(default=1, ge=1)
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
    result["archived"] = bool(result["archived"])
    total = len(result["checklist"])
    done = sum(bool(step["done"]) for step in result["checklist"])
    result["progress"] = {"done": done, "total": total, "percent": round(done / total * 100) if total else 0}
    result["started_directly"] = result["source_prompt_id"] is None and bool(re.fullmatch(r"direct_[a-f0-9]{32}", result["id"]))
    return result


def project_overview(db) -> dict:
    counts = {"planned": 0, "in_progress": 0, "paused": 0, "completed": 0}
    for row in db.execute("SELECT status, COUNT(*) AS count FROM projects WHERE archived = 0 GROUP BY status"):
        if row["status"] in counts:
            counts[row["status"]] = row["count"]
    counts["total"] = sum(counts.values())
    counts["ongoing"] = counts["total"] - counts["completed"]
    counts["archived"] = db.execute("SELECT COUNT(*) FROM projects WHERE archived = 1").fetchone()[0]
    counts["total"] += counts["archived"]
    recent = []
    for row in db.execute(
        "SELECT * FROM projects WHERE archived = 0 AND status IN ('planned', 'in_progress', 'paused') "
        "ORDER BY julianday(updated_at) DESC, id LIMIT 3"
    ):
        project = project_record(row)
        recent.append({key: project[key] for key in ("id", "title", "status", "materials", "surface", "progress", "updated_at")})
        recent[-1].update(cover_state(db, project["id"]))
    return {"counts": counts, "recent": recent}


def get_project(project_id: str) -> dict:
    with closing(storage.connect()) as db:
        db.execute("BEGIN")
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        result = project_record(row)
        source = db.execute("SELECT id, title, category, text, trashed FROM prompts WHERE id = ?", (row["source_prompt_id"],)).fetchone()
        result["source_prompt"] = dict(source) if source else None
        result["artworks"] = project_artworks(db, project_id)
        result.update(cover_state(db, project_id))
    return result


@router.get("/projects")
def projects_page() -> FileResponse:
    return FileResponse(storage.BASE_DIR / "templates" / "projects.html")


@router.get("/api/projects")
def list_projects() -> list[dict]:
    with closing(storage.connect()) as db:
        db.execute("BEGIN")
        result = []
        for row in db.execute("SELECT * FROM projects ORDER BY updated_at DESC, id"):
            item = project_record(row)
            del item["checklist"]
            item.update(cover_state(db, item["id"]))
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


@router.post("/api/projects/direct")
def create_direct_project(payload: ProjectDirectCreatePayload) -> dict:
    """Use the caller's stable ID so a retried creation cannot duplicate work."""
    now = datetime.now(timezone.utc).isoformat()
    plan = payload.model_dump(exclude={"id"})
    with closing(storage.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT * FROM projects WHERE id = ?", (payload.id,)).fetchone()
        if existing:
            saved = project_record(existing)
            if saved["source_prompt_id"] is not None or any(saved[key] != value for key, value in plan.items()):
                raise HTTPException(status_code=409, detail="This creation was already saved with different fields. Open the saved project, or create a separate project with this form.")
            created = False
        else:
            db.execute(
                "INSERT INTO projects(id, title, status, materials, surface, checklist, notes, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (payload.id, payload.title, payload.status, json.dumps(plan["materials"]), payload.surface,
                 json.dumps(plan["checklist"]), payload.notes, now, now),
            )
            created = True
    return {"project": get_project(payload.id), "created": created}


@router.get("/api/projects/{project_id}")
def project_detail(project_id: str) -> dict:
    return get_project(project_id)


def archive_state(db, project_id: str) -> dict:
    row = db.execute("SELECT archived, archive_revision FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"archived": bool(row["archived"]), "archive_revision": row["archive_revision"]}


@router.get("/api/projects/{project_id}/archive")
def get_project_archive(project_id: str) -> dict:
    with closing(storage.connect()) as db:
        return archive_state(db, project_id)


@router.put("/api/projects/{project_id}/archive")
def update_project_archive(project_id: str, payload: ProjectArchivePayload) -> dict:
    # Archive changes are independent of plan edits and their browser drafts.
    with closing(storage.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        saved = archive_state(db, project_id)
        if saved["archive_revision"] != payload.archive_revision:
            raise HTTPException(status_code=409, detail="The archive state changed on another device. Review its saved state before trying again; your plan edits are kept.")
        if saved["archived"] != payload.archived:
            db.execute("UPDATE projects SET archived = ?, archive_revision = archive_revision + 1 WHERE id = ?",
                       (int(payload.archived), project_id))
        return archive_state(db, project_id)


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


def validate_project_artwork_backups(manifest: dict) -> list[ProjectArtworkBackup]:
    values = manifest.get("project_artworks", [])
    if not isinstance(values, list):
        raise HTTPException(status_code=400, detail="The backup project photo list is invalid")
    try:
        return [ProjectArtworkBackup.model_validate(value) for value in values]
    except ValidationError as error:
        raise HTTPException(status_code=400, detail="A project photo in this backup is invalid") from error


def restore_project_artworks(db, photos: list[ProjectArtworkBackup], new_project_ids: set[str]) -> int:
    """Only restore links for newly restored projects, retaining deliberate removals."""
    restored = 0
    for item in photos:
        if item.project_id not in new_project_ids:
            continue
        artwork = db.execute("SELECT id FROM artworks WHERE filename = ? ORDER BY id LIMIT 1", (item.filename,)).fetchone()
        if not artwork or not db.execute("SELECT 1 FROM projects WHERE id = ?", (item.project_id,)).fetchone():
            continue
        cursor = db.execute(
            "INSERT OR IGNORE INTO project_artworks(project_id, artwork_id, stage, created_at) VALUES (?, ?, ?, ?)",
            (item.project_id, artwork["id"], item.stage, item.created_at.isoformat()),
        )
        restored += max(cursor.rowcount, 0)
    return restored


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
            "INSERT OR IGNORE INTO projects(id, source_prompt_id, title, status, materials, surface, checklist, notes, revision, archived, archive_revision, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, prompt_map.get(item.source_prompt_id), item.title, item.status, json.dumps(item.materials), item.surface,
             json.dumps([step.model_dump() for step in item.checklist]), item.notes, item.revision, int(item.archived), item.archive_revision,
             item.created_at.isoformat(), item.updated_at.isoformat()),
        )
        restored += max(cursor.rowcount, 0)
    return restored
