import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, BaseModel, Field, HttpUrl

from buffer_client import BufferClient, BufferError, BufferRejected
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


class BufferPost(BaseModel):
    platform: Literal["facebook", "instagram", "pinterest", "tiktok"]
    channel_id: str
    due_at: AwareDatetime
    media_url: HttpUrl
    board_id: str = ""
    ai_generated: bool = False


class BufferSchedule(BaseModel):
    revision: int = Field(ge=1)
    organization_id: str
    posts: list[BufferPost] = Field(min_length=1, max_length=4)


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
        "buffer_posts": json.loads(plan["buffer_posts"]),
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
    ) AS artwork_id, (
        SELECT json_group_object(platform, json_object(
            'state', state, 'channel_name', channel_name, 'due_at', due_at, 'buffer_id', buffer_id
        )) FROM marketing_buffer_posts WHERE plan_id = p.id
    ) AS buffer_posts
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
        if db.execute("SELECT 1 FROM marketing_buffer_posts WHERE plan_id = ?", (plan_id,)).fetchone():
            raise HTTPException(status_code=409, detail="This week has Buffer submissions. Manage queued posts in Buffer.")
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


@router.get("/api/marketing/buffer")
def buffer_organizations() -> dict:
    client = BufferClient()
    if not client.api_key:
        return {"configured": False, "organizations": []}
    try:
        return {"configured": True, "organizations": client.organizations()}
    except (BufferError, KeyError, TypeError) as error:
        raise HTTPException(status_code=502, detail="Could not connect to Buffer. Check the server API key.") from error


def connected_channels(client: BufferClient, organization_id: str) -> list[dict]:
    if not client.api_key:
        raise HTTPException(status_code=503, detail="Set BUFFER_API_KEY on the Black Canvas AI server.")
    try:
        if not any(item["id"] == organization_id for item in client.organizations()):
            raise HTTPException(status_code=404, detail="Choose a workspace connected to Buffer.")
        return client.channels(organization_id)
    except (BufferError, KeyError, TypeError) as error:
        raise HTTPException(status_code=502, detail="Could not load the social accounts from Buffer.") from error


@router.get("/api/marketing/buffer/channels")
def buffer_channels(organization_id: str) -> list[dict]:
    return connected_channels(BufferClient(), organization_id)


def buffer_input(plan: dict, selection: BufferPost, channel: dict) -> dict:
    post = next(item for item in plan["posts"] if item["platform"] == selection.platform)
    url = selection.media_url
    if url.scheme != "https" or url.username is not None or url.password is not None:
        raise HTTPException(status_code=400, detail="Use a public HTTPS media link.")
    if selection.due_at.date().isoformat() != post["date"] or selection.due_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail=f"Choose a future time on the planned date for {post['label']}.")
    video = selection.platform in {"instagram", "tiktok"}
    listing = plan["listing_url"]
    text = post["caption"]
    result = {
        "channelId": channel["id"],
        "text": text,
        "mode": "customScheduled",
        "schedulingType": "automatic",
        "dueAt": selection.due_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "needsApproval": False,
        "assets": [{"video" if video else "image": {"url": str(url)}}],
    }
    if selection.platform == "pinterest":
        if not any(board["serviceId"] == selection.board_id for board in channel["boards"]):
            raise HTTPException(status_code=400, detail="Choose a board on the selected Pinterest account.")
        metadata = {"boardServiceId": selection.board_id, "title": post["title"]}
        if listing:
            metadata["url"] = listing
        result["metadata"] = {"pinterest": metadata}
    elif selection.platform == "facebook" and listing and listing not in text:
        result["text"] = f"{text}\n\n{listing}"
    elif selection.platform == "instagram":
        result["metadata"] = {"instagram": {
            "type": "reel", "shouldShareToFeed": True, "isAiGenerated": selection.ai_generated,
        }}
    elif selection.platform == "tiktok":
        result["metadata"] = {"tiktok": {"isAiGenerated": selection.ai_generated}}
    return result


@router.post("/api/marketing/plans/{plan_id}/buffer")
def schedule_in_buffer(plan_id: str, payload: BufferSchedule) -> dict:
    client = BufferClient()
    channels = {item["id"]: item for item in connected_channels(client, payload.organization_id)}
    platforms = [item.platform for item in payload.posts]
    if len(set(platforms)) != len(platforms):
        raise HTTPException(status_code=400, detail="Choose one account per platform for this week.")

    pending = []
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        record = db.execute(PLAN_QUERY + " WHERE p.id = ?", (plan_id,)).fetchone()
        if record is None:
            raise HTTPException(status_code=404, detail="This marketing plan was removed.")
        plan = serialize_plan(dict(record))
        if not plan["approved"] or plan["revision"] != payload.revision:
            raise HTTPException(status_code=409, detail="Refresh and approve the saved week before scheduling.")
        for selection in payload.posts:
            if selection.platform in plan["buffer_posts"]:
                continue
            channel = channels.get(selection.channel_id)
            if not channel or channel["platform"] != selection.platform:
                raise HTTPException(status_code=400, detail="Choose an active Buffer account for each selected platform.")
            post = buffer_input(plan, selection, channel)
            db.execute(
                "INSERT INTO marketing_buffer_posts(plan_id, platform, channel_name, due_at, state) "
                "VALUES (?, ?, ?, ?, 'unconfirmed')",
                (plan_id, selection.platform, channel["name"], post["dueAt"]),
            )
            pending.append((selection.platform, post))

    errors = {
        platform: "Check Buffer before retrying. The post may already be there."
        for platform in platforms
        if plan["buffer_posts"].get(platform, {}).get("state") == "unconfirmed"
    }
    for platform, post in pending:
        try:
            result = client.schedule(post)
        except BufferRejected as error:
            with connect() as db:
                db.execute("DELETE FROM marketing_buffer_posts WHERE plan_id = ? AND platform = ?", (plan_id, platform))
            errors[platform] = str(error)
            continue
        except (BufferError, KeyError, TypeError):
            errors[platform] = "Check Buffer before retrying. The post may already be there."
            continue
        with connect() as db:
            db.execute(
                "UPDATE marketing_buffer_posts SET state = ?, buffer_id = ? WHERE plan_id = ? AND platform = ?",
                (result.get("status") or "accepted", result["id"], plan_id, platform),
            )
    plan = rows(PLAN_QUERY + " WHERE p.id = ?", (plan_id,))[0]
    return {"plan": serialize_plan(plan), "errors": errors}
