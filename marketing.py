import json
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl

from storage import connect, rows

router = APIRouter()
PLATFORMS = (
    ("instagram", "Instagram", "Reel", 0),
    ("pinterest", "Pinterest", "Pin", 1),
    ("facebook", "Facebook", "Photo post", 3),
    ("tiktok", "TikTok", "Video", 5),
)


class PlanDates(BaseModel):
    start_date: date = Field(ge=date(1900, 1, 1))
    listing_url: HttpUrl | None = None


class NewPlan(PlanDates):
    artwork_id: int
    story: str = Field(default="", max_length=400)


class PostCopy(BaseModel):
    instagram: str = Field(max_length=2200)
    pinterest: str = Field(max_length=500)
    pinterest_title: str = Field(max_length=100)
    facebook: str = Field(max_length=5000)
    tiktok: str = Field(max_length=2200)


class PlanEdit(PlanDates):
    revision: int = Field(ge=1)
    captions: PostCopy
    approved: bool = False


def plan_values(payload: PlanDates) -> tuple[str, str]:
    if payload.start_date > date.max - timedelta(days=PLATFORMS[-1][3]):
        raise HTTPException(status_code=400, detail="Choose an earlier start date.")
    url = payload.listing_url
    if url and (url.scheme != "https" or url.username is not None or url.password is not None):
        raise HTTPException(status_code=400, detail="Use an HTTPS listing link without sign-in details.")
    return payload.start_date.isoformat(), str(url) if url else ""


def starter_copy(title: str, collection: str, story: str, has_listing: bool) -> PostCopy:
    title = title.strip()[:120] or "Untitled artwork"
    series = collection.strip()[:100]
    if series == "Unsorted":
        series = ""
    note = story.strip()
    artwork = f"“{title}”"
    intro = f"{artwork} from my {series} collection" if series else artwork
    pin_call_to_action = "See the artwork listing." if has_listing else "Save for art inspiration."
    pin_intro = f"{intro}."
    pin_note = note[:500 - len(pin_intro) - len(pin_call_to_action) - 2].rstrip()
    return PostCopy(
        instagram="\n\n".join(filter(None, [
            f"A closer look at {artwork}.", note, "What detail catches your eye first?",
        ])),
        pinterest_title=f"{title} | {series or 'Black Canvas Art'}"[:100],
        pinterest=" ".join(filter(None, [pin_intro, pin_note, pin_call_to_action])),
        facebook="\n\n".join(filter(None, [
            f"I wanted to share {intro} with you.", note, "Let me know what you see in it.",
        ])),
        tiktok=f"Up close with {artwork}. Which detail made you stop scrolling?",
    )


def serialize_plan(plan: dict) -> dict:
    copy = json.loads(plan["posts"])
    start_date = date.fromisoformat(plan["start_date"])
    return {
        "id": plan["id"],
        "artwork_title": plan["artwork_title"],
        "artwork_id": plan["artwork_id"],
        "artwork_url": f"/uploads/{plan['artwork_filename']}" if plan["artwork_id"] else None,
        "start_date": plan["start_date"],
        "listing_url": plan["listing_url"],
        "approved": bool(plan["approved"]),
        "revision": plan["revision"],
        "posts": [
            {
                "platform": key,
                "label": label,
                "format": post_format,
                "date": (start_date + timedelta(days=offset)).isoformat(),
                "caption": copy[key],
                "title": copy["pinterest_title"] if key == "pinterest" else "",
            }
            for key, label, post_format, offset in PLATFORMS
        ],
    }


PLAN_QUERY = """
    SELECT p.*, (
        SELECT id FROM artworks WHERE filename = p.artwork_filename ORDER BY id LIMIT 1
    ) AS artwork_id
    FROM marketing_plans AS p
"""


@router.get("/marketing")
def marketing_page() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parent / "templates" / "marketing.html")


@router.get("/api/marketing/plans")
def list_plans() -> list[dict]:
    return [serialize_plan(plan) for plan in rows(PLAN_QUERY + " ORDER BY p.start_date DESC, p.id")]


@router.post("/api/marketing/plans", status_code=201)
def create_plan(payload: NewPlan) -> dict:
    start, link = plan_values(payload)
    plan_id = uuid4().hex
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        artwork = db.execute("SELECT * FROM artworks WHERE id = ?", (payload.artwork_id,)).fetchone()
        if artwork is None:
            raise HTTPException(status_code=404, detail="Artwork not found in Image Studio.")
        copy = starter_copy(artwork["title"], artwork["collection"], payload.story, bool(link))
        db.execute(
            "INSERT INTO marketing_plans(id, artwork_filename, artwork_title, start_date, listing_url, posts) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(artwork_filename, start_date) DO NOTHING",
            (plan_id, artwork["filename"], artwork["title"], start, link, copy.model_dump_json()),
        )
        plan = db.execute(PLAN_QUERY + " WHERE p.artwork_filename = ? AND p.start_date = ?",
                          (artwork["filename"], start)).fetchone()
    return serialize_plan(dict(plan))


@router.put("/api/marketing/plans/{plan_id}")
def update_plan(plan_id: str, payload: PlanEdit) -> dict:
    start, link = plan_values(payload)
    copy = {key: value.strip() for key, value in payload.captions.model_dump().items()}
    if payload.approved and not all(copy.values()):
        raise HTTPException(status_code=400, detail="Fill in every caption and the Pin title before approval.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        plan = db.execute("SELECT * FROM marketing_plans WHERE id = ?", (plan_id,)).fetchone()
        if plan is None:
            raise HTTPException(status_code=404, detail="This marketing plan was removed.")
        if plan["revision"] != payload.revision:
            raise HTTPException(status_code=409, detail="This plan was changed elsewhere. Refresh to review the latest copy.")
        conflict = db.execute(
            "SELECT 1 FROM marketing_plans WHERE artwork_filename = ? AND start_date = ? AND id != ?",
            (plan["artwork_filename"], start, plan_id),
        ).fetchone()
        if conflict:
            raise HTTPException(status_code=409, detail="This artwork already has a plan for that start date.")
        db.execute(
            "UPDATE marketing_plans SET start_date = ?, listing_url = ?, posts = ?, approved = ?, revision = revision + 1 "
            "WHERE id = ?",
            (start, link, json.dumps(copy), int(payload.approved), plan_id),
        )
        plan = db.execute(PLAN_QUERY + " WHERE p.id = ?", (plan_id,)).fetchone()
    return serialize_plan(dict(plan))
