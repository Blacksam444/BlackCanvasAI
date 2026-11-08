"""Dated reflections on a project, independent of its editable studio plan."""

from contextlib import closing
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

import storage
from project_covers import require_project

router = APIRouter()


class JournalFields(BaseModel):
    entry_date: date
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("entry_date", mode="before")
    @classmethod
    def calendar_date(cls, value):
        if isinstance(value, str):
            # Reject timestamps and numeric coercion: this is the artist's local date.
            if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                raise ValueError("Choose a calendar date")
        elif type(value) is not date:
            raise ValueError("Choose a calendar date")
        return value

    @field_validator("body", mode="before")
    @classmethod
    def trim_body(cls, value):
        return value.strip() if isinstance(value, str) else value


class JournalCreate(JournalFields):
    id: str = Field(pattern=r"^journal_[a-f0-9]{32}$")


class JournalRevision(BaseModel):
    revision: int = Field(ge=1, strict=True)


class JournalUpdate(JournalFields, JournalRevision):
    pass


class JournalBackup(JournalRevision):
    id: str = Field(pattern=r"^journal_[a-f0-9]{32}$")
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    entry_date: date
    body: str = Field(max_length=5000)
    deleted: bool = Field(default=False, strict=True)
    created_at: datetime
    updated_at: datetime

    @field_validator("entry_date", mode="before")
    @classmethod
    def calendar_date(cls, value):
        return JournalFields.calendar_date(value)

    @model_validator(mode="after")
    def valid_entry(self):
        if not self.deleted:
            JournalFields(entry_date=self.entry_date, body=self.body)
        return self


def record(row) -> dict:
    return {key: row[key] for key in ("id", "project_id", "entry_date", "body", "revision", "created_at", "updated_at")}


def saved_entry(db, project_id, entry_id):
    return db.execute("SELECT * FROM project_journal WHERE project_id = ? AND id = ?", (project_id, entry_id)).fetchone()


def conflict():
    return HTTPException(status_code=409, detail="This journal entry changed on another device. Review the saved entry before keeping your edits.")


def require_entry(db, project_id, entry_id):
    require_project(db, project_id)
    row = saved_entry(db, project_id, entry_id)
    if row is None or row["deleted"]:
        raise HTTPException(status_code=404, detail="This journal entry was removed or is unavailable. Your text is kept here; you can save it as a new entry.")
    return row


@router.get("/api/projects/{project_id}/journal")
def list_journal(project_id: str) -> list[dict]:
    with closing(storage.connect()) as db:
        db.execute("BEGIN")
        require_project(db, project_id)
        return [record(row) for row in db.execute(
            "SELECT * FROM project_journal WHERE project_id = ? AND deleted = 0 "
            "ORDER BY entry_date DESC, created_at DESC, id DESC", (project_id,))]


@router.get("/api/projects/{project_id}/journal/{entry_id}")
def get_journal_entry(project_id: str, entry_id: str) -> dict:
    with closing(storage.connect()) as db:
        db.execute("BEGIN")
        return record(require_entry(db, project_id, entry_id))


@router.post("/api/projects/{project_id}/journal")
def create_journal_entry(project_id: str, payload: JournalCreate) -> dict:
    with closing(storage.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        require_project(db, project_id)
        existing = saved_entry(db, project_id, payload.id)
        if existing is not None:
            # The same creation request can be retried after a lost response.
            if not existing["deleted"] and existing["revision"] == 1 and existing["entry_date"] == payload.entry_date.isoformat() and existing["body"] == payload.body:
                return {"created": False, "entry": record(existing)}
            raise conflict()
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO project_journal(project_id, id, entry_date, body, revision, deleted, created_at, updated_at) "
                   "VALUES (?, ?, ?, ?, 1, 0, ?, ?)", (project_id, payload.id, payload.entry_date.isoformat(), payload.body, now, now))
        return {"created": True, "entry": record(saved_entry(db, project_id, payload.id))}


@router.put("/api/projects/{project_id}/journal/{entry_id}")
def update_journal_entry(project_id: str, entry_id: str, payload: JournalUpdate) -> dict:
    with closing(storage.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        saved = require_entry(db, project_id, entry_id)
        same = saved["entry_date"] == payload.entry_date.isoformat() and saved["body"] == payload.body
        if saved["revision"] != payload.revision:
            if same and saved["revision"] == payload.revision + 1:
                return record(saved)  # Exact update retry after a lost response.
            raise conflict()
        if not same:
            db.execute("UPDATE project_journal SET entry_date = ?, body = ?, revision = revision + 1, updated_at = ? "
                       "WHERE project_id = ? AND id = ?", (payload.entry_date.isoformat(), payload.body,
                        datetime.now(timezone.utc).isoformat(), project_id, entry_id))
        return record(saved_entry(db, project_id, entry_id))


@router.delete("/api/projects/{project_id}/journal/{entry_id}")
def delete_journal_entry(project_id: str, entry_id: str, payload: JournalRevision) -> dict:
    with closing(storage.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        require_project(db, project_id)
        saved = saved_entry(db, project_id, entry_id)
        if saved is None:
            raise HTTPException(status_code=404, detail="Journal entry not found")
        if saved["deleted"] and saved["revision"] in {payload.revision, payload.revision + 1}:
            return {"removed": entry_id}
        if saved["revision"] != payload.revision or saved["deleted"]:
            raise conflict()
        # Keep only a retry marker, so a delayed creation cannot resurrect removed text.
        db.execute("UPDATE project_journal SET body = '', deleted = 1, revision = revision + 1, updated_at = ? "
                   "WHERE project_id = ? AND id = ?", (datetime.now(timezone.utc).isoformat(), project_id, entry_id))
        return {"removed": entry_id}


def validate_journal_backups(manifest: dict) -> list[JournalBackup]:
    values = manifest.get("project_journal", [])
    if not isinstance(values, list):
        raise HTTPException(status_code=400, detail="The project journal backup list is invalid")
    try:
        entries = [JournalBackup.model_validate(value) for value in values]
        if len({(item.project_id, item.id) for item in entries}) != len(entries):
            raise ValueError("Duplicate journal entries")
        return entries
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=400, detail="A project journal entry in this backup is invalid") from error


def restore_journal(db, entries: list[JournalBackup], new_project_ids: set[str]) -> int:
    restored = 0
    for entry in entries:
        if entry.project_id not in new_project_ids:
            continue
        if not db.execute("SELECT 1 FROM projects WHERE id = ?", (entry.project_id,)).fetchone():
            continue
        cursor = db.execute("INSERT OR IGNORE INTO project_journal(project_id, id, entry_date, body, revision, deleted, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (entry.project_id, entry.id, entry.entry_date.isoformat(), "" if entry.deleted else entry.body.strip(),
                             entry.revision, int(entry.deleted), entry.created_at.isoformat(), entry.updated_at.isoformat()))
        restored += max(cursor.rowcount, 0)
    return restored
