"""Portable, read-only snapshots of a studio plan and selected project photos."""

import base64
import re
from datetime import datetime, timezone
from html import escape
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

import storage
from projects import ProjectUpdatePayload, get_project

router = APIRouter()
MAX_PHOTO_BYTES = 20 * 1024 * 1024
STATUS_LABELS = {"planned": "Planned", "in_progress": "In progress", "paused": "Paused", "completed": "Completed"}
STAGE_LABELS = {"reference": "Reference", "progress": "Work in progress", "finished": "Finished piece"}
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


class ProjectSheetPayload(BaseModel):
    plan: ProjectUpdatePayload
    include_notes: bool = True
    include_source: bool = False
    photo_ids: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list, max_length=12)

    @field_validator("photo_ids")
    @classmethod
    def unique_photos(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Choose each photo once")
        return values


def embed_photos(photos: list[dict]) -> list[dict]:
    result = []
    remaining = MAX_PHOTO_BYTES
    upload_root = storage.UPLOAD_DIR.resolve()
    for photo in photos:
        item = {**photo, "image": ""}
        image_path = (upload_root / photo["filename"]).resolve()
        mime_type = IMAGE_TYPES.get(image_path.suffix.lower())
        if image_path.is_relative_to(upload_root) and mime_type and image_path.is_file():
            try:
                with image_path.open("rb") as image:
                    data = image.read(remaining + 1)
            except OSError:
                data = b""
            if len(data) > remaining:
                raise HTTPException(status_code=413, detail="These photos are too large for one project sheet. Choose fewer photos (up to 20 MB total).")
            if data:
                item["image"] = f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"
                remaining -= len(data)
        result.append(item)
    return result


@router.post("/api/projects/{project_id}/sheet")
def create_project_sheet(project_id: str, payload: ProjectSheetPayload) -> dict:
    project = get_project(project_id)
    plan = payload.plan.model_dump()
    if plan["revision"] > project["revision"]:
        raise HTTPException(status_code=409, detail="The saved project has changed. Reload it before making another sheet; your edits are still here.")
    linked = {photo["id"]: photo for photo in project["artworks"]}
    if any(photo_id not in linked for photo_id in payload.photo_ids):
        raise HTTPException(status_code=409, detail="A selected photo is no longer linked to this project. Refresh photos, then make the sheet again.")
    photos = embed_photos([linked[photo_id] for photo_id in payload.photo_ids])
    saved = all(plan[key] == project[key] for key in plan)
    snapshot = "Saved plan copy" if saved else "Copy of current edits"
    stale = plan["revision"] < project["revision"]
    warning = "Newer changes are saved in the studio. This copy uses the plan shown on this device." if stale else ""
    prepared = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    completed = sum(step["done"] for step in plan["checklist"])
    progress = f"{completed} of {len(plan['checklist'])} steps checked"
    source = project["source_prompt"] if payload.include_source else None
    lines = ["BLACK CANVAS — PROJECT SHEET", plan["title"], f"{STATUS_LABELS[plan['status']]} · {progress}", snapshot, f"Prepared {prepared}"]
    if warning:
        lines.append(warning)
    material_lines = [f"- {material}" for material in plan["materials"]] or ["No materials added."]
    lines.extend(["", "MATERIALS", *material_lines,
                  "", "WORKING SURFACE", plan["surface"] or "No surface added.", "", "STUDIO CHECKLIST"])
    lines.extend(f"{index}. [{'x' if step['done'] else ' '}] {step['text']}" for index, step in enumerate(plan["checklist"], 1))
    if not plan["checklist"]:
        lines.append("No studio steps added.")
    if payload.include_notes:
        lines.extend(["", "STUDIO NOTES", plan["notes"] or "No notes added."])
    if payload.include_source:
        lines.extend(["", "SOURCE IDEA", source["title"] if source else "Source idea unavailable."])
        if source:
            if source["trashed"]:
                lines.append("Original idea is in Trash.")
            lines.append(source["text"])
    if photos:
        lines.extend(["", "PROJECT PHOTOS", "Images are embedded in the HTML copy; this text copy keeps their titles and notes."])
        for photo in photos:
            lines.append(f"- {STAGE_LABELS[photo['stage']]}: {photo['title']}")
            if not photo["image"]:
                lines.append("  Image unavailable in this copy.")
            if payload.include_notes and photo["notes"]:
                lines.append(photo["notes"])

    material_items = "".join(f"<li>{escape(item)}</li>" for item in plan["materials"])
    checklist = "".join(
        f'<li><span class="step-number">{index}.</span><span class="step-check" aria-label="{"Done" if step["done"] else "Not checked"}">{"✓" if step["done"] else ""}</span><div>{escape(step["text"])}</div></li>'
        for index, step in enumerate(plan["checklist"], 1)
    )
    notes = f'<section><h2>Studio notes</h2><p class="preserve">{escape(plan["notes"] or "No notes added.")}</p></section>' if payload.include_notes else ""
    source_html = ""
    if payload.include_source:
        source_body = (f'<h3>{escape(source["title"])}</h3>'
                       + ('<p class="muted">Original idea is in Trash.</p>' if source["trashed"] else "")
                       + f'<p class="preserve">{escape(source["text"])}</p>') if source else "<p>Source idea unavailable.</p>"
        source_html = f'<section class="source-idea"><h2>Source idea</h2>{source_body}</section>'
    photo_html = ""
    for photo in photos:
        picture = f'<img src="{photo["image"]}" alt="{escape(photo["title"])}">' if photo["image"] else '<p class="missing-photo">Image unavailable in this copy.</p>'
        photo_notes = f'<p class="preserve">{escape(photo["notes"])}</p>' if payload.include_notes and photo["notes"] else ""
        photo_html += f'<figure>{picture}<figcaption><span class="muted">{STAGE_LABELS[photo["stage"]]}</span><h3>{escape(photo["title"])}</h3>{photo_notes}</figcaption></figure>'
    if photo_html:
        photo_html = f'<section class="photos"><h2>Project photos</h2>{photo_html}</section>'
    stylesheet = (storage.BASE_DIR / "static" / "project-sheet.css").read_text(encoding="utf-8")
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f'<title>{escape(plan["title"])} · Project sheet</title><style>{stylesheet}</style></head><body><main>'
        f'<header><p class="brand">BLACK CANVAS · PROJECT SHEET</p><h1>{escape(plan["title"])}</h1>'
        f'<p class="summary">{STATUS_LABELS[plan["status"]]} · {progress}</p>'
        f'<p class="muted">{snapshot} · Prepared {prepared}</p>'
        + (f'<p class="copy-warning">{warning}</p>' if warning else "")
        + '</header><section><h2>Materials</h2>'
        + (f'<ul class="materials">{material_items}</ul>' if material_items else '<p>No materials added.</p>')
        + f'<h2>Working surface</h2><p>{escape(plan["surface"] or "No surface added.")}</p></section>'
        + '<section><h2>Studio checklist</h2>'
        + (f'<ol class="checklist">{checklist}</ol>' if checklist else '<p>No studio steps added.</p>')
        + f'</section>{notes}{source_html}{photo_html}<footer>Project sheet · {snapshot}. Making this copy does not save project changes.</footer></main></body></html>'
    )
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", plan["title"]).strip("-")[:80] or "studio-project"
    return {"html": html, "text": "\n".join(lines) + "\n", "filename": f"black-canvas-{slug.lower()}",
            "snapshot": snapshot, "warning": warning}
