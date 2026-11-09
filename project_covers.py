"""User-chosen project images, backed by the existing linked artwork catalog."""

from contextlib import closing
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

import storage

router = APIRouter()
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class CoverPayload(BaseModel):
    artwork_id: int | None = Field(ge=1, strict=True)
    cover_revision: int = Field(ge=1, strict=True)


class CoverBackup(BaseModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    revision: int = Field(ge=1)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        if value is not None and (value in {".", ".."} or PurePosixPath(value).name != value
                                  or PureWindowsPath(value).name != value or ":" in value):
            raise ValueError("Covers need a plain image filename")
        return value


def available_image(filename: str) -> bool:
    root = storage.UPLOAD_DIR.resolve()
    path = (root / filename).resolve()
    return path.is_relative_to(root) and path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file()


def cover_state(db, project_id: str) -> dict:
    row = db.execute("SELECT artwork_id, revision FROM project_covers WHERE project_id = ?", (project_id,)).fetchone()
    chosen = row["artwork_id"] if row else None
    revision = row["revision"] if row else 1
    photos = db.execute(
        "SELECT a.id, a.filename, a.title, pa.stage FROM project_artworks pa JOIN artworks a ON a.id = pa.artwork_id "
        "WHERE pa.project_id = ? AND (? IS NOT NULL AND a.id = ? OR ? IS NULL AND pa.stage IN ('progress', 'finished')) "
        "ORDER BY julianday(pa.created_at) DESC, a.id DESC", (project_id, chosen, chosen, chosen),
    )
    cover = None
    for photo in photos:
        if available_image(photo["filename"]):
            cover = {"artwork_id": photo["id"], "url": f"/uploads/{quote(photo['filename'], safe='')}",
                     "title": photo["title"], "stage": photo["stage"], "mode": "chosen" if chosen else "automatic"}
            break
    return {"cover_artwork_id": chosen, "cover_revision": revision, "cover": cover,
            "cover_unavailable": chosen is not None and cover is None}


def require_project(db, project_id: str) -> None:
    if not db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/api/projects/{project_id}/cover")
def get_cover(project_id: str) -> dict:
    with closing(storage.connect()) as db:
        db.execute("BEGIN")
        require_project(db, project_id)
        return cover_state(db, project_id)


@router.put("/api/projects/{project_id}/cover")
def update_cover(project_id: str, payload: CoverPayload) -> dict:
    with closing(storage.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        require_project(db, project_id)
        saved = cover_state(db, project_id)
        if saved["cover_revision"] != payload.cover_revision:
            raise HTTPException(status_code=409, detail="The cover changed on another device. Review the saved cover and photos before saving your choice.")
        if payload.artwork_id is not None:
            photo = db.execute(
                "SELECT a.filename FROM project_artworks pa JOIN artworks a ON a.id = pa.artwork_id "
                "WHERE pa.project_id = ? AND a.id = ?", (project_id, payload.artwork_id),
            ).fetchone()
            if not photo:
                raise HTTPException(status_code=404, detail="This photo is no longer linked. Refresh the saved cover and photos to choose again.")
            if not available_image(photo["filename"]):
                raise HTTPException(status_code=422, detail="This image is unavailable. Choose another linked photo or Automatic.")
        if saved["cover_artwork_id"] != payload.artwork_id:
            db.execute(
                "INSERT INTO project_covers(project_id, artwork_id, revision) VALUES (?, ?, ?) "
                "ON CONFLICT(project_id) DO UPDATE SET artwork_id = excluded.artwork_id, revision = excluded.revision",
                (project_id, payload.artwork_id, saved["cover_revision"] + 1),
            )
        return cover_state(db, project_id)


def clear_artwork_cover(db, artwork_id: int, project_id: str | None = None) -> None:
    db.execute("UPDATE project_covers SET artwork_id = NULL, revision = revision + 1 "
               "WHERE artwork_id = ?" + (" AND project_id = ?" if project_id is not None else ""),
               (artwork_id, project_id) if project_id is not None else (artwork_id,))


def validate_cover_backups(manifest: dict) -> list[CoverBackup]:
    values = manifest.get("project_covers", [])
    if not isinstance(values, list):
        raise HTTPException(status_code=400, detail="The project cover backup list is invalid")
    try:
        covers = [CoverBackup.model_validate(value) for value in values]
        if len({cover.project_id for cover in covers}) != len(covers):
            raise ValueError("Duplicate project cover records")
        return covers
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=400, detail="A project cover in this backup is invalid") from error


def restore_covers(db, covers: list[CoverBackup], new_project_ids: set[str]) -> int:
    restored = 0
    for cover in covers:
        if cover.project_id not in new_project_ids:
            continue
        photo = db.execute(
            "SELECT a.id FROM project_artworks pa JOIN artworks a ON a.id = pa.artwork_id "
            "WHERE pa.project_id = ? AND a.filename = ?", (cover.project_id, cover.filename),
        ).fetchone() if cover.filename is not None else None
        cursor = db.execute("INSERT OR IGNORE INTO project_covers(project_id, artwork_id, revision) VALUES (?, ?, ?)",
                            (cover.project_id, photo["id"] if photo else None, cover.revision))
        restored += max(cursor.rowcount, 0)
    return restored
