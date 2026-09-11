import base64
import csv
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from urllib.parse import quote, urlencode

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel
from PIL import Image, ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from spellchecker import SpellChecker

from storage import DATA_DIR, UPLOAD_DIR, backup_data, connect, execute, initialize, rows

BASE_DIR = Path(__file__).resolve().parent
OPENAI_ENV_FILE = BASE_DIR / ".env"
OPENAI_MODEL = "gpt-5.6-luna"
OPENAI_MONTHLY_CALL_LIMIT = 250
OPENAI_LUNA_INPUT_PER_MILLION = 0.20
OPENAI_LUNA_OUTPUT_PER_MILLION = 1.20
PUBLIC_GALLERY_ONLY = os.environ.get("BLACKCANVAS_PUBLIC_GALLERY_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}


def is_likely_image_prompt(title: str, category: str, text: str) -> bool:
    """Identify visual-generation prompts without changing any imported records."""
    if category in {"AfroNova", "Quiet Nova", "GraffitiX"}:
        return True
    searchable = f"{title} {text}".lower()
    signals = (
        "image prompt", "generate an image", "create a portrait", "digital painting",
        "photorealistic", "illustration", "artwork", "visual composition", "midjourney",
        "dall-e", "dalle",
    )
    return any(signal in searchable for signal in signals)


initialize()
app = FastAPI(title="Black Canvas AI")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.middleware("http")
async def protect_public_gallery(request: Request, call_next):
    """When hosted as the public gallery, never expose private studio routes or original uploads."""
    path = request.url.path
    if PUBLIC_GALLERY_ONLY:
        if path == "/":
            return RedirectResponse("/gallery", status_code=307)
        public_route = (
            path in {"/gallery", "/inquire", "/api/health", "/favicon.ico"}
            or (path == "/api/gallery-settings" and request.method == "GET")
            or path.startswith("/static/")
            or path.startswith("/api/gallery-artworks")
            or path.startswith("/api/inquiry-artwork/")
            or (path == "/api/inquiries" and request.method == "POST")
            or (path == "/api/gallery-release-package" and request.method == "POST")
            or (path == "/api/gallery-release-settings" and request.method == "PUT")
        )
        if not public_route:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def dashboard_file() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "dashboard.html")


def openai_api_key() -> str:
    """Load the API key locally without ever returning it to the browser."""
    environment_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if environment_key:
        return environment_key
    if not OPENAI_ENV_FILE.exists():
        return ""
    for line in OPENAI_ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.partition("=")[2].strip().strip('"')
    return ""


def save_openai_api_key(api_key: str) -> None:
    """Keep the secret in the ignored local environment file, never in Git or SQLite."""
    lines = []
    if OPENAI_ENV_FILE.exists():
        lines = [line for line in OPENAI_ENV_FILE.read_text(encoding="utf-8").splitlines()
                 if not line.startswith("OPENAI_API_KEY=")]
    lines.append(f"OPENAI_API_KEY={api_key}")
    OPENAI_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["OPENAI_API_KEY"] = api_key


def openai_call_count() -> tuple[str, int]:
    current_month = datetime.now().strftime("%Y-%m")
    saved = rows("SELECT value FROM studio_settings WHERE key = 'openai_agent_usage'")
    if not saved:
        return current_month, 0
    try:
        usage = json.loads(saved[0]["value"])
    except (TypeError, json.JSONDecodeError):
        return current_month, 0
    if usage.get("month") != current_month:
        return current_month, 0
    return current_month, int(usage.get("calls", 0))


def response_usage(result: dict | None) -> tuple[int, int]:
    usage = (result or {}).get("usage") or {}
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)


def record_openai_call(activity_type: str = "Live Agent request", result: dict | None = None) -> None:
    """Count each request and retain a private, plain-language estimate for Jeffrey."""
    month, calls = openai_call_count()
    value = json.dumps({"month": month, "calls": calls + 1})
    input_tokens, output_tokens = response_usage(result)
    estimated_cost = (
        (input_tokens * OPENAI_LUNA_INPUT_PER_MILLION)
        + (output_tokens * OPENAI_LUNA_OUTPUT_PER_MILLION)
    ) / 1_000_000
    with connect() as db:
        db.execute(
            "INSERT INTO studio_settings(key, value) VALUES ('openai_agent_usage', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (value,),
        )
        db.execute(
            "INSERT INTO agent_activity(activity_type, model, input_tokens, output_tokens, estimated_cost) "
            "VALUES (?, ?, ?, ?, ?)",
            (activity_type, OPENAI_MODEL, input_tokens, output_tokens, estimated_cost),
        )


def studio_agent_instructions() -> str:
    return """You are Black Canvas Agent, Jeffrey McKay's skilled creative studio assistant.
Lead with the useful result, not a generic menu of possibilities. Be specific, warm, decisive,
and practical. Use the studio context and recent conversation when relevant, but never invent
facts that are not present. Give finished drafts, concrete recommendations, and ordered next actions
for creative direction, cataloging, pricing, gallery, content, and business work. If Jeffrey asks you
to make or write something, produce it now instead of telling him how he could produce it.
For image-generation prompts, output only the usable prompt itself: never begin with '/imagine prompt:',
never include Midjourney flags such as --ar, --raw, --style, --stylize, or --v, and do not add unsupported
generator settings. Preserve the requested subject and actual visual clues instead of replacing them with
a generic full-body character or unrelated collection language.
Do not claim to have performed web browsing, made purchases, contacted people, or changed anything outside
Black Canvas AI. You may recommend the best workspace action, but do not claim it already happened.
If a task needs a choice, make the strongest recommendation first and explain the tradeoff briefly."""


def openai_response_text(result: dict) -> str:
    """Extract text from the raw Responses API payload."""
    reply = str(result.get("output_text", "")).strip()
    if reply:
        return reply
    text_parts = []
    for item in result.get("output", []):
        for content in item.get("content", []) if isinstance(item, dict) else []:
            if content.get("type") == "output_text" and content.get("text"):
                text_parts.append(str(content["text"]))
    return "\n".join(text_parts).strip()


def agent_actions_for_request(message: str) -> list[dict[str, str]]:
    topic = message.lower()
    if any(word in topic for word in ("price", "pricing", "cost", "sell", "selling")):
        return [{"label": "Open unpriced artwork", "href": "/image-studio?focus=unpriced"}]
    if any(word in topic for word in ("organize", "review", "prompt library", "duplicate", "import", "google keep")):
        return [
            {"label": "Review Google Keep prompts", "href": "/prompts?review=keep"},
            {"label": "Open Prompt Library", "href": "/prompts"},
        ]
    if any(word in topic for word in ("style bible", "brand", "collection rules", "visual voice")):
        return [{"label": "Open Style Bible", "href": "/style-bible"}]
    if any(word in topic for word in ("listing", "product description", "product title", "seo")):
        return [{"label": "Open ready-to-list artwork", "href": "/image-studio?focus=ready"}]
    if any(word in topic for word in ("gallery", "website", "portfolio")):
        return [{"label": "Open Gallery Site", "href": "/gallery"}]
    if any(word in topic for word in ("order", "shipping", "tracking", "fulfillment")):
        return [{"label": "Open Orders Dashboard", "href": "/image-studio?focus=orders"}]
    return [
        {"label": "Open Image Studio", "href": "/image-studio"},
        {"label": "Open Prompt Library", "href": "/prompts"},
    ]


def relevant_studio_context(message: str, conversation_id: int | None = None) -> dict[str, object]:
    """Build compact, relevant context for the live agent without sending unrelated private records."""
    stop_words = {
        "about", "after", "again", "black", "canvas", "could", "from", "have", "help", "into",
        "just", "make", "need", "please", "that", "this", "what", "when", "where", "with", "would",
    }
    terms = {word for word in re.findall(r"[a-z0-9]+", message.lower()) if len(word) > 3 and word not in stop_words}

    def score(item: dict, fields: tuple[str, ...]) -> int:
        searchable = " ".join(str(item.get(field, "")) for field in fields).lower()
        return sum(1 for term in terms if term in searchable)

    prompt_rows = rows(
        "SELECT id, title, category, text, favorite, source FROM prompts "
        "ORDER BY favorite DESC, id DESC LIMIT 100"
    )
    ranked_prompts = sorted(
        prompt_rows,
        key=lambda item: (score(item, ("title", "category", "text")), item["favorite"], item["id"]),
        reverse=True,
    )
    relevant_prompts = [
        {
            "title": item["title"], "category": item["category"], "source": item["source"],
            "text": item["text"][:700],
        }
        for item in ranked_prompts[:4]
        if terms and score(item, ("title", "category", "text")) > 0
    ]

    artwork_rows = rows(
        "SELECT id, title, collection, tags, notes, dimensions, medium, price, sale_status "
        "FROM artworks ORDER BY id DESC LIMIT 100"
    )
    ranked_artworks = sorted(
        artwork_rows,
        key=lambda item: (score(item, ("title", "collection", "tags", "notes")), item["id"]),
        reverse=True,
    )
    relevant_artworks = [
        {
            "id": item["id"], "title": item["title"], "collection": item["collection"],
            "tags": item["tags"][:400], "notes": item["notes"][:700],
            "dimensions": item["dimensions"], "medium": item["medium"],
            "price": item["price"], "sale_status": item["sale_status"],
        }
        for item in ranked_artworks[:4]
        if terms and score(item, ("title", "collection", "tags", "notes")) > 0
    ]

    style_context = []
    for item in rows("SELECT name, content FROM styles ORDER BY name"):
        try:
            content = json.loads(item["content"])
        except (TypeError, json.JSONDecodeError):
            continue
        style_context.append({
            "name": item["name"],
            "statement": content.get("statement") or content.get("tagline") or "",
            "mood": list(content.get("mood") or [])[:4],
            "ingredients": list(content.get("ingredients") or [])[:5],
            "do": list(content.get("dos") or [])[:4],
            "avoid": list(content.get("donts") or [])[:4],
        })

    recent_conversation = []
    if conversation_id:
        recent_conversation = rows(
            "SELECT role, text FROM chat_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 8",
            (conversation_id,),
        )
        recent_conversation.reverse()
        recent_conversation = [
            {"role": item["role"], "text": item["text"][:1200]}
            for item in recent_conversation
        ]
        if recent_conversation and recent_conversation[-1]["role"] == "user" and recent_conversation[-1]["text"].strip() == message.strip():
            recent_conversation.pop()

    studio = dashboard_summary()
    return {
        "summary": {
            "artworks": studio["counts"]["artworks"],
            "prompts": studio["counts"]["prompts"],
            "prompts_to_review": studio["counts"]["to_review"],
            "ready_to_list": studio["studio"]["ready_to_list"],
            "active_orders": studio["studio"]["active_orders"],
            "catalog_value": studio["studio"]["catalog_value"],
        },
        "relevant_artworks": relevant_artworks,
        "relevant_prompts": relevant_prompts,
        "style_bible": style_context,
        "recent_conversation": recent_conversation,
    }


def live_agent_reply(message: str, conversation_id: int | None = None) -> dict[str, object] | None:
    """Use the Responses API when Jeffrey has connected a local key; otherwise use local tools."""
    api_key = openai_api_key()
    if not api_key:
        return None
    _, calls = openai_call_count()
    if calls >= OPENAI_MONTHLY_CALL_LIMIT:
        return {
            "reply": (
                "**Live Agent safety pause**\n\n"
                "This month’s Black Canvas AI limit of 250 live requests has been reached. "
                "The local creative tools are still available, and the limit will reset next month."
            )
        }
    studio_context = relevant_studio_context(message, conversation_id)
    request_body = {
        "model": OPENAI_MODEL,
        "instructions": studio_agent_instructions(),
        "input": (
            "Relevant Black Canvas AI workspace context: " + json.dumps(studio_context) + "\n\n"
            "Jeffrey's request: " + message
        ),
        "max_output_tokens": 900,
    }
    request = UrlRequest(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Live Agent could not respond: {detail[:200]}")
    except URLError:
        raise HTTPException(status_code=502, detail="Live Agent could not reach OpenAI. Please try again.")
    reply = openai_response_text(result)
    if not reply:
        raise HTTPException(status_code=502, detail="Live Agent returned an empty reply. Please try again.")
    record_openai_call("Creative chat", result)
    return {"reply": reply, "live_agent": True, "actions": agent_actions_for_request(message)}


def safe_live_agent_reply(message: str, conversation_id: int | None = None) -> dict[str, object] | None:
    """Fall back to the local agent instead of showing a dead-end error when the API is briefly unavailable."""
    try:
        return live_agent_reply(message, conversation_id)
    except HTTPException:
        return None


class ChatMessage(BaseModel):
    message: str
    conversation_id: int | None = None


class OpenAIApiKeyPayload(BaseModel):
    api_key: str


class ConversationPayload(BaseModel):
    title: str = "New conversation"


class ConversationRenamePayload(BaseModel):
    title: str


class ConversationMessagePayload(BaseModel):
    role: str
    text: str
    metadata: dict = {}


class PromptPayload(BaseModel):
    title: str
    category: str
    text: str
    favorite: bool = False


class PromptBulkPayload(BaseModel):
    prompt_ids: list[int]
    category: str | None = None
    reviewed: bool | None = None


class InquiryPayload(BaseModel):
    artwork_id: int | None = None
    inquiry_type: str = "Artwork inquiry"
    name: str
    email: str
    message: str
    budget: str = ""


class ArtworkBulkPayload(BaseModel):
    artwork_ids: list[int]
    collection: str | None = None
    medium: str | None = None
    sale_status: str | None = None
    gallery_visible: bool | None = None
    add_tags: str = ""


class StylePayload(BaseModel):
    content: dict


class StyleUpdatePayload(BaseModel):
    style_name: str
    text: str


class StyleUpdateDecision(BaseModel):
    suggestions: dict[str, list[str]]


class SpellCheckPayload(BaseModel):
    text: str


class PromptRefinePayload(BaseModel):
    prompt: str
    category: str
    mode: str


class ArtworkPayload(BaseModel):
    title: str
    collection: str
    tags: str = ""
    notes: str = ""
    favorite: bool = False
    dimensions: str = ""
    medium: str = ""
    price: float = 0
    sale_status: str = "In progress"
    gallery_visible: bool = False
    listing_url: str = ""
    data_url: str


class ArtworkDetailsPayload(BaseModel):
    title: str
    collection: str
    tags: str = ""
    notes: str = ""
    dimensions: str = ""
    medium: str = ""
    price: float = 0
    sale_status: str = "In progress"
    gallery_visible: bool = False
    listing_url: str = ""


class GallerySettingsPayload(BaseModel):
    artist_name: str = "Jeffrey McKay"
    intro: str = "Black Canvas is a living archive of color, story, texture, and Black imagination."
    shop_url: str = ""
    etsy_url: str = ""
    pinterest_url: str = ""
    instagram_url: str = ""
    contact_email: str = ""


class PrintExportPayload(BaseModel):
    width_inches: float
    height_inches: float


class SaleRecordPayload(BaseModel):
    sale_price: float
    sold_date: str
    sales_channel: str
    buyer_name: str = ""
    notes: str = ""


class FulfillmentPayload(BaseModel):
    status: str
    carrier: str = ""
    tracking_number: str = ""


class ExpensePayload(BaseModel):
    description: str
    category: str
    amount: float
    expense_date: str
    notes: str = ""


class RevenueGoalPayload(BaseModel):
    monthly_goal: float


class ArtworkPricePayload(BaseModel):
    price: float


class ArtworkPricingPayload(BaseModel):
    materials: float
    hours: float
    hourly_rate: float
    overhead: float
    fees_percent: float
    profit_percent: float
    recommended_price: float


class GoogleCredentialsPayload(BaseModel):
    credentials: dict


class GoogleClientPayload(BaseModel):
    client_id: str
    client_secret: str


class ChatGPTImportPayload(BaseModel):
    candidate_ids: list[str]


class DriveArtworkPayload(BaseModel):
    title: str
    collection: str = "Unsorted"
    tags: str = ""
    notes: str = ""


class GooglePhotosImportPayload(DriveArtworkPayload):
    session_id: str
    photo_id: str


def clean_image_idea(message: str) -> str:
    idea = message.strip().rstrip(".?!")
    patterns = [
        r"^(?:can|could|will|would)\s+(?:we|you)\s+(?:write|create|make|generate)\s+(?:me\s+)?(?:an?\s+)?(?:image\s+)?prompt\s+(?:for|of|about)\s+",
        r"^(?:please\s+)?(?:write|create|make|generate)\s+(?:me\s+)?(?:an?\s+)?(?:image\s+)?prompt\s+(?:for|of|about)?\s*",
        r"^(?:please\s+)?(?:create|make|generate)\s+(?:me\s+)?(?:an?\s+)?(?:portrait|painting|photograph|photo|artwork|image)\s+(?:for|of|about)\s+",
        r"^(?:i\s+(?:want|need)\s+)(?:an?\s+)?(?:image\s+)?prompt\s+(?:for|of|about)?\s*",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", idea, flags=re.IGNORECASE).strip()
        if cleaned != idea:
            idea = cleaned
            break
    idea = re.sub(r"\b(a)\s+(african)\b", r"an \2", idea, flags=re.IGNORECASE)
    simple_style = re.sub(r"[^a-z]", "", idea.lower())
    if simple_style in ("afronova", "afronovastyle"):
        idea = "a regal Black visionary in the AfroNova style"
    elif simple_style in ("quietnova", "quietnovastyle"):
        idea = "a contemplative Black figure in the Quiet Nova style"
    elif simple_style in ("graffitix", "graffitixstyle"):
        idea = "an expressive Black urban creator in the GraffitiX style"
    return idea or message.strip()


def prompt_collection(idea: str) -> tuple[str, str, str, str]:
    lowered = idea.lower()
    if "afro nova" in lowered or "afronova" in lowered:
        return ("AfroNova", "deep violet, midnight blue, luminous gold, and rich earth tones",
                "Afrofuturist elegance, celestial symbolism, intricate textile detail, and regal visual language",
                "powerful, visionary, dignified")
    if "quiet nova" in lowered:
        return ("Quiet Nova", "warm earth tones, soft cream, muted blue, and restrained gold",
                "subtle tactile texture, generous negative space, and softly rendered details",
                "intimate, grounded, contemplative")
    if "graffitix" in lowered or "graffiti x" in lowered:
        return ("GraffitiX", "electric magenta, cyan, black, and flashes of gold",
                "layered spray-paint marks, torn-paper textures, expressive urban energy, and a restrained symbolic vocabulary of hand-drawn 444 numerals, crowns, skulls, X-eyes, crude diamonds, primitive pyramids, cryptic writing, crossed-out phrases, ledger marks, and loose scribbles; organize the composition around one main subject, one hero symbol, one or two supporting symbols, then secondary background writing",
                "bold, rebellious, kinetic")
    if any(word in lowered for word in ("graffiti", "street", "urban", "neon", "city", "hip-hop")):
        return ("GraffitiX", "electric magenta, cyan, black, and flashes of gold",
                "layered spray-paint marks, torn-paper textures, expressive urban energy, and a restrained symbolic vocabulary of hand-drawn 444 numerals, crowns, skulls, X-eyes, crude diamonds, primitive pyramids, cryptic writing, crossed-out phrases, ledger marks, and loose scribbles; organize the composition around one main subject, one hero symbol, one or two supporting symbols, then secondary background writing",
                "bold, rebellious, kinetic")
    if any(word in lowered for word in ("quiet", "calm", "peaceful", "soft", "gentle", "reflective", "morning")):
        return ("Quiet Nova", "warm earth tones, soft cream, muted blue, and restrained gold",
                "subtle tactile texture, generous negative space, and softly rendered details",
                "intimate, grounded, contemplative")
    return ("AfroNova", "deep violet, midnight blue, luminous gold, and rich earth tones",
            "Afrofuturist elegance, celestial symbolism, intricate textile detail, and regal visual language",
            "powerful, visionary, dignified")


def saved_style_direction(collection: str, palette: str, style: str, mood: str) -> tuple[str, str, str, str]:
    """Blend the creator's current Style Bible into locally generated prompts."""
    with connect() as db:
        row = db.execute("SELECT content FROM styles WHERE name = ?", (collection,)).fetchone()
    if not row:
        return palette, style, mood, ""
    try:
        content = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return palette, style, mood, ""

    colors = [str(value).strip() for value in content.get("colors", []) if str(value).strip()]
    ingredients = [str(value).strip() for value in content.get("ingredients", []) if str(value).strip()]
    language = [str(value).strip() for value in content.get("language", []) if str(value).strip()]
    moods = [str(value).strip() for value in content.get("mood", []) if str(value).strip()]
    dos = [str(value).strip() for value in content.get("dos", []) if str(value).strip()]
    donts = [str(value).strip() for value in content.get("donts", []) if str(value).strip()]

    if colors:
        palette = ", ".join(colors)
    if moods:
        mood = ", ".join(moods)
    direction_parts = ingredients + language + dos
    if direction_parts:
        style = "; ".join(direction_parts)
    avoid = "; avoid " + ", ".join(donts) if donts else ""
    return palette, style, mood, avoid


def create_image_prompt(message: str) -> tuple[str, str]:
    idea = clean_image_idea(message)
    collection, palette, style, mood = prompt_collection(idea)
    palette, style, mood, avoid = saved_style_direction(collection, palette, style, mood)
    lowered = idea.lower()
    artwork_reference = "visual details:" in lowered or "use this creative direction:" in lowered
    if artwork_reference:
        title_match = re.search(r"image prompt for\s+(.+?)\s+in the\s+(?:AfroNova|Quiet Nova|GraffitiX)\s+style", message, flags=re.IGNORECASE)
        notes_match = re.search(r"use this creative direction:\s*(.+?)(?:\.\s*visual details:|$)", message, flags=re.IGNORECASE | re.DOTALL)
        tags_match = re.search(r"visual details:\s*(.+?)\s*$", message, flags=re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else "the source artwork"
        source_notes = notes_match.group(1).strip() if notes_match else ""
        source_tags = tags_match.group(1).strip() if tags_match else ""
        source_direction = ". ".join(part for part in (source_notes, source_tags) if part) or title
        prompt = (
            f"{collection} fine-art reinterpretation of {title}. Preserve the actual source concept and visual cues: "
            f"{source_direction}. Keep the composition focused on the described subject, form, expression, and mood; "
            "if the source is a face, mask, monster head, or close portrait, keep it a close portrait rather than inventing a full body. "
            f"Use {style}. Use a refined palette of {palette}, tactile materials, cinematic directional lighting, "
            f"strong focal hierarchy, and a {mood} emotional charge. Do not add unrelated clothing, a standing pose, "
            "or unrelated characters unless they are specifically part of the source description. "
            "Museum-quality contemporary artwork with a handmade, expressive finish."
        )
        return collection, prompt
    subject = re.split(r"\s+in\s+the\s+(?:AfroNova|Quiet Nova|GraffitiX)\s+style", idea, maxsplit=1, flags=re.IGNORECASE)[0]
    requested_mood = re.search(r"with\s+(?:an?\s+)?(.+?)\s+mood", idea, flags=re.IGNORECASE)
    requested_colors = re.search(r"using\s+(.+?),\s+as\s+", idea, flags=re.IGNORECASE)
    requested_pose = re.search(r"(?:^|[.;])\s*pose\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_camera = re.search(r"(?:^|[.;])\s*camera\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_hero = re.search(r"(?:^|[.;])\s*hero symbol\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    if requested_mood:
        mood = requested_mood.group(1).strip()
    if requested_colors and "collection color palette" not in requested_colors.group(1).lower():
        palette = requested_colors.group(1).strip()
    if "photorealistic" in lowered or "photograph" in lowered:
        medium = "cinematic photorealistic portrait photography"
    elif "acrylic" in lowered:
        medium = "museum-quality acrylic painting on textured canvas"
    elif "editorial fashion" in lowered:
        medium = "high-fashion editorial portrait photography"
    elif "graphic poster" in lowered:
        medium = "bold contemporary graphic poster art"
    else:
        medium = "museum-quality fine-art digital painting with painterly realism"
    safety = " age-appropriate styling and a dignified, authentic expression," if any(
        word in subject.lower() for word in ("child", "boy", "girl", "kid", "baby")
    ) else ""
    if collection == "GraffitiX":
        pose_direction = requested_pose.group(1).strip() if requested_pose else (
            "a grounded pose with a planted foot, weight shift, bent joints, hip angle, shoulder counter-rotation, "
            "torso twist, and a readable S-curve, Z-curve, or spiral line of action"
        )
        camera_direction = requested_camera.group(1).strip() if requested_camera else (
            "a deliberate low-angle three-quarter, pavement tracking, high Dutch-angle, or eye-level camera view"
        )
        hero_symbol = requested_hero.group(1).strip() if requested_hero else "a rough-painted 444, crown, skull, X-eye, or nova glyph"
        prompt = (
            f"Full-body {subject},{safety} presented as the unmistakable focal subject. "
            f"Engineer {pose_direction}. Use {camera_direction}, keeping the silhouette immediately readable. "
            "Build authentic 1990s streetwear with construction detail: oversized pleated chinos, stacked ankles, "
            "pocket tee or cropped tank, open flannel or vintage windbreaker, bandana or snapback, and retro sneakers. "
            f"Establish one dominant hero symbol—{hero_symbol}; use only one or two small supporting symbols, then restrained background writing. "
            "Render raw Black Canvas / 444 GraffitiX mixed-media fine art: heavy oil stick, oil pastel, dripping acrylic, "
            "impasto, aerosol haze, charcoal, chalk, scratches, collage, and exposed canvas. "
            f"Use {palette}, stark graphic directional lighting, brutal contrast, irregular hand-drawn edges, tactile matte surfaces, "
            f"and a {mood} emotional charge. Keep the figure emotionally present and dominant over every mark. "
            "Museum-quality contemporary urban artwork with a raw, tactile, handmade finish."
        )
        return collection, prompt
    prompt = (
        f"Create {medium} of {subject},{safety} presented as the unmistakable focal subject. "
        f"Use a balanced three-quarter composition at eye level, with confident posture, expressive eyes, "
        f"and carefully observed facial features. Build the visual direction around {style}. "
        f"Illuminate the subject with soft directional key light and a subtle luminous rim light, creating "
        f"dimensional skin tones, controlled highlights, and rich shadow detail. Use a refined palette of "
        f"{palette}. Place the subject against an atmospheric, story-rich background that supports the idea "
        f"without competing with the face. The mood is {mood}. Include believable materials, finely rendered "
        f"fabric and accessories, natural depth of field, sophisticated color grading, crisp focal detail, "
        f"gallery-ready composition, ultra-detailed, cohesive, emotionally resonant{avoid}."
    )
    return collection, prompt


def clean_copy_ready_prompt(prompt: str) -> str:
    """Remove legacy Midjourney labels and parameters from prompts before reuse."""
    cleaned = re.sub(r"(?:^|\n)\s*/imagine\s+prompt\s*:\s*", "\n", prompt, flags=re.IGNORECASE)
    legacy_graffitix_tail = (
        r"Museum-quality contemporary urban artwork, no digital smoothness, no glossy CGI finish, "
        r"no polished 3D render, no clean vector edges, no random decorative symbols, "
        r"no cluttered focal hierarchy, no text, no watermark, no signature, no logo, no frame"
    )
    cleaned = re.sub(
        legacy_graffitix_tail,
        "Museum-quality contemporary urban artwork with a raw, tactile, handmade finish.",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+no text, no watermark, no signature, no logo, no frame", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+--ar\s+\d+:\d+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+--raw\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+--style\s+\S+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+--stylize\s+\d+(?:\.\d+)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+--q\s+\d+(?:\.\d+)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+--v\s*\d+(?:\.\d+)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+--(?:sref|seed|chaos|weird)\s+\S+", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


@app.get("/")
def home() -> FileResponse:
    return dashboard_file()


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return dashboard_file()


@app.get("/chat")
def chat() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "chat.html")


@app.get("/agent-activity")
def agent_activity_page() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "agent-activity.html")


@app.get("/prompts")
def prompts() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "prompts.html")


@app.get("/image-studio")
def image_studio() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "image-studio.html")


@app.get("/style-bible")
def style_bible() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "style-bible.html")


@app.get("/gallery")
def gallery() -> FileResponse:
    """A public-facing gallery preview, kept separate from the studio tools."""
    return FileResponse(
        BASE_DIR / "templates" / "gallery.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    """Small public-safe health check for the hosting provider."""
    return {"status": "ok", "mode": "public-gallery" if PUBLIC_GALLERY_ONLY else "studio"}


@app.get("/inquire")
def inquire() -> FileResponse:
    """Public collector and commission inquiry form."""
    return FileResponse(
        BASE_DIR / "templates" / "inquire.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/inquiry-artwork/{artwork_id}")
def inquiry_artwork(artwork_id: int) -> dict[str, object]:
    matches = rows(
        "SELECT id, title, collection FROM artworks WHERE id = ? AND gallery_visible = 1",
        (artwork_id,),
    )
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    return matches[0]


@app.post("/api/inquiries")
def create_inquiry(payload: InquiryPayload) -> dict[str, object]:
    name = re.sub(r"\s+", " ", payload.name).strip()[:100]
    email = payload.email.strip().lower()[:254]
    message = payload.message.strip()[:3000]
    inquiry_type = re.sub(r"\s+", " ", payload.inquiry_type).strip()[:80] or "Artwork inquiry"
    budget = re.sub(r"\s+", " ", payload.budget).strip()[:120]
    if len(name) < 2 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(message) < 8:
        raise HTTPException(status_code=400, detail="Please add your name, a valid email, and a short message.")
    artwork_id = payload.artwork_id
    if artwork_id is not None:
        artwork = rows("SELECT id FROM artworks WHERE id = ? AND gallery_visible = 1", (artwork_id,))
        if not artwork:
            artwork_id = None
    inquiry_id = execute(
        "INSERT INTO inquiries(artwork_id, inquiry_type, name, email, message, budget) VALUES (?, ?, ?, ?, ?, ?)",
        (artwork_id, inquiry_type, name, email, message, budget),
    )
    return {"id": inquiry_id, "message": "Thank you—your inquiry has been received by Jeffrey's studio."}


@app.get("/api/inquiries")
def list_inquiries() -> list[dict[str, object]]:
    return rows(
        "SELECT i.id, i.artwork_id, i.inquiry_type, i.name, i.email, i.message, i.budget, i.status, i.created_at, "
        "COALESCE(a.title, '') AS artwork_title FROM inquiries i LEFT JOIN artworks a ON a.id = i.artwork_id "
        "ORDER BY CASE i.status WHEN 'New' THEN 0 ELSE 1 END, i.id DESC"
    )


@app.get("/api/gallery-settings")
def get_gallery_settings() -> dict[str, str | bool]:
    defaults = GallerySettingsPayload().model_dump()
    with connect() as db:
        setting = db.execute("SELECT value FROM studio_settings WHERE key = 'gallery_settings'").fetchone()
    if not setting:
        return {**defaults, "public_mode": PUBLIC_GALLERY_ONLY}
    try:
        saved = json.loads(setting["value"])
    except json.JSONDecodeError:
        return {**defaults, "public_mode": PUBLIC_GALLERY_ONLY}
    return {**{key: str(saved.get(key, value)) for key, value in defaults.items()}, "public_mode": PUBLIC_GALLERY_ONLY}


@app.get("/api/gallery-release-package")
def download_gallery_release_package() -> FileResponse:
    """Create a package containing only visitor-safe artwork and gallery settings."""
    if PUBLIC_GALLERY_ONLY:
        raise HTTPException(status_code=404, detail="Not found")
    visible = rows(
        "SELECT title, collection, tags, notes, favorite, dimensions, medium, price, sale_status, gallery_visible, listing_url, filename "
        "FROM artworks WHERE gallery_visible = 1 AND sale_status NOT IN ('Sold', 'Not for sale') ORDER BY id DESC"
    )
    settings = get_gallery_settings()
    settings.pop("public_mode", None)
    release_dir = DATA_DIR / "gallery-releases"
    release_dir.mkdir(parents=True, exist_ok=True)
    package_path = release_dir / "black-canvas-gallery-release.zip"
    manifest = {
        "version": 1,
        "gallery_settings": settings,
        "artworks": [dict(item) for item in visible],
    }
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("gallery.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for item in visible:
            filename = Path(str(item["filename"])).name
            image_path = UPLOAD_DIR / filename
            if image_path.is_file():
                package.write(image_path, f"images/{filename}")
    return FileResponse(package_path, media_type="application/zip", filename=package_path.name)


@app.post("/api/gallery-release-package")
async def install_gallery_release_package(request: Request, package: UploadFile = File(...)) -> dict[str, int]:
    """Install a gallery-only package on the public host, protected by a one-time secret."""
    if not PUBLIC_GALLERY_ONLY:
        raise HTTPException(status_code=404, detail="Not found")
    release_token = os.environ.get("BLACKCANVAS_RELEASE_TOKEN", "").strip()
    provided_token = request.headers.get("x-blackcanvas-release-token", "")
    if not release_token or not secrets.compare_digest(provided_token, release_token):
        raise HTTPException(status_code=403, detail="Release authorization is required")
    package.file.seek(0, os.SEEK_END)
    package_size = package.file.tell()
    package.file.seek(0)
    if package_size > 500 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The gallery release package is too large")
    try:
        with zipfile.ZipFile(package.file) as archive:
            manifest = json.loads(archive.read("gallery.json"))
            artworks = manifest.get("artworks", [])
            settings = manifest.get("gallery_settings", {})
            if not isinstance(artworks, list) or len(artworks) > 500 or not isinstance(settings, dict):
                raise ValueError("Invalid gallery release package")
            filenames: set[str] = set()
            for artwork in artworks:
                filename = Path(str(artwork.get("filename", ""))).name
                if not filename or filename != artwork.get("filename") or filename in filenames:
                    raise ValueError("Invalid artwork filename")
                filenames.add(filename)
                image_info = archive.getinfo(f"images/{filename}")
                if image_info.file_size <= 0 or image_info.file_size > 25 * 1024 * 1024:
                    raise ValueError("Invalid artwork image")
    except (KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="That gallery release package could not be read") from error

    for image_path in UPLOAD_DIR.iterdir():
        if image_path.is_file():
            image_path.unlink()
    with zipfile.ZipFile(package.file) as archive, connect() as db:
        db.execute("DELETE FROM artworks")
        for artwork in artworks:
            filename = Path(str(artwork["filename"])).name
            (UPLOAD_DIR / filename).write_bytes(archive.read(f"images/{filename}"))
            db.execute(
                "INSERT INTO artworks(title, collection, tags, notes, favorite, dimensions, medium, price, sale_status, gallery_visible, listing_url, filename) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    str(artwork.get("title", "Untitled work")).strip() or "Untitled work",
                    str(artwork.get("collection", "Unsorted")).strip() or "Unsorted",
                    str(artwork.get("tags", "")).strip(), str(artwork.get("notes", "")).strip(),
                    int(bool(artwork.get("favorite"))), str(artwork.get("dimensions", "")).strip(),
                    str(artwork.get("medium", "")).strip(), max(float(artwork.get("price", 0) or 0), 0),
                    str(artwork.get("sale_status", "In progress")).strip() or "In progress",
                    str(artwork.get("listing_url", "")).strip(), filename,
                ),
            )
        db.execute(
            "INSERT INTO studio_settings(key, value) VALUES ('gallery_settings', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps({key: str(settings.get(key, value)) for key, value in GallerySettingsPayload().model_dump().items()}),),
        )
    return {"artworks": len(artworks)}


@app.put("/api/gallery-settings")
def update_gallery_settings(payload: GallerySettingsPayload) -> dict[str, str]:
    settings = {key: value.strip() for key, value in payload.model_dump().items()}
    for key in ("shop_url", "etsy_url", "pinterest_url", "instagram_url"):
        if settings[key] and not re.match(r"https?://", settings[key], re.IGNORECASE):
            raise HTTPException(status_code=400, detail="Links need to begin with https://")
    if settings["contact_email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", settings["contact_email"]):
        raise HTTPException(status_code=400, detail="Please enter a valid contact email")
    with connect() as db:
        db.execute(
            "INSERT INTO studio_settings(key, value) VALUES ('gallery_settings', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(settings),),
        )
    return settings


@app.put("/api/gallery-release-settings")
def update_public_gallery_settings(request: Request, payload: GallerySettingsPayload) -> dict[str, str]:
    """Update public-facing links without re-uploading the artwork package."""
    if not PUBLIC_GALLERY_ONLY:
        raise HTTPException(status_code=404, detail="Not found")
    release_token = os.environ.get("BLACKCANVAS_RELEASE_TOKEN", "").strip()
    provided_token = request.headers.get("x-blackcanvas-release-token", "")
    if not release_token or not secrets.compare_digest(provided_token, release_token):
        raise HTTPException(status_code=403, detail="Release authorization is required")
    return update_gallery_settings(payload)


@app.get("/connections")
def connections() -> FileResponse:
    return FileResponse(
        BASE_DIR / "templates" / "connections.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/openai/status")
def openai_status() -> dict[str, object]:
    _, calls = openai_call_count()
    return {
        "connected": bool(openai_api_key()),
        "model": OPENAI_MODEL,
        "calls_used": calls,
        "calls_limit": OPENAI_MONTHLY_CALL_LIMIT,
    }


@app.get("/api/agent-activity")
def agent_activity() -> dict[str, object]:
    """Private usage log. Estimates are helpful guidance; the Platform invoice remains authoritative."""
    current_month, total_calls = openai_call_count()
    with connect() as db:
        activity = [dict(item) for item in db.execute(
            "SELECT id, activity_type, model, input_tokens, output_tokens, estimated_cost, status, created_at "
            "FROM agent_activity WHERE substr(created_at, 1, 7) = ? ORDER BY id DESC LIMIT 100",
            (current_month,),
        ).fetchall()]
    estimated_cost = round(sum(float(item["estimated_cost"] or 0) for item in activity), 4)
    return {
        "month": current_month,
        "model": OPENAI_MODEL,
        "calls_used": total_calls,
        "calls_limit": OPENAI_MONTHLY_CALL_LIMIT,
        "logged_calls": len(activity),
        "earlier_unlogged_calls": max(total_calls - len(activity), 0),
        "estimated_cost": estimated_cost,
        "activity": activity,
    }


@app.post("/api/openai/key")
def connect_openai_agent(payload: OpenAIApiKeyPayload) -> dict[str, object]:
    api_key = payload.api_key.strip()
    if not api_key.startswith("sk-") or len(api_key) < 20:
        raise HTTPException(status_code=400, detail="That does not look like an OpenAI API key.")
    save_openai_api_key(api_key)
    return {"connected": True, "message": "Live Agent key saved locally."}


def image_prompt_chat_response(topic: str) -> dict[str, object]:
    collection, prompt = create_image_prompt(topic)
    idea = clean_image_idea(topic)
    title = re.sub(r"\s+", " ", idea).strip().title()[:70] or "Generated Image Prompt"
    return {
        "reply": (
            f"**{collection} creative direction**\n\n{prompt}\n\n"
            f"This uses your current {collection} Style Bible rules. You can copy it into your image "
            "generator. It was created locally, so it did not use a paid AI key."
        ),
        "generated_prompt": prompt,
        "prompt_title": title,
        "prompt_category": collection,
    }


def save_generated_prompt(result: dict[str, object]) -> dict[str, object]:
    """Keep agent-created image prompts in the library without asking Jeffrey to save a second time."""
    prompt = clean_copy_ready_prompt(str(result.get("generated_prompt") or ""))
    if not prompt:
        return result
    title = re.sub(r"\s+", " ", str(result.get("prompt_title") or "Generated Image Prompt")).strip()[:120]
    category = str(result.get("prompt_category") or "Unsorted").strip()[:60] or "Unsorted"
    with connect() as db:
        existing = db.execute("SELECT id FROM prompts WHERE text = ? LIMIT 1", (prompt,)).fetchone()
        if existing:
            prompt_id = existing["id"]
            save_status = "already_saved"
        else:
            cursor = db.execute(
                "INSERT INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, ?, ?, 0, 'agent', 1)",
                (title, category, prompt),
            )
            prompt_id = cursor.lastrowid
            save_status = "saved"
    result.update({
        "generated_prompt": prompt,
        "prompt_title": title,
        "prompt_category": category,
        "prompt_saved": True,
        "prompt_save_status": save_status,
        "prompt_id": prompt_id,
    })
    return result


def looks_like_prompt_build_request(message: str) -> bool:
    """Recognize the everyday ways Jeffrey asks the agent to make an image prompt."""
    text = message.lower()
    asks_to_make = bool(re.search(r"\b(create|generate|make|build|write|rewrite|refine|remix|develop|design)\b", text))
    mentions_prompt = bool(re.search(r"\b(prompt|midjourney|image|portrait|painting|artwork)\b", text))
    return asks_to_make and mentions_prompt


def chat_prompt_title(request: str, fallback: str = "Saved Black Canvas Prompt") -> str:
    idea = clean_image_idea(request)
    title = re.sub(r"\s+", " ", idea).strip().title()[:90]
    return title or fallback


def recover_chat_prompts() -> dict[str, int]:
    """Bring prior genuine prompt replies from the local Black Canvas chat into the library once."""
    imported = 0
    checked = 0
    rejected_openers = (
        "i can't", "i cannot", "the saved draft is missing", "upload the reference",
        "**black canvas agent brief", "**black canvas pricing direction",
    )
    with connect() as db:
        messages = db.execute(
            "SELECT m.conversation_id, m.role, m.text, c.title FROM chat_messages m "
            "JOIN conversations c ON c.id = m.conversation_id ORDER BY m.conversation_id, m.id"
        ).fetchall()
        latest_request: dict[int, str] = {}
        for message in messages:
            text = str(message["text"] or "").strip()
            if message["role"] == "user":
                latest_request[message["conversation_id"]] = text
                continue
            if message["role"] != "assistant" or len(text) < 120:
                continue
            request = latest_request.get(message["conversation_id"], "")
            conversation_title = str(message["title"] or "")
            context = f"{conversation_title} {request}"
            if not looks_like_prompt_build_request(context):
                continue
            if text.lower().startswith(rejected_openers):
                continue
            checked += 1
            category = prompt_collection(context)[0]
            title = chat_prompt_title(request or conversation_title)
            cursor = db.execute(
                "INSERT OR IGNORE INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, ?, ?, 0, 'agent', 1)",
                (title, category, clean_copy_ready_prompt(text)),
            )
            imported += max(cursor.rowcount, 0)
    return {"checked": checked, "imported": imported}


@app.post("/api/chat")
def chat_reply(payload: ChatMessage) -> dict[str, object]:
    topic = payload.message.strip()
    topic_lower = topic.lower()
    explicit_image_prompt = "image prompt" in topic_lower or looks_like_prompt_build_request(topic)
    if explicit_image_prompt:
        live_reply = safe_live_agent_reply(topic, payload.conversation_id)
        if live_reply:
            collection, _ = create_image_prompt(topic)
            live_reply.update({
                "generated_prompt": clean_copy_ready_prompt(str(live_reply["reply"])),
                "prompt_title": (re.sub(r"\s+", " ", clean_image_idea(topic)).strip().title()[:70]
                                 or "Generated Image Prompt"),
                "prompt_category": collection,
            })
            return save_generated_prompt(live_reply)
        return save_generated_prompt(image_prompt_chat_response(topic))
    live_reply = safe_live_agent_reply(topic, payload.conversation_id)
    if live_reply:
        return live_reply
    studio = dashboard_summary()
    studio_data = studio["studio"]
    if any(word in topic_lower for word in ("price", "pricing", "cost", "sell", "selling", "etsy", "marketplace")):
        return {
            "reply": (
                "**Black Canvas pricing direction**\n\n"
                f"You currently have **{studio_data['ready_to_list']}** pieces marked Ready to List and "
                f"**{studio_data['catalog_value']:,.0f}** in available catalog value.\n\n"
                "For one artwork, use this order:\n"
                "- Start with your material, printing, and packaging costs.\n"
                "- Add time, complexity, size, and the collection’s position.\n"
                "- Compare the final number to your intended buyer and sales channel.\n\n"
                "Open **Image Studio**, select the artwork, and use the Pricing Calculator before publishing."
            ),
            "actions": [{"label": "Open unpriced artwork", "href": "/image-studio?focus=unpriced"}]
        }
    if any(phrase in topic_lower for phrase in ("content calendar", "content plan", "weekly content", "weekly posts", "post schedule")):
        catalog_count = studio["counts"]["artworks"]
        weekly_plan = (
            "Monday — The feeling: Show the finished artwork and name the emotion or question behind it.\n"
            "Tuesday — The process: Share one close-up or short clip of a material, mark, or decision.\n"
            "Wednesday — The story: Explain one piece of the artwork’s meaning, ancestry, place, or future vision.\n"
            "Thursday — The detail: Post a crop, color choice, symbol, or texture and ask viewers what they notice.\n"
            "Friday — The invitation: Introduce the collection, share availability, and invite collectors to save or inquire."
        )
        return {
            "reply": (
                "**Your Black Canvas five-post content plan**\n\n"
                "**Monday — The feeling:** Show the finished artwork and name the emotion or question behind it.\n"
                "**Tuesday — The process:** Share one close-up or short clip of a material, mark, or decision.\n"
                "**Wednesday — The story:** Explain one piece of the artwork’s meaning, ancestry, place, or future vision.\n"
                "**Thursday — The detail:** Post a crop, color choice, symbol, or texture and ask viewers what they notice.\n"
                "**Friday — The invitation:** Introduce the collection, share availability, and invite collectors to save or inquire.\n\n"
                f"You have **{catalog_count}** cataloged {'artwork' if catalog_count == 1 else 'artworks'} to pull from. "
                "Keep each post focused on one honest visual detail, then use the artwork Content Kit when you are ready to write the final caption."
            ),
            "actions": [
                {"label": "Open Image Studio", "href": "/image-studio"},
                {"label": "Save this plan to Prompt Library", "href": (
                    "/prompts?new=1&title=" + quote("Weekly Content Plan")
                    + "&category=Content&text=" + quote(weekly_plan)
                )},
            ]
        }
    if any(phrase in topic_lower for phrase in ("launch plan", "launch my collection", "launch this collection", "art launch", "launch my art")):
        return {
            "reply": (
                "**Your Black Canvas collection-launch plan**\n\n"
                "**1. Select the release:** Choose 3–6 pieces that share one clear story and visual voice.\n"
                "**2. Complete the records:** Add title, size, medium, story, tags, and price for every chosen piece.\n"
                "**3. Prepare the buying path:** Run Listing Readiness, then create each Seller Package.\n"
                "**4. Build anticipation:** Share process, details, and the collection story before showing every finished piece.\n"
                "**5. Announce the release:** Publish the collection name, launch date, key artwork, and a simple way to inquire or buy.\n"
                "**6. Show the work again:** Use detail posts, a studio video, and one collector-focused explanation during launch week.\n"
                "**7. Follow up:** Track inquiries, update sold artwork immediately, and keep fulfillment records complete.\n\n"
                f"Right now you have **{studio_data['ready_to_list']}** pieces marked Ready to List. "
                "Start with the catalog so every artwork you promote is ready when someone wants to collect it."
            ),
            "actions": [
                {"label": "Open listing-ready artwork", "href": "/image-studio?focus=ready"},
                {"label": "Build a content week", "href": "/chat?q=Make%20me%20a%20weekly%20content%20plan"},
            ],
        }
    if "tiktok caption" in topic_lower or "instagram caption" in topic_lower:
        channel = "TikTok" if "tiktok" in topic_lower else "Instagram"
        subject = re.sub(r"\b(write|create|make|me|a|an|tiktok|instagram|caption|for)\b", " ", topic, flags=re.IGNORECASE)
        subject = re.sub(r"\s+", " ", subject).strip(" .") or "this piece"
        caption_text = (
            f"{subject[:1].upper() + subject[1:]} is a reminder that the work can hold both memory and possibility. "
            "Every layer is part of the story—built slowly, honestly, and with intention. "
            "What detail pulls you in first?\n\n"
            "#BlackCanvasArt #ContemporaryBlackArt #ArtistProcess #ArtCollector #CreativeStudio"
        )
        return {
            "reply": (
                f"**Your {channel} caption draft**\n\n"
                f"{caption_text}\n\n"
                "Edit the wording so it sounds like you, then pair it with a close detail, a process clip, or the finished artwork."
            ),
            "actions": [
                {"label": "Build a content week", "href": "/chat?q=Make%20me%20a%20weekly%20content%20plan"},
                {"label": "Save caption to Prompt Library", "href": (
                    "/prompts?new=1&title=" + quote(f"{channel} Caption — {subject[:45]}")
                    + "&category=Content&text=" + quote(caption_text)
                )},
            ],
        }
    if any(word in topic_lower for word in ("tiktok", "instagram", "caption", "reel", "social", "content")):
        return {
            "reply": (
                "**Black Canvas content direction**\n\n"
                f"For **{topic}**, use this simple post structure:\n"
                "- **Hook:** Name the feeling, story, or visual detail people should notice first.\n"
                "- **Process:** Share one honest behind-the-scenes decision.\n"
                "- **Meaning:** Explain what the piece represents in one or two clear lines.\n"
                "- **Invitation:** Ask viewers to save, comment, or follow the collection.\n\n"
                "Open an artwork in Image Studio and use its Content Kit to turn that structure into a caption set."
            ),
            "actions": [{"label": "Open Image Studio", "href": "/image-studio"}]
        }
    if any(word in topic_lower for word in ("organize", "organise", "review", "prompt library", "duplicate", "import")):
        return {
            "reply": (
                "**Black Canvas library direction**\n\n"
                f"You have **{studio['counts']['to_review']}** imported prompts waiting for review.\n\n"
                "Start with **Likely image prompts** when you want to pull creative directions forward. Use "
                "**Duplicates first** for cleanup: keep one strong copy, choose its collection, and remove extra "
                "copies only when you confirm they are truly identical."
            ),
            "actions": [
                {"label": "Review likely image prompts", "href": "/prompts?review=image"},
                {"label": "Review duplicates first", "href": "/prompts?review=duplicates"},
            ]
        }
    if any(word in topic_lower for word in ("order", "shipping", "ship", "fulfillment", "fulfilment", "tracking", "buyer")):
        active_orders = studio_data["active_orders"]
        return {
            "reply": (
                "**Black Canvas order direction**\n\n"
                f"You currently have **{active_orders}** active {'order' if active_orders == 1 else 'orders'} in fulfillment.\n\n"
                "For each sold piece, confirm the buyer details, packing status, carrier, tracking number, "
                "and delivery status. Keep the artwork record current so your sales and profit reports stay accurate."
            ),
            "actions": [{"label": "Open Orders Dashboard", "href": "/image-studio?focus=orders"}]
        }
    if any(word in topic_lower for word in ("print", "dpi", "300 dpi", "giclée", "giclee", "canvas size")):
        return {
            "reply": (
                "**Black Canvas print direction**\n\n"
                "Before sending a file to print, confirm the final print dimensions and pixel dimensions together. "
                "A 300-DPI label does not create missing detail—it only prepares a file that already has enough pixels.\n\n"
                "Use Print Prep from the artwork card in Image Studio. It will tell you the maximum clean print size "
                "and can export a print-ready PNG when the artwork is large enough."
            ),
            "actions": [{"label": "Open Image Studio", "href": "/image-studio"}]
        }
    if any(word in topic_lower for word in ("style bible", "brand", "collection rules", "visual voice")):
        return {
            "reply": (
                "**Black Canvas style direction**\n\n"
                "Your Style Bible is the source of truth for AfroNova, Quiet Nova, and GraffitiX. "
                "Use it before generating prompts so colors, symbols, mood, and visual storytelling stay consistent across a collection.\n\n"
                "Add any new rule as an update first, then review it before it becomes part of the permanent collection direction."
            ),
            "actions": [{"label": "Open Style Bible", "href": "/style-bible"}]
        }
    if any(word in topic_lower for word in ("listing", "list this", "product description", "product title", "seo", "shop listing")):
        return {
            "reply": (
                "**Black Canvas listing direction**\n\n"
                "A strong art listing needs four things: a clear title, the story behind the artwork, exact physical details, "
                "and a simple invitation to collect it. Write for the buyer who wants to understand both the piece and the process.\n\n"
                "In Image Studio, open the artwork and use Listing Readiness first. When the piece is complete, "
                "use the Seller Package to gather the listing copy, buyer details, and supporting files."
            ),
            "actions": [{"label": "Open ready-to-list artwork", "href": "/image-studio?focus=ready"}]
        }
    if any(word in topic_lower for word in ("certificate", "coa", "receipt", "provenance")):
        return {
            "reply": (
                "**Black Canvas collector-document direction**\n\n"
                "For a finished sale, keep the collector documents tied to the artwork record: the Certificate of Authenticity, "
                "sale receipt, artwork details, and fulfillment record. That gives the buyer a clear, professional package and keeps your studio records organized.\n\n"
                "Open the sold artwork in Image Studio to create the document set."
            ),
            "actions": [{"label": "Open Image Studio", "href": "/image-studio"}]
        }
    creative_triggers = ("portrait", "painting", "photo", "artwork", "afronova", "afro nova", "quiet nova", "graffitix", "graffiti x")
    if any(word in topic_lower for word in creative_triggers):
        live_reply = safe_live_agent_reply(topic, payload.conversation_id)
        if live_reply:
            return live_reply
        return image_prompt_chat_response(topic)
    live_reply = safe_live_agent_reply(topic, payload.conversation_id)
    if live_reply:
        return live_reply
    return {
        "reply": (
            f"**Black Canvas Agent plan for {topic}**\n\n"
            "Start by choosing the one outcome you want from this idea:\n"
            "- **Create:** turn it into an image prompt using AfroNova, Quiet Nova, or GraffitiX.\n"
            "- **Sell:** connect it to pricing, a listing, or a collector document.\n"
            "- **Share:** shape it into a process story, caption, or short-form content idea.\n"
            "- **Organize:** save the strongest pieces of the idea into your Prompt Library or Style Bible.\n\n"
            "Tell me which outcome you want, or use the Studio Brief for a recommendation based on your current workspace."
        ),
        "actions": [
            {"label": "Open Prompt Builder", "href": "/chat"},
            {"label": "Create Studio Brief", "href": "/chat?brief=1"},
        ]
    }


@app.get("/api/conversations")
def list_conversations() -> list[dict]:
    return rows(
        "SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) AS message_count "
        "FROM conversations c LEFT JOIN chat_messages m ON m.conversation_id = c.id "
        "GROUP BY c.id ORDER BY c.updated_at DESC, c.id DESC"
    )


@app.post("/api/conversations")
def create_conversation(payload: ConversationPayload) -> dict:
    title = re.sub(r"\s+", " ", payload.title).strip()[:60] or "New conversation"
    conversation_id = execute("INSERT INTO conversations(title) VALUES (?)", (title,))
    return {"id": conversation_id, "title": title}


@app.get("/api/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int) -> list[dict]:
    if not rows("SELECT id FROM conversations WHERE id = ?", (conversation_id,)):
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = rows(
        "SELECT id, role, text, metadata, created_at FROM chat_messages "
        "WHERE conversation_id = ? ORDER BY id", (conversation_id,)
    )
    for message in messages:
        try:
            message["metadata"] = json.loads(message["metadata"] or "{}")
        except json.JSONDecodeError:
            message["metadata"] = {}
    return messages


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation(conversation_id: int, payload: ConversationRenamePayload) -> dict:
    title = re.sub(r"\s+", " ", payload.title).strip()[:60]
    if not title:
        raise HTTPException(status_code=400, detail="A title is required")
    if not rows("SELECT id FROM conversations WHERE id = ?", (conversation_id,)):
        raise HTTPException(status_code=404, detail="Conversation not found")
    execute("UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (title, conversation_id))
    return {"id": conversation_id, "title": title}


@app.post("/api/conversations/{conversation_id}/messages")
def save_conversation_message(conversation_id: int, payload: ConversationMessagePayload) -> dict:
    if payload.role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="Unknown message role")
    if not rows("SELECT id FROM conversations WHERE id = ?", (conversation_id,)):
        raise HTTPException(status_code=404, detail="Conversation not found")
    message_id = execute(
        "INSERT INTO chat_messages(conversation_id, role, text, metadata) VALUES (?, ?, ?, ?)",
        (conversation_id, payload.role, payload.text.strip(), json.dumps(payload.metadata)),
    )
    execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,))
    return {"id": message_id, "status": "saved"}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: int) -> dict[str, str]:
    with connect() as db:
        db.execute("DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,))
        db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return {"status": "deleted"}


@app.post("/api/prompts/refine")
def refine_prompt(payload: PromptRefinePayload) -> dict[str, str]:
    prompt = clean_copy_ready_prompt(payload.prompt)
    category = payload.category if payload.category in ("AfroNova", "Quiet Nova", "GraffitiX") else "AfroNova"
    labels = {
        "clean": "Clean copy-ready prompt",
        "cinematic": "Cinematic variation",
        "detailed": "Detailed variation",
        "simple": "Simplified variation",
        "style": f"Stronger {category} variation",
    }
    if payload.mode not in labels:
        raise HTTPException(status_code=400, detail="Unknown refinement")

    if payload.mode == "clean":
        refined = prompt
    elif payload.mode == "cinematic":
        refined = prompt + (
            " Frame it like a prestige film still using a 50mm lens, shallow depth of field, subtle film grain, "
            "volumetric atmosphere, cinematic blocking, and controlled highlight roll-off."
        )
    elif payload.mode == "detailed":
        refined = prompt + (
            " Add precise micro-detail in skin, hair, fabric weave, jewelry, hands, surface texture, and environmental "
            "storytelling while keeping the composition clean and the main subject visually dominant."
        )
    elif payload.mode == "simple":
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", prompt) if part.strip()]
        keepers = []
        for index, sentence in enumerate(sentences):
            lowered = sentence.lower()
            if index == 0 or any(key in lowered for key in ("visual direction", "palette", "mood", "no text")):
                keepers.append(sentence)
        refined = " ".join(keepers[:5]) or prompt
    else:
        palette, direction, mood, avoid = saved_style_direction(category, "", "", "")
        cues = direction or f"the signature visual language of {category}"
        refined = prompt + (
            f" Push the {category} identity further through {cues}. Keep the mood {mood or 'intentional and expressive'}"
            f"{avoid}."
        )

    refined = re.sub(r"\s+", " ", refined).strip()
    return save_generated_prompt({
        "reply": f"**{labels[payload.mode]}**\n\n{refined}",
        "generated_prompt": refined,
        "prompt_title": labels[payload.mode],
        "prompt_category": category,
    })


@app.get("/api/prompts")
def list_prompts() -> list[dict]:
    return rows("SELECT id, title, category, text, favorite, source, reviewed FROM prompts ORDER BY id DESC")


@app.post("/api/prompts/recover-chat")
def recover_saved_chat_prompts() -> dict[str, int]:
    return recover_chat_prompts()


@app.get("/api/dashboard")
def dashboard_summary() -> dict:
    with connect() as db:
        prompt_count = db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
        artwork_count = db.execute("SELECT COUNT(*) FROM artworks").fetchone()[0]
        favorite_count = db.execute(
            "SELECT (SELECT COUNT(*) FROM prompts WHERE favorite = 1) + "
            "(SELECT COUNT(*) FROM artworks WHERE favorite = 1)"
        ).fetchone()[0]
        review_count = db.execute("SELECT COUNT(*) FROM prompts WHERE reviewed = 0").fetchone()[0]
        unreviewed_prompt_rows = db.execute(
            "SELECT title, category, text FROM prompts WHERE reviewed = 0"
        ).fetchall()
        image_review_count = sum(
            is_likely_image_prompt(item["title"], item["category"], item["text"])
            for item in unreviewed_prompt_rows
        )
        catalog_value = db.execute(
            "SELECT COALESCE(SUM(price), 0) FROM artworks WHERE sale_status NOT IN ('Sold', 'Not for sale')"
        ).fetchone()[0]
        sales_revenue = db.execute(
            "SELECT COALESCE(SUM(sale_price), 0) FROM artworks WHERE sale_status = 'Sold'"
        ).fetchone()[0]
        active_orders = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE sale_status = 'Sold' "
            "AND fulfillment_status NOT IN ('Delivered', 'Local pickup complete')"
        ).fetchone()[0]
        completed_orders = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE sale_status = 'Sold' "
            "AND fulfillment_status IN ('Delivered', 'Local pickup complete')"
        ).fetchone()[0]
        total_expenses = db.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses").fetchone()[0]
        current_month = datetime.now().strftime("%Y-%m")
        monthly_revenue = db.execute(
            "SELECT COALESCE(SUM(sale_price), 0) FROM artworks WHERE sale_status = 'Sold' AND sold_date LIKE ?",
            (f"{current_month}%",),
        ).fetchone()[0]
        goal_row = db.execute("SELECT value FROM studio_settings WHERE key = 'monthly_revenue_goal'").fetchone()
        monthly_goal = float(goal_row["value"]) if goal_row else 1000.0
        ready_to_list = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE sale_status = 'Ready to list'"
        ).fetchone()[0]
        unpriced_artwork = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE price <= 0 AND sale_status NOT IN ('Sold', 'Not for sale')"
        ).fetchone()[0]
        incomplete_artwork = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE sale_status NOT IN ('Sold', 'Not for sale') AND "
            "(TRIM(dimensions) = '' OR TRIM(medium) = '' OR TRIM(notes) = '' OR TRIM(tags) = '')"
        ).fetchone()[0]
        prompt_rows = [dict(item) for item in db.execute(
            "SELECT id, title, category, text FROM prompts ORDER BY id DESC LIMIT 3"
        ).fetchall()]
        artwork_rows = [dict(item) for item in db.execute(
            "SELECT id, title, collection, notes FROM artworks ORDER BY id DESC LIMIT 3"
        ).fetchall()]
        prompt_spotlights = [dict(item) for item in db.execute(
            "SELECT id, title, category, text FROM prompts WHERE reviewed = 1 "
            "AND category IN ('AfroNova', 'Quiet Nova', 'GraffitiX') "
            "AND LENGTH(TRIM(text)) BETWEEN 60 AND 1600 "
            "ORDER BY favorite DESC, id DESC"
        ).fetchall()]
        if not prompt_spotlights:
            prompt_spotlights = [dict(item) for item in db.execute(
                "SELECT id, title, category, text FROM prompts WHERE reviewed = 1 "
                "AND LENGTH(TRIM(text)) BETWEEN 60 AND 1600 ORDER BY favorite DESC, id DESC"
            ).fetchall()]
        if prompt_spotlights:
            spotlight_start = (datetime.now().timetuple().tm_yday - 1) % len(prompt_spotlights)
            prompt_spotlights = prompt_spotlights[spotlight_start:] + prompt_spotlights[:spotlight_start]
        prompt_of_day = prompt_spotlights[0] if prompt_spotlights else None

    activity = [
        {"kind": "prompt", "id": item["id"], "title": item["title"],
         "detail": item["category"], "description": item["text"]}
        for item in prompt_rows
    ] + [
        {"kind": "artwork", "id": item["id"], "title": item["title"],
         "detail": item["collection"], "description": item["notes"] or "Saved artwork"}
        for item in artwork_rows
    ]
    activity.sort(key=lambda item: item["id"], reverse=True)
    priorities: list[dict[str, str | int]] = []
    if active_orders:
        priorities.append({"icon": "▣", "title": "Move active orders forward", "count": active_orders,
                           "detail": "Review packing, shipping, and delivery status.", "href": "/image-studio?focus=orders", "tone": "blue"})
    if incomplete_artwork:
        priorities.append({"icon": "✓", "title": "Complete artwork details", "count": incomplete_artwork,
                           "detail": "Add missing size, medium, story, or tags first.", "href": "/image-studio?focus=incomplete", "tone": "amber"})
    if unpriced_artwork:
        priorities.append({"icon": "$", "title": "Price your available artwork", "count": unpriced_artwork,
                           "detail": "Use the calculator so catalog value reflects your work.", "href": "/image-studio?focus=unpriced", "tone": "purple"})
    if ready_to_list:
        priorities.append({"icon": "✦", "title": "Publish ready artwork", "count": ready_to_list,
                           "detail": "These pieces have been marked Ready to List.", "href": "/image-studio?focus=ready", "tone": "pink"})
    if image_review_count:
        priorities.append({"icon": "✦", "title": "Review likely image prompts", "count": image_review_count,
                           "detail": "Start with visual directions that are ready to develop.", "href": "/prompts?review=image", "tone": "purple"})
    elif review_count:
        priorities.append({"icon": "▤", "title": "Review imported prompts", "count": review_count,
                           "detail": "Keep the strongest ideas and organize the rest.", "href": "/prompts", "tone": "amber"})
    if not priorities:
        priorities.append({"icon": "✦", "title": "Create something new", "count": 0,
                           "detail": "Your studio records are caught up. Start a new artwork or prompt.", "href": "/chat", "tone": "purple"})
    return {
        "counts": {"prompts": prompt_count, "artworks": artwork_count,
                   "favorites": favorite_count, "to_review": review_count},
        "studio": {
            "catalog_value": round(float(catalog_value or 0), 2),
            "sales_revenue": round(float(sales_revenue or 0), 2),
            "active_orders": active_orders,
            "completed_orders": completed_orders,
            "ready_to_list": ready_to_list,
            "expenses": round(float(total_expenses or 0), 2),
            "net_profit": round(float(sales_revenue or 0) - float(total_expenses or 0), 2),
            "monthly_revenue": round(float(monthly_revenue or 0), 2),
            "monthly_goal": round(monthly_goal, 2),
            "goal_percent": min(round(float(monthly_revenue or 0) / monthly_goal * 100, 1), 100) if monthly_goal else 0,
        },
        "prompt_of_day": dict(prompt_of_day) if prompt_of_day else None,
        "prompt_spotlights": prompt_spotlights[:8],
        "recent": activity[:3],
        "priorities": priorities[:4],
    }


@app.get("/api/agent-brief")
def agent_brief() -> dict[str, object]:
    """Return a local, data-aware studio brief without sending data to an AI provider."""
    with connect() as db:
        prompt_count = db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
        review_count = db.execute("SELECT COUNT(*) FROM prompts WHERE reviewed = 0").fetchone()[0]
        unreviewed_prompt_rows = db.execute(
            "SELECT title, category, text FROM prompts WHERE reviewed = 0"
        ).fetchall()
        image_review_count = sum(
            is_likely_image_prompt(item["title"], item["category"], item["text"])
            for item in unreviewed_prompt_rows
        )
        artwork_count = db.execute("SELECT COUNT(*) FROM artworks").fetchone()[0]
        ready_to_list = db.execute("SELECT COUNT(*) FROM artworks WHERE sale_status = 'Ready to list'").fetchone()[0]
        unpriced = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE price <= 0 AND sale_status NOT IN ('Sold', 'Not for sale')"
        ).fetchone()[0]
        incomplete = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE sale_status NOT IN ('Sold', 'Not for sale') AND "
            "(TRIM(dimensions) = '' OR TRIM(medium) = '' OR TRIM(notes) = '' OR TRIM(tags) = '')"
        ).fetchone()[0]
        active_orders = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE sale_status = 'Sold' "
            "AND fulfillment_status NOT IN ('Delivered', 'Local pickup complete')"
        ).fetchone()[0]
        favorites = db.execute("SELECT COUNT(*) FROM prompts WHERE favorite = 1").fetchone()[0]

    if active_orders:
        next_step = f"Move {active_orders} active {'order' if active_orders == 1 else 'orders'} forward in Image Studio."
        action = {"label": "Open Orders Dashboard", "href": "/image-studio?focus=orders"}
    elif incomplete:
        next_step = f"Complete the missing catalog details on {incomplete} {'artwork' if incomplete == 1 else 'artworks'} before pricing or listing."
        action = {"label": "Complete artwork details", "href": "/image-studio?focus=incomplete"}
    elif unpriced:
        next_step = f"Price {unpriced} available {'artwork' if unpriced == 1 else 'artworks'} before listing."
        action = {"label": "Price available artwork", "href": "/image-studio?focus=unpriced"}
    elif ready_to_list:
        next_step = f"Prepare {ready_to_list} {'piece' if ready_to_list == 1 else 'pieces'} that are ready to list."
        action = {"label": "Open ready-to-list artwork", "href": "/image-studio?focus=ready"}
    elif image_review_count:
        next_step = f"Review {image_review_count} likely image {'prompt' if image_review_count == 1 else 'prompts'} before sorting the rest of your import."
        action = {"label": "Review likely image prompts", "href": "/prompts?review=image"}
    elif review_count:
        next_step = f"Review your {review_count} imported {'prompt' if review_count == 1 else 'prompts'} in a focused session."
        action = {"label": "Review imported prompts", "href": "/prompts?review=duplicates"}
    else:
        next_step = "Create a new prompt or add your next artwork to the studio."
        action = {"label": "Open Prompt Builder", "href": "/chat?builder=1"}

    return {"next_step": next_step, "action": action, "reply": (
        "**Black Canvas Agent Brief**\n\n"
        f"- **{artwork_count}** artworks in your studio\n"
        f"- **{prompt_count}** saved prompts, including **{favorites}** favorites\n"
        f"- **{review_count}** imported prompts still waiting for review\n"
        f"- **{ready_to_list}** pieces ready to list\n\n"
        f"**Best next move:** {next_step}\n\n"
        "This brief uses the information already saved inside BlackCanvasAI."
    )}


@app.post("/api/prompts")
def create_prompt(payload: PromptPayload) -> dict:
    try:
        prompt_id = execute(
            "INSERT INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, ?, ?, ?, 'manual', 1)",
            (payload.title.strip(), payload.category, payload.text.strip(), int(payload.favorite)),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Prompt already exists")
    return {"id": prompt_id, **payload.model_dump()}


@app.put("/api/prompts/{prompt_id}")
def update_prompt(prompt_id: int, payload: PromptPayload) -> dict:
    try:
        with connect() as db:
            cursor = db.execute(
                "UPDATE prompts SET title = ?, category = ?, text = ?, favorite = ?, reviewed = 1 WHERE id = ?",
                (payload.title.strip(), payload.category, payload.text.strip(), int(payload.favorite), prompt_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Prompt not found")
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="That prompt is already saved")
    return {"id": prompt_id, **payload.model_dump(), "reviewed": True}


@app.post("/api/prompts/bulk-update")
def bulk_update_prompts(payload: PromptBulkPayload) -> dict[str, int]:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))[:500]
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    updates: list[str] = []
    values: list[str | int] = []
    if payload.category is not None:
        updates.append("category = ?")
        values.append(payload.category)
    if payload.reviewed is not None:
        updates.append("reviewed = ?")
        values.append(int(payload.reviewed))
    if not updates:
        raise HTTPException(status_code=400, detail="No changes were requested")
    placeholders = ",".join("?" for _ in prompt_ids)
    with connect() as db:
        cursor = db.execute(
            f"UPDATE prompts SET {', '.join(updates)} WHERE id IN ({placeholders})",
            (*values, *prompt_ids),
        )
    return {"updated": cursor.rowcount}


@app.post("/api/prompts/bulk-clean")
def bulk_clean_prompts(payload: PromptBulkPayload) -> dict[str, int]:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))[:500]
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    placeholders = ",".join("?" for _ in prompt_ids)
    cleaned = 0
    changed = 0
    with connect() as db:
        items = db.execute(
            f"SELECT id, text FROM prompts WHERE id IN ({placeholders})",
            prompt_ids,
        ).fetchall()
        for item in items:
            clean_text = clean_copy_ready_prompt(item["text"])
            cleaned += 1
            if clean_text != item["text"]:
                db.execute("UPDATE prompts SET text = ? WHERE id = ?", (clean_text, item["id"]))
                changed += 1
    return {"cleaned": cleaned, "changed": changed}


@app.post("/api/prompts/bulk-delete")
def bulk_delete_prompts(payload: PromptBulkPayload) -> dict[str, int]:
    prompt_ids = list(dict.fromkeys(payload.prompt_ids))[:500]
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="Select at least one prompt")
    placeholders = ",".join("?" for _ in prompt_ids)
    with connect() as db:
        cursor = db.execute(f"DELETE FROM prompts WHERE id IN ({placeholders})", prompt_ids)
    return {"removed": cursor.rowcount}


@app.delete("/api/prompts/{prompt_id}")
def delete_prompt(prompt_id: int) -> dict[str, str]:
    with connect() as db:
        cursor = db.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Prompt not found")
    return {"status": "removed"}


@app.patch("/api/prompts/{prompt_id}/favorite")
def favorite_prompt(prompt_id: int, favorite: bool) -> dict[str, bool]:
    execute("UPDATE prompts SET favorite = ? WHERE id = ?", (int(favorite), prompt_id))
    return {"favorite": favorite}


@app.get("/api/styles")
def list_styles() -> dict:
    return {item["name"]: json.loads(item["content"]) for item in rows("SELECT name, content FROM styles")}


@app.get("/api/styles/{style_name}/agent-brief")
def style_agent_brief(style_name: str) -> dict[str, object]:
    if style_name not in {"AfroNova", "Quiet Nova", "GraffitiX"}:
        raise HTTPException(status_code=404, detail="Style not found")
    with connect() as db:
        row = db.execute("SELECT content FROM styles WHERE name = ?", (style_name,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Style not found")
    try:
        style = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="Style data could not be read")

    mood = ", ".join(str(value) for value in style.get("mood", [])[:4]) or "intentional and expressive"
    ingredients = "; ".join(str(value) for value in style.get("ingredients", [])[:4]) or "the collection's saved visual ingredients"
    dos = "; ".join(str(value) for value in style.get("dos", [])[:3]) or "the collection's saved rules"
    donts = "; ".join(str(value) for value in style.get("donts", [])[:3]) or "generic visual choices"
    return {
        "title": f"{style_name} Creative Brief",
        "reply": (
            f"**Black Canvas Agent brief: {style_name}**\n\n"
            f"**Core direction:** {style.get('statement') or style.get('tagline') or 'Use the saved collection identity.'}\n\n"
            f"- **Energy:** {mood}\n"
            f"- **Build with:** {ingredients}\n"
            f"- **Always protect:** {dos}\n"
            f"- **Avoid:** {donts}\n\n"
            "**Best next move:** Pick one clear subject, let this collection direction lead the composition, then use the Prompt Builder to turn it into a testable image prompt."
        ),
        "actions": [
            {"label": f"Browse {style_name} prompts", "href": f"/prompts?category={quote(style_name)}"},
            {"label": f"Create {style_name} prompt", "href": f"/chat?builder=1&collection={quote(style_name)}"},
        ],
    }


@app.put("/api/styles/{name}")
def save_style(name: str, payload: StylePayload) -> dict[str, str]:
    execute("INSERT OR REPLACE INTO styles(name, content) VALUES (?, ?)", (name, json.dumps(payload.content)))
    return {"status": "saved"}


def style_update_suggestions(text: str) -> dict[str, list[str]]:
    suggestions = {"ingredients": [], "language": [], "dos": [], "donts": []}
    pieces = re.split(r"[\n•]+|(?<=[.!?])\s+", text)
    for piece in pieces:
        item = re.sub(r"^[-*\d.)\s]+", "", piece).strip().rstrip(".")
        if len(item) < 3:
            continue
        lowered = item.lower()
        if any(word in lowered for word in ("avoid", "don't", "do not", "never", "instead of", "overpower", "crowd")):
            bucket = "donts"
        elif any(word in lowered for word in ("rule", "always", "keep", "use", "follow", "hierarchy", "secondary", "main subject")):
            bucket = "dos"
        elif any(word in lowered for word in ("phrase", "language", "word", "describe", "call it")):
            bucket = "language"
        else:
            bucket = "ingredients"
        if item not in suggestions[bucket] and len(suggestions[bucket]) < 12:
            suggestions[bucket].append(item[:240])
    return suggestions


@app.post("/api/spellcheck")
def spellcheck_text(payload: SpellCheckPayload) -> dict:
    checker = SpellChecker(distance=1)
    protected = {
        "afronova", "graffitix", "midjourney", "afrofuturist", "afrofuturism",
        "streetart", "chatgpt", "blackcanvas", "neon", "scribbles", "xeyes",
    }
    common_creative_corrections = {
        "ancsstral": "ancestral", "enegy": "energy", "afrofutursim": "afrofuturism",
        "afrofuturistm": "afrofuturism", "graffitti": "graffiti", "portriat": "portrait",
        "cosimc": "cosmic", "beutiful": "beautiful", "colrs": "colors",
        "discripton": "description", "discription": "description", "descripton": "description",
        "discriptions": "descriptions", "discriptons": "descriptions", "descriptons": "descriptions",
        "artowrk": "artwork", "artwrk": "artwork", "calander": "calendar",
        "definately": "definitely", "seperate": "separate", "recieve": "receive",
        "thier": "their", "wierd": "weird", "teh": "the",
    }
    changes: list[dict[str, str]] = []

    def correct_word(match: re.Match) -> str:
        word = match.group(0)
        lowered = word.lower()
        if len(word) < 4 or lowered in protected or word.isupper() or any(char.isdigit() for char in word):
            return word
        if lowered in common_creative_corrections:
            correction = common_creative_corrections[lowered]
            if word[0].isupper():
                correction = correction.capitalize()
            changes.append({"original": word, "replacement": correction})
            return correction
        if lowered not in checker.unknown([lowered]):
            return word
        correction = checker.correction(lowered)
        if not correction or correction == lowered:
            return word
        if word[0].isupper():
            correction = correction.capitalize()
        changes.append({"original": word, "replacement": correction})
        return correction

    corrected = re.sub(r"[A-Za-z][A-Za-z'-]*", correct_word, payload.text)
    return {"corrected_text": corrected, "changes": changes}


@app.get("/api/style-updates")
def list_style_updates() -> list[dict]:
    items = rows(
        "SELECT id, style_name, source_text, suggestions, status, created_at "
        "FROM style_updates ORDER BY id DESC"
    )
    for item in items:
        item["suggestions"] = json.loads(item["suggestions"])
    return items


@app.post("/api/style-updates")
def create_style_update(payload: StyleUpdatePayload) -> dict:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Paste a style update first")
    if payload.style_name not in ("AfroNova", "Quiet Nova", "GraffitiX"):
        raise HTTPException(status_code=400, detail="Choose a valid style")
    suggestions = style_update_suggestions(text)
    update_id = execute(
        "INSERT INTO style_updates(style_name, source_text, suggestions) VALUES (?, ?, ?)",
        (payload.style_name, text, json.dumps(suggestions)),
    )
    return {"id": update_id, "style_name": payload.style_name, "source_text": text,
            "suggestions": suggestions, "status": "pending"}


@app.post("/api/style-updates/{update_id}/approve")
def approve_style_update(update_id: int, payload: StyleUpdateDecision) -> dict:
    with connect() as db:
        update = db.execute(
            "SELECT style_name, status FROM style_updates WHERE id = ?", (update_id,)
        ).fetchone()
        if not update:
            raise HTTPException(status_code=404, detail="Style update not found")
        if update["status"] != "pending":
            raise HTTPException(status_code=409, detail="Style update already reviewed")
        style_row = db.execute("SELECT content FROM styles WHERE name = ?", (update["style_name"],)).fetchone()
        if not style_row:
            raise HTTPException(status_code=404, detail="Style not found")
        style = json.loads(style_row["content"])
        for field in ("ingredients", "language", "dos", "donts"):
            existing = style.setdefault(field, [])
            for value in payload.suggestions.get(field, []):
                clean_value = value.strip()[:240]
                if clean_value and clean_value not in existing:
                    existing.append(clean_value)
        db.execute("UPDATE styles SET content = ? WHERE name = ?", (json.dumps(style), update["style_name"]))
        db.execute("UPDATE style_updates SET suggestions = ?, status = 'approved' WHERE id = ?",
                   (json.dumps(payload.suggestions), update_id))
    return {"status": "approved", "style_name": update["style_name"], "content": style}


@app.post("/api/style-updates/{update_id}/dismiss")
def dismiss_style_update(update_id: int) -> dict[str, str]:
    with connect() as db:
        cursor = db.execute(
            "UPDATE style_updates SET status = 'dismissed' WHERE id = ? AND status = 'pending'", (update_id,)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Pending style update not found")
    return {"status": "dismissed"}


@app.get("/api/artworks")
def list_artworks() -> list[dict]:
    items = rows("SELECT id, title, collection, tags, notes, favorite, dimensions, medium, price, sale_status, sale_price, sold_date, sales_channel, buyer_name, sale_notes, fulfillment_status, shipping_carrier, tracking_number, gallery_visible, listing_url, filename, created_at FROM artworks ORDER BY id DESC")
    for item in items:
        item["url"] = f"/uploads/{item['filename']}"
    return items


@app.post("/api/artworks/bulk-update")
def bulk_update_artworks(payload: ArtworkBulkPayload) -> dict[str, int]:
    artwork_ids = list(dict.fromkeys(payload.artwork_ids))[:100]
    if not artwork_ids:
        raise HTTPException(status_code=400, detail="Select at least one artwork")
    valid_collections = {"Unsorted", "AfroNova", "Quiet Nova", "GraffitiX"}
    valid_statuses = {"In progress", "Ready to list", "Listed", "Sold", "Not for sale"}
    if payload.collection is not None and payload.collection not in valid_collections:
        raise HTTPException(status_code=400, detail="Choose a valid collection")
    if payload.sale_status is not None and payload.sale_status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Choose a valid sales status")
    medium = payload.medium.strip() if payload.medium is not None else None
    if medium is not None and len(medium) > 120:
        raise HTTPException(status_code=400, detail="Keep the medium under 120 characters")
    if payload.collection is None and medium is None and payload.sale_status is None and payload.gallery_visible is None and not payload.add_tags.strip():
        raise HTTPException(status_code=400, detail="Choose at least one change")
    placeholders = ",".join("?" for _ in artwork_ids)
    with connect() as db:
        items = db.execute(f"SELECT id, tags FROM artworks WHERE id IN ({placeholders})", artwork_ids).fetchall()
        for item in items:
            updates, values = [], []
            if payload.collection is not None:
                updates.append("collection = ?"); values.append(payload.collection)
            if medium is not None:
                updates.append("medium = ?"); values.append(medium)
            if payload.sale_status is not None:
                updates.append("sale_status = ?"); values.append(payload.sale_status)
            if payload.gallery_visible is not None:
                updates.append("gallery_visible = ?"); values.append(int(payload.gallery_visible))
            if payload.add_tags.strip():
                existing = [tag.strip() for tag in str(item["tags"] or "").split(",") if tag.strip()]
                seen = {tag.lower() for tag in existing}
                for tag in payload.add_tags.split(","):
                    clean_tag = tag.strip()
                    if clean_tag and clean_tag.lower() not in seen:
                        existing.append(clean_tag); seen.add(clean_tag.lower())
                updates.append("tags = ?"); values.append(", ".join(existing))
            db.execute(f"UPDATE artworks SET {', '.join(updates)} WHERE id = ?", (*values, item["id"]))
    return {"updated": len(items)}


@app.get("/api/gallery-artworks")
def list_gallery_artworks() -> list[dict]:
    """Public gallery data: no private order details and no full-resolution file URLs."""
    items = rows(
        "SELECT id, title, collection, tags, notes, favorite, dimensions, medium, price, sale_status, listing_url "
        "FROM artworks WHERE gallery_visible = 1 AND sale_status NOT IN ('Sold', 'Not for sale') ORDER BY id DESC"
    )
    for item in items:
        item["url"] = f"/api/gallery-artworks/{item['id']}/image"
    return items


@app.get("/api/gallery-artworks/{artwork_id}/image")
def gallery_artwork_image(artwork_id: int, width: int = 1200) -> Response:
    """Serve a right-sized gallery preview, keeping the original upload private."""
    matches = rows("SELECT filename FROM artworks WHERE id = ? AND gallery_visible = 1", (artwork_id,))
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    image_path = UPLOAD_DIR / matches[0]["filename"]
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Artwork image not found")
    try:
        with Image.open(image_path) as source:
            preview = ImageOps.exif_transpose(source).convert("RGB")
            preview_width = min(max(int(width), 320), 1600)
            preview.thumbnail((preview_width, preview_width), Image.Resampling.LANCZOS)
            image_bytes = io.BytesIO()
            preview.save(image_bytes, format="JPEG", quality=86, optimize=True)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Artwork preview could not be prepared") from error
    return Response(
        content=image_bytes.getvalue(), media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400", "Vary": "Accept"},
    )


@app.get("/api/artworks/{artwork_id}/agent-brief")
def artwork_agent_brief(artwork_id: int) -> dict[str, object]:
    with connect() as db:
        artwork = db.execute(
            "SELECT id, title, collection, tags, notes, dimensions, medium, price, sale_status, "
            "fulfillment_status FROM artworks WHERE id = ?",
            (artwork_id,),
        ).fetchone()
    if not artwork:
        raise HTTPException(status_code=404, detail="Artwork not found")

    artwork = dict(artwork)
    missing = [
        label for field, label in (
            ("dimensions", "size"),
            ("medium", "medium"),
            ("notes", "story / description"),
            ("tags", "tags"),
        ) if not str(artwork[field] or "").strip()
    ]
    title = artwork["title"] or "This artwork"
    if artwork["sale_status"] == "Sold":
        next_step = "Finish the fulfillment record, then prepare the collector documents and delivery details."
        actions = [
            {"label": "Track this order", "href": f"/image-studio?artwork={artwork['id']}&tool=fulfillment"},
            {"label": "Open Orders Dashboard", "href": "/image-studio?focus=orders"},
        ]
    elif missing:
        next_step = f"Complete the missing {', '.join(missing)} before moving it toward sale."
        actions = [
            {"label": "Edit this artwork", "href": f"/image-studio?artwork={artwork['id']}&tool=edit"},
            {"label": "View all incomplete artwork", "href": "/image-studio?focus=incomplete"},
        ]
    elif float(artwork["price"] or 0) <= 0:
        next_step = "Use the Pricing Calculator to set a confident starting retail price."
        actions = [
            {"label": "Open Pricing Calculator", "href": f"/image-studio?artwork={artwork['id']}&tool=pricing"},
            {"label": "View all unpriced artwork", "href": "/image-studio?focus=unpriced"},
        ]
    elif artwork["sale_status"] == "Ready to list":
        next_step = "Create the listing materials and Seller Package, then publish it where your collectors can find it."
        actions = [
            {"label": "Open listing checklist", "href": f"/image-studio?artwork={artwork['id']}&tool=readiness"},
            {"label": "View ready-to-list artwork", "href": "/image-studio?focus=ready"},
        ]
    else:
        next_step = "Choose whether the next step is content, print prep, pricing, or listing readiness."
        actions = [{"label": "Open Image Studio", "href": "/image-studio"}]

    price_line = (
        f"**${float(artwork['price'] or 0):,.0f}** current catalog price"
        if float(artwork["price"] or 0) else "No price set yet"
    )
    collection = str(artwork["collection"] or "").strip()
    if collection in {"AfroNova", "Quiet Nova", "GraffitiX"}:
        actions.append({
            "label": f"Browse {collection} prompts",
            "href": f"/prompts?category={quote(collection)}",
        })
    if artwork["sale_status"] != "Sold":
        actions.append({
            "label": "Create artwork content kit",
            "href": f"/image-studio?artwork={artwork['id']}&tool=content",
        })
    return {
        "title": f"Artwork Plan: {title}"[:60],
        "reply": (
            f"**Black Canvas Agent plan for {title}**\n\n"
            f"- Collection: **{artwork['collection']}**\n"
            f"- Status: **{artwork['sale_status']}**\n"
            f"- {price_line}\n"
            f"- {('Details still needed: ' + ', '.join(missing)) if missing else 'Core artwork details are present'}\n\n"
            f"**Best next move:** {next_step}"
        ),
        "actions": actions,
    }


@app.get("/api/artworks-export")
def export_artwork_catalog() -> Response:
    artworks = rows(
        "SELECT id, title, collection, dimensions, medium, tags, notes, price, sale_status, "
        "sale_price, sold_date, sales_channel, buyer_name, fulfillment_status, shipping_carrier, "
        "tracking_number, created_at FROM artworks ORDER BY id DESC"
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "Catalog ID", "Artwork", "Collection", "Dimensions", "Medium", "Tags", "Description / Notes",
        "List Price", "Artwork Status", "Sale Price", "Date Sold", "Sales Channel", "Buyer",
        "Fulfillment Status", "Shipping Carrier", "Tracking Number", "Date Added",
    ])
    for artwork in artworks:
        writer.writerow([
            artwork["id"], artwork["title"], artwork["collection"], artwork["dimensions"], artwork["medium"],
            artwork["tags"], artwork["notes"], f"{float(artwork['price'] or 0):.2f}", artwork["sale_status"],
            f"{float(artwork['sale_price'] or 0):.2f}", artwork["sold_date"], artwork["sales_channel"],
            artwork["buyer_name"], artwork["fulfillment_status"], artwork["shipping_carrier"],
            artwork["tracking_number"], artwork["created_at"],
        ])
    filename = f"BlackCanvasAI-Artwork-Catalog-{datetime.now().strftime('%Y-%m-%d')}.csv"
    return Response(
        content=output.getvalue().encode("utf-8-sig"), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sales")
def list_sales() -> dict:
    sales = rows(
        "SELECT id, title, collection, sale_price, sold_date, sales_channel, buyer_name, sale_notes "
        "FROM artworks WHERE sale_status = 'Sold' ORDER BY sold_date DESC, id DESC"
    )
    total = sum(float(sale["sale_price"] or 0) for sale in sales)
    return {
        "sales": sales,
        "count": len(sales),
        "total_revenue": round(total, 2),
        "average_sale": round(total / len(sales), 2) if sales else 0,
    }


@app.get("/api/orders")
def list_orders() -> dict:
    orders = rows(
        "SELECT id, title, collection, buyer_name, sale_price, sold_date, fulfillment_status, "
        "shipping_carrier, tracking_number FROM artworks WHERE sale_status = 'Sold' "
        "ORDER BY CASE fulfillment_status WHEN 'Not started' THEN 1 WHEN 'Packing' THEN 2 "
        "WHEN 'Ready to ship' THEN 3 WHEN 'Shipped' THEN 4 WHEN 'Delivered' THEN 5 ELSE 6 END, sold_date DESC"
    )
    active = sum(order["fulfillment_status"] not in {"Delivered", "Local pickup complete"} for order in orders)
    return {
        "orders": orders,
        "count": len(orders),
        "active": active,
        "completed": len(orders) - active,
    }


@app.get("/api/expenses")
def list_expenses() -> dict:
    expenses = rows(
        "SELECT id, description, category, amount, expense_date, notes FROM expenses "
        "ORDER BY expense_date DESC, id DESC"
    )
    total = sum(float(item["amount"] or 0) for item in expenses)
    categories: dict[str, float] = {}
    for item in expenses:
        categories[item["category"]] = round(categories.get(item["category"], 0) + float(item["amount"] or 0), 2)
    return {"expenses": expenses, "count": len(expenses), "total": round(total, 2), "categories": categories}


@app.post("/api/expenses")
def create_expense(payload: ExpensePayload) -> dict:
    description = payload.description.strip()
    category = payload.category.strip()
    if not description:
        raise HTTPException(status_code=400, detail="Add an expense description")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Expense amount must be greater than zero")
    try:
        datetime.strptime(payload.expense_date, "%Y-%m-%d")
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Use a valid expense date") from error
    allowed = {"Art materials", "Printing", "Packaging", "Shipping", "Advertising", "Platform fees", "Studio", "Software", "Other"}
    if category not in allowed:
        raise HTTPException(status_code=400, detail="Choose a valid expense category")
    expense_id = execute(
        "INSERT INTO expenses(description, category, amount, expense_date, notes) VALUES (?, ?, ?, ?, ?)",
        (description, category, payload.amount, payload.expense_date, payload.notes.strip()),
    )
    return {"id": expense_id, **payload.model_dump(), "description": description, "category": category}


@app.delete("/api/expenses/{expense_id}")
def delete_expense(expense_id: int) -> dict:
    with connect() as db:
        cursor = db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Expense not found")
    return {"status": "removed"}


@app.put("/api/expenses/{expense_id}")
def update_expense(expense_id: int, payload: ExpensePayload) -> dict:
    description = payload.description.strip()
    category = payload.category.strip()
    if not description:
        raise HTTPException(status_code=400, detail="Add an expense description")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Expense amount must be greater than zero")
    try:
        datetime.strptime(payload.expense_date, "%Y-%m-%d")
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Use a valid expense date") from error
    allowed = {"Art materials", "Printing", "Packaging", "Shipping", "Advertising", "Platform fees", "Studio", "Software", "Other"}
    if category not in allowed:
        raise HTTPException(status_code=400, detail="Choose a valid expense category")
    with connect() as db:
        try:
            cursor = db.execute(
                "UPDATE expenses SET description = ?, category = ?, amount = ?, expense_date = ?, notes = ? WHERE id = ?",
                (description, category, payload.amount, payload.expense_date, payload.notes.strip(), expense_id),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="That expense is already recorded") from error
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Expense not found")
    return {"id": expense_id, **payload.model_dump(), "description": description, "category": category}


@app.get("/api/finance-report")
def finance_report(period: str = "all") -> dict:
    period = period.lower().strip()
    if period not in {"all", "month", "year"}:
        raise HTTPException(status_code=400, detail="Choose all, month, or year")
    date_prefix = ""
    if period == "month":
        date_prefix = datetime.now().strftime("%Y-%m")
    elif period == "year":
        date_prefix = datetime.now().strftime("%Y")
    sales_filter = " AND sold_date LIKE ?" if date_prefix else ""
    expense_filter = " WHERE expense_date LIKE ?" if date_prefix else ""
    query_values = (f"{date_prefix}%",) if date_prefix else ()
    sales = rows(
        "SELECT id, title AS description, sold_date AS entry_date, sales_channel AS category, "
        f"sale_price AS amount FROM artworks WHERE sale_status = 'Sold'{sales_filter} ORDER BY sold_date DESC",
        query_values,
    )
    expenses = rows(
        f"SELECT id, description, expense_date AS entry_date, category, amount FROM expenses{expense_filter} "
        "ORDER BY expense_date DESC, id DESC", query_values,
    )
    revenue = sum(float(item["amount"] or 0) for item in sales)
    expense_total = sum(float(item["amount"] or 0) for item in expenses)
    category_totals: dict[str, float] = {}
    for item in expenses:
        category_totals[item["category"]] = round(
            category_totals.get(item["category"], 0) + float(item["amount"] or 0), 2
        )
    transactions = [
        {**item, "type": "Income", "signed_amount": float(item["amount"] or 0)} for item in sales
    ] + [
        {**item, "type": "Expense", "signed_amount": -float(item["amount"] or 0)} for item in expenses
    ]
    transactions.sort(key=lambda item: (item["entry_date"], item["id"]), reverse=True)
    goal_data = get_revenue_goal()
    return {
        "revenue": round(revenue, 2),
        "expenses": round(expense_total, 2),
        "net_profit": round(revenue - expense_total, 2),
        "sale_count": len(sales),
        "expense_count": len(expenses),
        "expense_categories": category_totals,
        "transactions": transactions,
        "monthly_goal": goal_data,
        "period": period,
    }


@app.get("/api/revenue-goal")
def get_revenue_goal() -> dict:
    current_month = datetime.now().strftime("%Y-%m")
    with connect() as db:
        goal_row = db.execute("SELECT value FROM studio_settings WHERE key = 'monthly_revenue_goal'").fetchone()
        goal = float(goal_row["value"]) if goal_row else 1000.0
        revenue = float(db.execute(
            "SELECT COALESCE(SUM(sale_price), 0) FROM artworks WHERE sale_status = 'Sold' AND sold_date LIKE ?",
            (f"{current_month}%",),
        ).fetchone()[0] or 0)
    return {
        "month": current_month,
        "goal": round(goal, 2),
        "revenue": round(revenue, 2),
        "remaining": round(max(goal - revenue, 0), 2),
        "percent": min(round(revenue / goal * 100, 1), 100) if goal else 0,
    }


@app.put("/api/revenue-goal")
def update_revenue_goal(payload: RevenueGoalPayload) -> dict:
    if payload.monthly_goal <= 0:
        raise HTTPException(status_code=400, detail="Monthly revenue goal must be greater than zero")
    with connect() as db:
        db.execute(
            "INSERT INTO studio_settings(key, value) VALUES ('monthly_revenue_goal', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(round(payload.monthly_goal, 2)),),
        )
    return get_revenue_goal()


@app.get("/api/finance-report/export")
def export_finance_report(period: str = "all") -> Response:
    report = finance_report(period)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Black Canvas Art Studio - Profit and Loss Report"])
    writer.writerow(["Generated", datetime.now().strftime("%Y-%m-%d")])
    writer.writerow(["Period", {"all": "All time", "month": "This month", "year": "This year"}[report["period"]]])
    writer.writerow([])
    writer.writerow(["Summary", "Amount"])
    writer.writerow(["Sales revenue", f"{report['revenue']:.2f}"])
    writer.writerow(["Business expenses", f"{report['expenses']:.2f}"])
    writer.writerow(["Net profit", f"{report['net_profit']:.2f}"])
    writer.writerow([])
    writer.writerow(["Type", "Date", "Description", "Category / Channel", "Amount"])
    for item in report["transactions"]:
        writer.writerow([
            item["type"], item["entry_date"], item["description"], item["category"],
            f"{item['signed_amount']:.2f}",
        ])
    filename = f"BlackCanvasAI-Profit-Loss-{datetime.now().strftime('%Y-%m-%d')}.csv"
    return Response(
        content=output.getvalue().encode("utf-8-sig"), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sales/export")
def export_sales_report() -> Response:
    report = list_sales()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Artwork", "Collection", "Sale Price", "Date Sold", "Sales Channel", "Buyer", "Notes"])
    for sale in report["sales"]:
        writer.writerow([
            sale["title"], sale["collection"], f"{float(sale['sale_price'] or 0):.2f}", sale["sold_date"],
            sale["sales_channel"], sale["buyer_name"], sale["sale_notes"],
        ])
    filename = f"BlackCanvasAI-Sales-{datetime.now().strftime('%Y-%m-%d')}.csv"
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/artworks/{artwork_id}/certificate")
def artwork_certificate(artwork_id: int) -> FileResponse:
    matches = rows(
        "SELECT id, title, collection, notes, dimensions, medium, filename, created_at "
        "FROM artworks WHERE id = ?", (artwork_id,)
    )
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    artwork = matches[0]
    if not artwork["dimensions"].strip() or not artwork["medium"].strip():
        raise HTTPException(status_code=400, detail="Add dimensions and medium before creating a certificate")
    image_path = UPLOAD_DIR / artwork["filename"]
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Artwork image file not found")

    certificate_id = f"BC-{artwork_id:05d}-{uuid.uuid5(uuid.NAMESPACE_URL, artwork['filename']).hex[:8].upper()}"
    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "-", artwork["title"]).strip("-") or "artwork"
    certificate_dir = DATA_DIR / "certificates"
    certificate_dir.mkdir(parents=True, exist_ok=True)
    certificate_path = certificate_dir / f"{safe_title}-certificate-of-authenticity.pdf"
    page_width, page_height = landscape(letter)
    document = canvas.Canvas(str(certificate_path), pagesize=(page_width, page_height))
    document.setTitle(f"Certificate of Authenticity - {artwork['title']}")
    document.setAuthor("BlackCanvasAI for Jeffrey McKay")

    document.setFillColor(colors.HexColor("#F7F3EA"))
    document.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    document.setStrokeColor(colors.HexColor("#17131F"))
    document.setLineWidth(2)
    document.rect(24, 24, page_width - 48, page_height - 48, fill=0, stroke=1)
    document.setStrokeColor(colors.HexColor("#9A7342"))
    document.setLineWidth(0.8)
    document.rect(31, 31, page_width - 62, page_height - 62, fill=0, stroke=1)

    image_box_x, image_box_y, image_box_w, image_box_h = 58, 105, 270, 360
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((image_box_w, image_box_h), Image.Resampling.LANCZOS)
        image_buffer = io.BytesIO()
        image.save(image_buffer, format="JPEG", quality=92)
        image_width, image_height = image.size
    image_x = image_box_x + (image_box_w - image_width) / 2
    image_y = image_box_y + (image_box_h - image_height) / 2
    document.setFillColor(colors.white)
    document.rect(image_box_x - 9, image_box_y - 9, image_box_w + 18, image_box_h + 18, fill=1, stroke=0)
    document.drawImage(ImageReader(image_buffer), image_x, image_y, width=image_width, height=image_height, mask="auto")

    text_x = 375
    document.setFillColor(colors.HexColor("#6C4D88"))
    document.setFont("Helvetica-Bold", 10)
    document.drawString(text_x, 503, "BLACK CANVAS ART STUDIO")
    document.setFillColor(colors.HexColor("#17131F"))
    document.setFont("Helvetica-Bold", 21)
    document.drawString(text_x, 463, "CERTIFICATE OF AUTHENTICITY")
    document.setStrokeColor(colors.HexColor("#9A7342"))
    document.setLineWidth(1.2)
    document.line(text_x, 447, 730, 447)
    document.setFont("Helvetica", 10)
    document.setFillColor(colors.HexColor("#514A58"))
    document.drawString(text_x, 422, "This certificate confirms that the artwork described below is an authentic work by")
    document.setFont("Helvetica-Bold", 12)
    document.setFillColor(colors.HexColor("#17131F"))
    document.drawString(text_x, 401, "Jeffrey McKay")

    details = [
        ("TITLE", artwork["title"]),
        ("COLLECTION", artwork["collection"]),
        ("MEDIUM", artwork["medium"]),
        ("DIMENSIONS", artwork["dimensions"]),
        ("CERTIFICATE NO.", certificate_id),
    ]
    detail_y = 360
    for label, value in details:
        document.setFillColor(colors.HexColor("#7A707F"))
        document.setFont("Helvetica-Bold", 8)
        document.drawString(text_x, detail_y, label)
        document.setFillColor(colors.HexColor("#17131F"))
        document.setFont("Helvetica", 11)
        document.drawString(text_x + 105, detail_y, str(value)[:48])
        detail_y -= 31

    statement = artwork["notes"].strip() or "An original artwork created as part of the Black Canvas body of work."
    document.setFillColor(colors.HexColor("#514A58"))
    document.setFont("Helvetica-Oblique", 9)
    text_object = document.beginText(text_x, 190)
    text_object.setLeading(13)
    words = statement.split()
    lines: list[str] = []
    current_line = ""
    for word in words:
        candidate = f"{current_line} {word}".strip()
        if document.stringWidth(candidate, "Helvetica-Oblique", 9) > 355 and current_line:
            lines.append(current_line)
            current_line = word
        else:
            current_line = candidate
    if current_line:
        lines.append(current_line)
    for line in lines[:4]:
        text_object.textLine(line)
    document.drawText(text_object)

    document.setStrokeColor(colors.HexColor("#514A58"))
    document.setLineWidth(0.7)
    document.line(text_x, 103, 545, 103)
    document.line(580, 103, 730, 103)
    document.setFont("Helvetica", 8)
    document.setFillColor(colors.HexColor("#6B626E"))
    document.drawString(text_x, 88, "Artist signature - Jeffrey McKay")
    document.drawString(580, 88, "Date")
    document.setFont("Helvetica", 7)
    document.drawRightString(730, 51, f"Generated by BlackCanvasAI  |  {certificate_id}")
    document.showPage()
    document.save()
    return FileResponse(certificate_path, media_type="application/pdf", filename=certificate_path.name)


@app.get("/api/artworks/{artwork_id}/sale-receipt")
def artwork_sale_receipt(artwork_id: int) -> FileResponse:
    matches = rows(
        "SELECT id, title, collection, dimensions, medium, sale_status, sale_price, sold_date, "
        "sales_channel, buyer_name, sale_notes, filename FROM artworks WHERE id = ?", (artwork_id,)
    )
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    artwork = matches[0]
    if artwork["sale_status"] != "Sold" or float(artwork["sale_price"] or 0) <= 0:
        raise HTTPException(status_code=400, detail="Record this artwork as sold before creating a receipt")

    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "-", artwork["title"]).strip("-") or "artwork"
    receipt_dir = DATA_DIR / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{safe_title}-sale-receipt.pdf"
    receipt_number = f"BC-SALE-{artwork_id:05d}-{artwork['sold_date'].replace('-', '')}"
    document = canvas.Canvas(str(receipt_path), pagesize=letter)
    page_width, page_height = letter
    document.setTitle(f"Artwork Sale Receipt - {artwork['title']}")
    document.setAuthor("BlackCanvasAI for Jeffrey McKay")

    document.setFillColor(colors.HexColor("#F7F3EA"))
    document.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    document.setFillColor(colors.HexColor("#17131F"))
    document.rect(0, page_height - 144, page_width, 144, fill=1, stroke=0)
    document.setFillColor(colors.HexColor("#B58AF8"))
    document.setFont("Helvetica-Bold", 11)
    document.drawString(52, page_height - 54, "BLACK CANVAS ART STUDIO")
    document.setFillColor(colors.white)
    document.setFont("Helvetica-Bold", 27)
    document.drawString(52, page_height - 92, "ARTWORK SALE RECEIPT")
    document.setFont("Helvetica", 9)
    document.setFillColor(colors.HexColor("#D8D2DF"))
    document.drawString(52, page_height - 116, f"Receipt {receipt_number}")

    image_path = UPLOAD_DIR / artwork["filename"]
    if image_path.is_file():
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((180, 210), Image.Resampling.LANCZOS)
            image_buffer = io.BytesIO()
            image.save(image_buffer, format="JPEG", quality=90)
            image_width, image_height = image.size
        document.setFillColor(colors.white)
        document.rect(52, 397, 198, 228, fill=1, stroke=0)
        document.drawImage(
            ImageReader(image_buffer), 61 + (180 - image_width) / 2, 406 + (210 - image_height) / 2,
            width=image_width, height=image_height, mask="auto",
        )

    document.setFillColor(colors.HexColor("#6C4D88"))
    document.setFont("Helvetica-Bold", 9)
    document.drawString(285, 602, "ARTWORK")
    document.setFillColor(colors.HexColor("#17131F"))
    document.setFont("Helvetica-Bold", 18)
    document.drawString(285, 574, artwork["title"][:34])
    document.setStrokeColor(colors.HexColor("#C8B995"))
    document.setLineWidth(0.8)
    document.line(285, 558, 560, 558)

    details = [
        ("Collection", artwork["collection"] or "Unsorted"),
        ("Dimensions", artwork["dimensions"] or "Not recorded"),
        ("Medium", artwork["medium"] or "Not recorded"),
        ("Date sold", artwork["sold_date"]),
        ("Sales channel", artwork["sales_channel"] or "Direct sale"),
        ("Buyer", artwork["buyer_name"] or "Private buyer"),
    ]
    y = 530
    for label, value in details:
        document.setFillColor(colors.HexColor("#786F7C"))
        document.setFont("Helvetica-Bold", 8)
        document.drawString(285, y, label.upper())
        document.setFillColor(colors.HexColor("#17131F"))
        document.setFont("Helvetica", 9)
        value_text = str(value)
        if document.stringWidth(value_text, "Helvetica", 9) <= 175:
            document.drawString(385, y, value_text)
        else:
            words = value_text.split()
            first_line = ""
            while words:
                candidate = f"{first_line} {words[0]}".strip()
                if first_line and document.stringWidth(candidate, "Helvetica", 9) > 175:
                    break
                first_line = candidate
                words.pop(0)
            document.drawString(385, y, first_line)
            document.drawString(385, y - 12, " ".join(words)[:38])
        y -= 31

    document.setFillColor(colors.white)
    document.roundRect(52, 270, 508, 92, 8, fill=1, stroke=0)
    document.setFillColor(colors.HexColor("#6C4D88"))
    document.setFont("Helvetica-Bold", 9)
    document.drawString(72, 332, "PAYMENT SUMMARY")
    document.setFillColor(colors.HexColor("#514A58"))
    document.setFont("Helvetica", 11)
    document.drawString(72, 298, artwork["title"][:44])
    document.setFillColor(colors.HexColor("#17131F"))
    document.setFont("Helvetica-Bold", 18)
    document.drawRightString(540, 298, f"${float(artwork['sale_price']):,.2f}")

    notes = artwork["sale_notes"].strip()
    if notes:
        document.setFillColor(colors.HexColor("#6C4D88"))
        document.setFont("Helvetica-Bold", 9)
        document.drawString(52, 230, "SALE NOTES")
        document.setFillColor(colors.HexColor("#514A58"))
        document.setFont("Helvetica", 9)
        text_object = document.beginText(52, 209)
        text_object.setLeading(13)
        current = ""
        lines: list[str] = []
        for word in notes.split():
            candidate = f"{current} {word}".strip()
            if document.stringWidth(candidate, "Helvetica", 9) > 500 and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for line in lines[:3]:
            text_object.textLine(line)
        document.drawText(text_object)

    document.setStrokeColor(colors.HexColor("#9A7342"))
    document.line(52, 118, 560, 118)
    document.setFillColor(colors.HexColor("#17131F"))
    document.setFont("Helvetica-Bold", 10)
    document.drawString(52, 92, "Thank you for supporting independent Black art.")
    document.setFillColor(colors.HexColor("#6B626E"))
    document.setFont("Helvetica", 8)
    document.drawString(52, 70, "Artist: Jeffrey McKay  |  Black Canvas Art Studio")
    document.drawRightString(560, 70, "Generated securely by BlackCanvasAI")
    document.showPage()
    document.save()
    return FileResponse(receipt_path, media_type="application/pdf", filename=receipt_path.name)


@app.get("/api/artworks/{artwork_id}/gallery-label")
def artwork_gallery_label(artwork_id: int) -> FileResponse:
    matches = rows(
        "SELECT id, title, collection, notes, dimensions, medium, price, sale_status "
        "FROM artworks WHERE id = ?", (artwork_id,)
    )
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    artwork = matches[0]
    if not artwork["medium"].strip() or not artwork["dimensions"].strip():
        raise HTTPException(status_code=400, detail="Add dimensions and medium before creating a gallery label")

    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "-", artwork["title"]).strip("-") or "artwork"
    label_dir = DATA_DIR / "gallery-labels"
    label_dir.mkdir(parents=True, exist_ok=True)
    label_path = label_dir / f"{safe_title}-gallery-label.pdf"
    document = canvas.Canvas(str(label_path), pagesize=letter)
    page_width, page_height = letter
    document.setTitle(f"Gallery Label - {artwork['title']}")
    document.setAuthor("BlackCanvasAI for Jeffrey McKay")

    label_width, label_height = 360, 252
    label_x = (page_width - label_width) / 2
    label_y = (page_height - label_height) / 2
    document.setFillColor(colors.white)
    document.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    document.setDash(3, 3)
    document.setStrokeColor(colors.HexColor("#B8B2BB"))
    document.setLineWidth(0.5)
    document.rect(label_x, label_y, label_width, label_height, fill=0, stroke=1)
    document.setDash()

    content_x = label_x + 28
    content_right = label_x + label_width - 28
    document.setFillColor(colors.HexColor("#6C4D88"))
    document.setFont("Helvetica-Bold", 8)
    document.drawString(content_x, label_y + 215, "BLACK CANVAS ART STUDIO")
    document.setFillColor(colors.HexColor("#17131F"))
    title = artwork["title"].strip() or "Untitled Artwork"
    title_size = 21 if document.stringWidth(title, "Helvetica-Bold", 21) <= label_width - 56 else 16
    document.setFont("Helvetica-Bold", title_size)
    document.drawString(content_x, label_y + 180, title[:44])
    document.setFont("Helvetica-Oblique", 10)
    document.setFillColor(colors.HexColor("#514A58"))
    document.drawString(content_x, label_y + 158, "Jeffrey McKay")
    document.setStrokeColor(colors.HexColor("#B59258"))
    document.setLineWidth(1)
    document.line(content_x, label_y + 143, content_right, label_y + 143)

    document.setFillColor(colors.HexColor("#17131F"))
    document.setFont("Helvetica", 9)
    document.drawString(content_x, label_y + 121, artwork["collection"] or "Unsorted")
    document.drawString(content_x, label_y + 104, artwork["medium"][:58])
    document.drawString(content_x, label_y + 87, artwork["dimensions"][:45])

    statement = artwork["notes"].strip()
    if statement:
        document.setFillColor(colors.HexColor("#514A58"))
        document.setFont("Helvetica", 8)
        text_object = document.beginText(content_x, label_y + 62)
        text_object.setLeading(11)
        current = ""
        lines: list[str] = []
        for word in statement.split():
            candidate = f"{current} {word}".strip()
            if document.stringWidth(candidate, "Helvetica", 8) > label_width - 56 and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for line in lines[:3]:
            text_object.textLine(line)
        document.drawText(text_object)

    if artwork["sale_status"] != "Not for sale" and float(artwork["price"] or 0) > 0:
        document.setFillColor(colors.HexColor("#17131F"))
        document.setFont("Helvetica-Bold", 10)
        document.drawRightString(content_right, label_y + 22, f"${float(artwork['price']):,.0f}")
    document.setFillColor(colors.HexColor("#9A929E"))
    document.setFont("Helvetica", 6)
    document.drawCentredString(page_width / 2, label_y - 14, "Cut along the dotted line - finished label size: 5 x 3.5 inches")
    document.showPage()
    document.save()
    return FileResponse(label_path, media_type="application/pdf", filename=label_path.name)


@app.get("/api/artworks/{artwork_id}/buyer-kit")
def artwork_buyer_kit(artwork_id: int) -> dict:
    matches = rows(
        "SELECT id, title, collection, notes, dimensions, medium, sale_status, sale_price, sold_date, "
        "sales_channel, buyer_name FROM artworks WHERE id = ?", (artwork_id,)
    )
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    artwork = matches[0]
    if artwork["sale_status"] != "Sold":
        raise HTTPException(status_code=400, detail="Record this artwork as sold before creating a buyer kit")

    buyer = artwork["buyer_name"].strip() or "there"
    title = artwork["title"].strip() or "your new artwork"
    collection = artwork["collection"].strip() or "Black Canvas"
    medium = artwork["medium"].strip() or "original artwork"
    dimensions = artwork["dimensions"].strip()
    thank_you = (
        f"Hi {buyer},\n\nThank you for purchasing {title} from my {collection} collection. "
        "It means a great deal to know this piece has found a home with you. "
        "Your support helps me keep building bold, imaginative work centered on Black creativity and possibility.\n\n"
        "I hope the artwork brings energy, meaning, and inspiration to your space for years to come. "
        "Please feel free to share a photo once it is displayed.\n\nWith gratitude,\nJeffrey McKay\nBlack Canvas Art Studio"
    )
    medium_lower = medium.lower()
    if "canvas" in medium_lower or "acrylic" in medium_lower or "oil" in medium_lower:
        care = (
            f"Care instructions for {title}:\n\n"
            "- Display away from direct sunlight and strong heat sources.\n"
            "- Dust gently with a clean, dry, soft cloth. Do not use water or household cleaners.\n"
            "- Hold and move the artwork by its outer edges or frame.\n"
            "- Keep the Certificate of Authenticity in a safe place."
        )
    elif "print" in medium_lower or "paper" in medium_lower:
        care = (
            f"Care instructions for {title}:\n\n"
            "- Frame behind UV-protective glass or acrylic when possible.\n"
            "- Use acid-free matting and backing materials.\n"
            "- Keep away from direct sunlight, moisture, and high humidity.\n"
            "- Handle with clean, dry hands and keep the Certificate of Authenticity safe."
        )
    else:
        care = (
            f"Care instructions for {title}:\n\n"
            "- Keep away from direct sunlight, moisture, and extreme temperatures.\n"
            "- Dust only with a clean, dry, soft cloth.\n"
            "- Handle carefully by the edges and avoid touching the artwork surface.\n"
            "- Store the Certificate of Authenticity in a safe place."
        )
    artwork_line = f"{title} - {medium}"
    if dimensions:
        artwork_line += f", {dimensions}"
    checklist = [
        f"Confirm artwork: {artwork_line}",
        "Inspect and photograph the artwork before packing",
        "Include the signed Certificate of Authenticity",
        "Include printed care instructions and thank-you note",
        "Protect corners and artwork surface",
        "Use sturdy packaging with no movement inside",
        "Photograph the sealed package",
        "Send pickup or tracking information to the buyer",
    ]
    return {
        "artwork_title": title,
        "buyer_name": artwork["buyer_name"].strip(),
        "thank_you": thank_you,
        "care_instructions": care,
        "packing_checklist": checklist,
    }


@app.get("/api/artworks/{artwork_id}/content-kit")
def artwork_content_kit(artwork_id: int) -> dict:
    matches = rows("SELECT id, title, collection, tags, notes, dimensions, medium, price, sale_status, listing_url FROM artworks WHERE id = ?", (artwork_id,))
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    artwork = matches[0]
    title = artwork["title"].strip()
    collection = artwork["collection"].strip()
    notes = artwork["notes"].strip() or f"An original {collection} artwork created by Jeffrey McKay."
    raw_tags = [tag.strip() for tag in artwork["tags"].split(",") if tag.strip()]
    collection_tones = {
        "AfroNova": ("future royalty, ancestral power, and Black imagination", "visionary"),
        "Quiet Nova": ("stillness, honest emotion, and quiet strength", "reflective"),
        "GraffitiX": ("raw street energy, layered symbolism, and fearless expression", "electric"),
        "Unsorted": ("original vision, story, and creative expression", "distinctive"),
    }
    story, tone = collection_tones.get(collection, collection_tones["Unsorted"])
    tone_article = "an" if tone[:1].lower() in "aeiou" else "a"
    hashtag_words = raw_tags + [collection, "BlackArt", "ContemporaryArt", "OriginalArtwork", "ArtCollector"]
    hashtags: list[str] = []
    for tag in hashtag_words:
        clean = re.sub(r"[^A-Za-z0-9]", "", tag)
        if clean and clean.lower() not in {item.lower() for item in hashtags}:
            hashtags.append(clean)
    hashtag_line = " ".join(f"#{tag}" for tag in hashtags[:12])
    etsy_tags = raw_tags + [collection, "Black wall art", "original art", "art collector gift"]
    etsy_tags = list(dict.fromkeys(tag[:20] for tag in etsy_tags if tag))[:13]
    listing_title = f"{title} | {collection} Original Art | Contemporary Black Wall Art"[:140]
    listing_facts = [
        f"Size: {artwork['dimensions']}" if artwork["dimensions"] else "",
        f"Medium: {artwork['medium']}" if artwork["medium"] else "",
        f"Price: ${artwork['price']:,.0f}" if artwork["price"] else "",
    ]
    listing_facts_text = "\n".join(item for item in listing_facts if item)
    listing_facts_block = f"{listing_facts_text}\n\n" if listing_facts_text else ""
    gallery_settings = get_gallery_settings()
    pinterest_title = f"{title} | {collection} Contemporary Black Art"[:100]
    pinterest_description = (
        f'“{title}” is {tone_article} {tone} work from Jeffrey McKay’s {collection} collection, '
        f"exploring {story}. {notes} Discover more original artwork from Black Canvas."
    )[:800]
    pinterest_topics = list(dict.fromkeys(
        raw_tags + [collection, "Black art", "Contemporary art", "Wall art", "Art collectors"]
    ))[:10]
    pinterest_alt_text = (
        f'Artwork titled “{title}” by Jeffrey McKay from the {collection} collection. {notes}'
    )[:500]
    return {
        "artwork_title": title,
        "instagram": (
            f"{title}. {tone_article.capitalize()} {tone} piece from the {collection} collection, shaped by {story}.\n\n"
            f"{notes}\n\nWhat feeling or story does this piece bring up for you?\n\n{hashtag_line}"
        ),
        "tiktok_hook": f"Watch how “{title}” turns {story} into a finished work of art.",
        "tiktok_caption": f"From the first idea to the final detail—meet “{title}” from my {collection} collection. {hashtag_line}",
        "listing_title": listing_title,
        "listing_description": (
            f'“{title}” is an original piece from the {collection} collection, exploring {story}.\n\n'
            f"Artwork story:\n{notes}\n\n"
            f"{listing_facts_block}"
            "This statement artwork is designed for collectors who value distinctive contemporary Black art, "
            "intentional storytelling, and work with a strong visual presence.\n\n"
            "Please review the artwork photographs and listing details carefully for size, materials, framing, "
            "and shipping information before purchasing."
        ),
        "listing_tags": etsy_tags,
        "pinterest_title": pinterest_title,
        "pinterest_description": pinterest_description,
        "pinterest_topics": pinterest_topics,
        "pinterest_alt_text": pinterest_alt_text,
        "pinterest_destination": artwork.get("listing_url", "") or gallery_settings.get("shop_url", ""),
        "pinterest_profile": gallery_settings.get("pinterest_url", ""),
        "pinterest_board": collection if collection != "Unsorted" else "Black Canvas Art",
    }


def artwork_image_record(artwork_id: int) -> tuple[dict, Path]:
    matches = rows(
        "SELECT id, title, collection, tags, notes, dimensions, medium, price, sale_status, "
        "gallery_visible, filename FROM artworks WHERE id = ?",
        (artwork_id,),
    )
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    image_path = UPLOAD_DIR / matches[0]["filename"]
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Artwork image file not found")
    return matches[0], image_path


def prepared_image_data_url(image_path: Path) -> str:
    """Create a cost-conscious image input while preserving enough detail for visual analysis."""
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).copy()
        if getattr(image, "is_animated", False):
            image.seek(0)
        if image.mode == "RGBA":
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def artwork_visual_request_body(
    artwork: dict, image_data_url: str, style: dict | None = None, existing_titles: list[str] | None = None
) -> dict:
    """Build a vision-first request; catalog metadata is secondary evidence, never the subject."""
    catalog_context = {
        "current_title": artwork.get("title") or "",
        "current_collection": artwork.get("collection") or "Unsorted",
        "current_tags": artwork.get("tags") or "",
        "current_notes": artwork.get("notes") or "",
    }
    style_context = style or {}
    unavailable_titles = [title for title in (existing_titles or []) if title][:100]
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "visual_summary": {"type": "string"},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "collection": {"type": "string", "enum": ["AfroNova", "Quiet Nova", "GraffitiX", "Unsorted"]},
            "generated_prompt": {"type": "string"},
        },
        "required": ["title", "visual_summary", "description", "tags", "collection", "generated_prompt"],
        "additionalProperties": False,
    }
    instructions = (
        "You are Black Canvas AI's expert artwork analyst and prompt reverse-engineer. "
        "Analyze the actual pixels before reading the catalog context. Identify the visible subject, crop, pose, "
        "facial or object features, palette, lighting, background, materials, mark-making, mood, and composition. "
        "Never replace a close-up face with a full-body figure, never invent clothing or symbols that are not visible, "
        "and never use the filename or an old generic title as visual evidence. Suggest a distinctive artwork title, "
        "an accurate collector-friendly description, 8 to 14 useful comma-free tags, the best collection, and one "
        "detailed copy-ready image prompt that could recreate the visible image. The prompt must start directly with "
        "the subject; do not include '/imagine prompt:' or generator codes such as --ar, --raw, --style, or --v. "
        "Use the collection Style Bible only as a restrained finishing layer after the image has been described accurately. "
        "The suggested title must be distinctive and must not repeat any title in the supplied unavailable-title list."
    )
    return {
        "model": OPENAI_MODEL,
        "instructions": instructions,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": (
                    "First inspect the attached artwork itself. Then use this secondary catalog context only to refine "
                    f"the result: {json.dumps(catalog_context)}. Relevant Style Bible: {json.dumps(style_context)}. "
                    f"Unavailable titles: {json.dumps(unavailable_titles)}"
                )},
                {"type": "input_image", "image_url": image_data_url, "detail": "high"},
            ],
        }],
        "text": {"format": {"type": "json_schema", "name": "artwork_visual_analysis", "strict": True, "schema": schema}},
        "max_output_tokens": 1400,
        "store": False,
    }


def analyze_artwork_pixels(artwork: dict, image_path: Path) -> dict:
    api_key = openai_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Connect the Live Agent first so Black Canvas AI can see the artwork.")
    _, calls = openai_call_count()
    if calls >= OPENAI_MONTHLY_CALL_LIMIT:
        raise HTTPException(status_code=429, detail="The monthly Live Agent safety limit has been reached.")

    style = {}
    style_rows = rows("SELECT content FROM styles WHERE name = ?", (artwork.get("collection") or "",))
    if style_rows:
        try:
            style = json.loads(style_rows[0]["content"])
        except (TypeError, json.JSONDecodeError):
            style = {}
    existing_titles = [
        item["title"] for item in rows("SELECT title FROM artworks WHERE id != ? ORDER BY id DESC", (artwork["id"],))
    ]
    request_body = artwork_visual_request_body(
        artwork, prepared_image_data_url(image_path), style, existing_titles
    )
    request = UrlRequest(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=75) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"The visual analyst could not respond: {detail[:240]}")
    except URLError:
        raise HTTPException(status_code=502, detail="The visual analyst could not reach OpenAI. Please try again.")

    output = openai_response_text(result)
    if not output:
        raise HTTPException(status_code=502, detail="The visual analyst returned an empty result. Please try again.")
    try:
        analysis = json.loads(output)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="The visual analyst returned an unreadable result. Please try again.")
    analysis["generated_prompt"] = clean_copy_ready_prompt(str(analysis.get("generated_prompt") or ""))
    analysis["tags"] = [str(tag).strip() for tag in analysis.get("tags", []) if str(tag).strip()][:14]
    record_openai_call("Artwork image analysis", result)
    return analysis


@app.post("/api/artworks/{artwork_id}/visual-analysis")
def artwork_visual_analysis(artwork_id: int) -> dict:
    artwork, image_path = artwork_image_record(artwork_id)
    return analyze_artwork_pixels(artwork, image_path)


@app.get("/api/artworks/{artwork_id}/print-info")
def artwork_print_info(artwork_id: int) -> dict:
    artwork, image_path = artwork_image_record(artwork_id)
    with Image.open(image_path) as image:
        width, height = ImageOps.exif_transpose(image).size
        dpi_value = image.info.get("dpi", (0, 0))
    current_dpi = round(float(dpi_value[0])) if isinstance(dpi_value, (tuple, list)) and dpi_value else 0
    return {
        "artwork_title": artwork["title"],
        "pixel_width": width,
        "pixel_height": height,
        "current_dpi": current_dpi,
        "max_width_300": round(width / 300, 2),
        "max_height_300": round(height / 300, 2),
        "aspect_ratio": width / height,
    }


@app.post("/api/artworks/{artwork_id}/print-export")
def export_artwork_for_print(artwork_id: int, payload: PrintExportPayload) -> FileResponse:
    if payload.width_inches <= 0 or payload.height_inches <= 0:
        raise HTTPException(status_code=400, detail="Print dimensions must be greater than zero")
    artwork, image_path = artwork_image_record(artwork_id)
    required_width = round(payload.width_inches * 300)
    required_height = round(payload.height_inches * 300)
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source)
        width, height = image.size
        original_ratio = width / height
        requested_ratio = required_width / required_height
        if abs(original_ratio - requested_ratio) / original_ratio > 0.025:
            raise HTTPException(status_code=400, detail="The requested size does not match this image’s shape")
        if width < required_width or height < required_height:
            raise HTTPException(
                status_code=400,
                detail=f"This file needs at least {required_width} × {required_height} pixels for that size at 300 DPI",
            )
        prepared = image.copy()
        if prepared.size != (required_width, required_height):
            prepared = prepared.resize((required_width, required_height), Image.Resampling.LANCZOS)
        if prepared.mode not in ("RGB", "RGBA"):
            prepared = prepared.convert("RGBA" if "transparency" in source.info else "RGB")
        export_dir = DATA_DIR / "print_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[^A-Za-z0-9_-]+", "-", artwork["title"]).strip("-") or "artwork"
        export_path = export_dir / f"{safe_title}-{required_width}x{required_height}-300dpi.png"
        prepared.save(export_path, format="PNG", dpi=(300, 300), optimize=True)
    return FileResponse(export_path, media_type="image/png", filename=export_path.name)


def listing_readiness_result(artwork_id: int) -> dict:
    matches = rows(
        "SELECT id, title, tags, notes, dimensions, medium, price, sale_status, filename "
        "FROM artworks WHERE id = ?", (artwork_id,)
    )
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    artwork = matches[0]
    image_path = UPLOAD_DIR / artwork["filename"]
    pixel_width = pixel_height = 0
    if image_path.is_file():
        with Image.open(image_path) as image:
            pixel_width, pixel_height = ImageOps.exif_transpose(image).size
    tag_count = len([tag for tag in artwork["tags"].split(",") if tag.strip()])
    checks = [
        {"key": "title", "label": "Clear artwork title", "ready": len(artwork["title"].strip()) >= 3,
         "detail": "Give the piece a recognizable title."},
        {"key": "description", "label": "Artwork story or description", "ready": len(artwork["notes"].strip()) >= 30,
         "detail": "Add at least a short paragraph explaining the piece."},
        {"key": "tags", "label": "Searchable tags", "ready": tag_count >= 3,
         "detail": f"Add at least 3 tags. Current total: {tag_count}."},
        {"key": "dimensions", "label": "Dimensions", "ready": bool(artwork["dimensions"].strip()),
         "detail": "Add the physical or intended print size."},
        {"key": "medium", "label": "Medium or materials", "ready": bool(artwork["medium"].strip()),
         "detail": "Example: acrylic on canvas or archival art print."},
        {"key": "price", "label": "Selling price", "ready": float(artwork["price"] or 0) > 0,
         "detail": "Add a price greater than $0."},
        {"key": "image", "label": "High-resolution listing image", "ready": min(pixel_width, pixel_height) >= 1500,
         "detail": f"Current image: {pixel_width:,} × {pixel_height:,} pixels. Aim for at least 1,500 pixels on the shorter side."},
    ]
    completed = sum(1 for check in checks if check["ready"])
    return {
        "artwork_id": artwork_id,
        "artwork_title": artwork["title"],
        "sale_status": artwork["sale_status"],
        "completed": completed,
        "total": len(checks),
        "percent": round(completed / len(checks) * 100),
        "ready_to_list": completed == len(checks),
        "checks": checks,
    }


@app.get("/api/artworks/{artwork_id}/listing-readiness")
def artwork_listing_readiness(artwork_id: int) -> dict:
    return listing_readiness_result(artwork_id)


@app.post("/api/artworks/{artwork_id}/mark-ready")
def mark_artwork_ready(artwork_id: int) -> dict:
    result = listing_readiness_result(artwork_id)
    if not result["ready_to_list"]:
        raise HTTPException(status_code=400, detail="Complete the listing checklist first")
    execute("UPDATE artworks SET sale_status = 'Ready to list' WHERE id = ?", (artwork_id,))
    result["sale_status"] = "Ready to list"
    return result


@app.post("/api/artworks/{artwork_id}/record-sale")
def record_artwork_sale(artwork_id: int, payload: SaleRecordPayload) -> dict:
    if payload.sale_price <= 0:
        raise HTTPException(status_code=400, detail="Sale price must be greater than zero")
    try:
        datetime.strptime(payload.sold_date, "%Y-%m-%d")
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Use a valid sale date") from error
    channel = payload.sales_channel.strip()
    if not channel:
        raise HTTPException(status_code=400, detail="Choose a sales channel")
    with connect() as db:
        cursor = db.execute(
            "UPDATE artworks SET sale_status = 'Sold', sale_price = ?, sold_date = ?, sales_channel = ?, buyer_name = ?, sale_notes = ? WHERE id = ?",
            (payload.sale_price, payload.sold_date, channel, payload.buyer_name.strip(), payload.notes.strip(), artwork_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Artwork not found")
    return {"status": "Sold", "sale_price": payload.sale_price, "sold_date": payload.sold_date,
            "sales_channel": channel, "buyer_name": payload.buyer_name.strip(), "notes": payload.notes.strip()}


@app.put("/api/artworks/{artwork_id}/price")
def update_artwork_price(artwork_id: int, payload: ArtworkPricePayload) -> dict:
    if payload.price <= 0:
        raise HTTPException(status_code=400, detail="Artwork price must be greater than zero")
    with connect() as db:
        cursor = db.execute("UPDATE artworks SET price = ? WHERE id = ?", (round(payload.price, 2), artwork_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Artwork not found")
    return {"id": artwork_id, "price": round(payload.price, 2)}


@app.get("/api/artworks/{artwork_id}/pricing")
def get_artwork_pricing(artwork_id: int) -> dict:
    matches = rows("SELECT price, pricing_data FROM artworks WHERE id = ?", (artwork_id,))
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    try:
        saved = json.loads(matches[0]["pricing_data"] or "{}")
    except json.JSONDecodeError:
        saved = {}
    return {"price": float(matches[0]["price"] or 0), "pricing": saved}


@app.put("/api/artworks/{artwork_id}/pricing")
def save_artwork_pricing(artwork_id: int, payload: ArtworkPricingPayload) -> dict:
    values = payload.model_dump()
    if any(float(value) < 0 for value in values.values()):
        raise HTTPException(status_code=400, detail="Pricing values cannot be negative")
    if payload.fees_percent >= 100:
        raise HTTPException(status_code=400, detail="Selling fees must be less than 100 percent")
    if payload.recommended_price <= 0:
        raise HTTPException(status_code=400, detail="Recommended price must be greater than zero")
    with connect() as db:
        cursor = db.execute(
            "UPDATE artworks SET price = ?, pricing_data = ? WHERE id = ?",
            (round(payload.recommended_price, 2), json.dumps(values), artwork_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Artwork not found")
    return {"id": artwork_id, "price": round(payload.recommended_price, 2), "pricing": values}


@app.post("/api/artworks/{artwork_id}/fulfillment")
def update_artwork_fulfillment(artwork_id: int, payload: FulfillmentPayload) -> dict:
    allowed = {"Not started", "Packing", "Ready to ship", "Shipped", "Delivered", "Local pickup complete"}
    status = payload.status.strip()
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Choose a valid fulfillment status")
    carrier = payload.carrier.strip()
    tracking_number = payload.tracking_number.strip()
    if status == "Shipped" and not tracking_number:
        raise HTTPException(status_code=400, detail="Add a tracking number before marking this order shipped")
    with connect() as db:
        artwork = db.execute("SELECT sale_status FROM artworks WHERE id = ?", (artwork_id,)).fetchone()
        if not artwork:
            raise HTTPException(status_code=404, detail="Artwork not found")
        if artwork["sale_status"] != "Sold":
            raise HTTPException(status_code=400, detail="Record the artwork as sold before tracking fulfillment")
        db.execute(
            "UPDATE artworks SET fulfillment_status = ?, shipping_carrier = ?, tracking_number = ? WHERE id = ?",
            (status, carrier, tracking_number, artwork_id),
        )
    return {"status": status, "carrier": carrier, "tracking_number": tracking_number}


@app.get("/api/artworks/{artwork_id}/seller-package")
def download_seller_package(artwork_id: int) -> FileResponse:
    readiness = listing_readiness_result(artwork_id)
    if not readiness["ready_to_list"]:
        raise HTTPException(status_code=400, detail="Complete the listing checklist before creating a seller package")
    artwork, image_path = artwork_image_record(artwork_id)
    details = rows(
        "SELECT title, collection, tags, notes, dimensions, medium, price, sale_status FROM artworks WHERE id = ?",
        (artwork_id,),
    )[0]
    kit = artwork_content_kit(artwork_id)
    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "-", artwork["title"]).strip("-") or "artwork"
    package_dir = DATA_DIR / "seller_packages"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / f"{safe_title}-seller-package.zip"

    listing_text = (
        f"LISTING TITLE\n{kit['listing_title']}\n\n"
        f"PRICE\n${details['price']:,.2f}\n\n"
        f"DIMENSIONS\n{details['dimensions']}\n\n"
        f"MEDIUM\n{details['medium']}\n\n"
        f"DESCRIPTION\n{kit['listing_description']}\n\n"
        f"TAGS\n{', '.join(kit['listing_tags'])}\n"
    )
    social_text = (
        f"INSTAGRAM\n{kit['instagram']}\n\n"
        f"TIKTOK HOOK\n{kit['tiktok_hook']}\n\n"
        f"TIKTOK CAPTION\n{kit['tiktok_caption']}\n"
    )
    guide_text = (
        "BLACKCANVASAI SELLER PACKAGE\n\n"
        "1. Review and personalize all wording before publishing.\n"
        "2. Confirm price, dimensions, medium, framing, inventory, and shipping details.\n"
        "3. Use the original image for archiving and the 300-DPI PNG for print preparation.\n"
        "4. Marketplace requirements vary; preview the final listing before publishing.\n"
    )
    with Image.open(image_path) as source:
        prepared = ImageOps.exif_transpose(source).copy()
        if prepared.mode not in ("RGB", "RGBA"):
            prepared = prepared.convert("RGBA" if "transparency" in source.info else "RGB")
        print_buffer = io.BytesIO()
        prepared.save(print_buffer, format="PNG", dpi=(300, 300), optimize=True)

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.write(image_path, f"images/{safe_title}-original{image_path.suffix.lower()}")
        package.writestr(f"images/{safe_title}-300dpi.png", print_buffer.getvalue())
        package.writestr("listing-copy.txt", listing_text)
        package.writestr("social-media-copy.txt", social_text)
        package.writestr("artwork-details.json", json.dumps(details, indent=2))
        package.writestr("README.txt", guide_text)
    return FileResponse(package_path, media_type="application/zip", filename=package_path.name)


@app.post("/api/artworks")
def create_artwork(payload: ArtworkPayload) -> dict:
    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp|gif));base64,(.+)", payload.data_url, re.DOTALL)
    if not match:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    image_bytes = base64.b64decode(match.group(2), validate=True)
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be smaller than 10 MB")
    listing_url = payload.listing_url.strip()
    if listing_url and not re.match(r"https://[^\s/]+(?:/|$)", listing_url, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="The shop or product link needs to begin with https://")
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}[match.group(1)]
    filename = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(image_bytes)
    artwork_id = execute(
        "INSERT INTO artworks(title, collection, tags, notes, favorite, dimensions, medium, price, sale_status, gallery_visible, listing_url, filename) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (payload.title.strip(), payload.collection, payload.tags.strip(), payload.notes.strip(), int(payload.favorite),
         payload.dimensions.strip(), payload.medium.strip(), max(payload.price, 0), payload.sale_status, int(payload.gallery_visible), listing_url, filename),
    )
    return {"id": artwork_id, "url": f"/uploads/{filename}"}


@app.patch("/api/artworks/{artwork_id}/favorite")
def favorite_artwork(artwork_id: int, favorite: bool) -> dict[str, bool]:
    execute("UPDATE artworks SET favorite = ? WHERE id = ?", (int(favorite), artwork_id))
    return {"favorite": favorite}


@app.put("/api/artworks/{artwork_id}")
def update_artwork(artwork_id: int, payload: ArtworkDetailsPayload) -> dict:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Artwork title is required")
    listing_url = payload.listing_url.strip()
    if listing_url and not re.match(r"https://[^\s/]+(?:/|$)", listing_url, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="The shop or product link needs to begin with https://")
    with connect() as db:
        cursor = db.execute(
            "UPDATE artworks SET title = ?, collection = ?, tags = ?, notes = ?, dimensions = ?, medium = ?, price = ?, sale_status = ?, gallery_visible = ?, listing_url = ? WHERE id = ?",
            (title, payload.collection, payload.tags.strip(), payload.notes.strip(), payload.dimensions.strip(),
             payload.medium.strip(), max(payload.price, 0), payload.sale_status, int(payload.gallery_visible), listing_url, artwork_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Artwork not found")
    return {"id": artwork_id, "title": title, "collection": payload.collection,
            "tags": payload.tags.strip(), "notes": payload.notes.strip(), "dimensions": payload.dimensions.strip(),
            "medium": payload.medium.strip(), "price": max(payload.price, 0), "sale_status": payload.sale_status,
            "gallery_visible": payload.gallery_visible, "listing_url": listing_url}


@app.delete("/api/artworks/{artwork_id}")
def delete_artwork(artwork_id: int) -> dict[str, str]:
    with connect() as db:
        item = db.execute("SELECT filename FROM artworks WHERE id = ?", (artwork_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Artwork not found")
        db.execute("DELETE FROM artworks WHERE id = ?", (artwork_id,))
    image_path = UPLOAD_DIR / item["filename"]
    if image_path.exists():
        image_path.unlink()
    return {"status": "removed"}


@app.get("/api/backup")
def download_backup() -> JSONResponse:
    return JSONResponse(
        backup_data(),
        headers={"Content-Disposition": "attachment; filename=blackcanvas-backup.json"},
    )


CHATGPT_IMPORT_CACHE = UPLOAD_DIR.parent / "chatgpt_import_candidates.json"

CHATGPT_PROMPT_WORDS = (
    "prompt", "midjourney", "dall-e", "dalle", "image generator", "image prompt",
    "style bible", "listing title", "listing description", "listing tags", "caption",
    "content plan", "creative brief", "brand voice",
)
CHATGPT_VISUAL_WORDS = (
    "artwork", "portrait", "painting", "illustration", "canvas", "graffiti", "afronova",
    "quiet nova", "graffitix", "afrofutur", "composition", "photograph", "visual",
)


def chatgpt_candidate_is_prompt(candidate: dict) -> bool:
    """Keep useful creative directions while leaving ordinary chat out of auto-save."""
    text = str(candidate.get("text") or "").strip()
    if len(text) < 35:
        return False
    searchable = text.lower()
    prompt_hits = sum(word in searchable for word in CHATGPT_PROMPT_WORDS)
    visual_hits = sum(word in searchable for word in CHATGPT_VISUAL_WORDS)
    action = bool(re.match(r"^\s*(create|generate|write|design|develop|draft|make|give me|help me|produce|build|compose|turn|rewrite|imagine|describe|plan|outline)\b", text, re.IGNORECASE))
    role = str(candidate.get("role") or "user")
    if role == "assistant":
        return prompt_hits > 0 or (visual_hits >= 2 and len(text) >= 120)
    return prompt_hits > 0 or (action and visual_hits > 0)


def auto_import_chatgpt_candidates(candidates: list[dict]) -> tuple[int, int]:
    detected = 0
    imported = 0
    with connect() as db:
        for candidate in candidates:
            if not chatgpt_candidate_is_prompt(candidate):
                continue
            detected += 1
            title = str(candidate.get("conversation") or "ChatGPT prompt")[:120]
            cursor = db.execute(
                "INSERT OR IGNORE INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, 'ChatGPT Import', ?, 0, 'chatgpt', 0)",
                (title, str(candidate.get("text") or "").strip()),
            )
            imported += max(cursor.rowcount, 0)
    return detected, imported


def chatgpt_candidates(conversations: list[dict]) -> list[dict[str, str | float]]:
    candidates: list[dict[str, str | float]] = []
    seen: set[str] = set()
    for conversation in conversations:
        conversation_title = str(conversation.get("title") or "Untitled conversation")
        for node_id, node in (conversation.get("mapping") or {}).items():
            message = (node or {}).get("message") or {}
            role = str((message.get("author") or {}).get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            parts = (message.get("content") or {}).get("parts") or []
            text = "\n".join(part for part in parts if isinstance(part, str)).strip()
            if len(text) < 20 or text in seen:
                continue
            seen.add(text)
            candidate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{conversation.get('id', '')}:{node_id}"))
            candidates.append({
                "id": candidate_id,
                "conversation": conversation_title,
                "text": text,
                "role": role,
                "created_at": float(message.get("create_time") or 0),
            })
    candidates.sort(key=lambda item: float(item["created_at"]), reverse=True)
    return candidates[:1000]


@app.post("/api/chatgpt/import-preview")
async def preview_chatgpt_export(export_file: UploadFile = File(...)) -> dict:
    try:
        if (export_file.filename or "").lower().endswith(".zip"):
            await export_file.seek(0)
            with zipfile.ZipFile(export_file.file) as archive:
                conversation_names = sorted(
                    name for name in archive.namelist()
                    if re.fullmatch(r"conversations(?:-\d+)?\.json", Path(name).name, flags=re.IGNORECASE)
                )
                if not conversation_names:
                    raise ValueError("Conversation history files were not found in that ZIP")
                history_size = sum(archive.getinfo(name).file_size for name in conversation_names)
                if history_size > 500 * 1024 * 1024:
                    raise ValueError("The conversation history is too large to scan safely")
                conversations = []
                for conversation_name in conversation_names:
                    history_part = json.loads(archive.read(conversation_name))
                    if not isinstance(history_part, list):
                        raise ValueError(f"{conversation_name} does not contain a conversation list")
                    conversations.extend(history_part)
        else:
            raw = await export_file.read(200 * 1024 * 1024 + 1)
            if len(raw) > 200 * 1024 * 1024:
                raise ValueError("That JSON export is too large to scan safely")
            conversations = json.loads(raw)
        if not isinstance(conversations, list):
            raise ValueError("The conversation export is not a list")
    except (ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail=f"Could not read that ChatGPT export: {error}") from error
    candidates = chatgpt_candidates(conversations)
    CHATGPT_IMPORT_CACHE.write_text(json.dumps(candidates), encoding="utf-8")
    return {"count": len(candidates), "candidates": candidates}


@app.post("/api/chatgpt/auto-import")
def auto_import_chatgpt_prompts() -> dict[str, int]:
    if not CHATGPT_IMPORT_CACHE.exists():
        raise HTTPException(status_code=400, detail="Upload the ChatGPT export first")
    candidates = json.loads(CHATGPT_IMPORT_CACHE.read_text(encoding="utf-8"))
    detected, imported = auto_import_chatgpt_candidates(candidates)
    return {"detected": detected, "imported": imported}


@app.get("/api/chatgpt/import-candidates")
def saved_chatgpt_candidates() -> dict:
    if not CHATGPT_IMPORT_CACHE.exists():
        return {"count": 0, "candidates": []}
    candidates = json.loads(CHATGPT_IMPORT_CACHE.read_text(encoding="utf-8"))
    return {"count": len(candidates), "candidates": candidates}


@app.post("/api/chatgpt/import-selected")
def import_chatgpt_prompts(payload: ChatGPTImportPayload) -> dict[str, int]:
    if not CHATGPT_IMPORT_CACHE.exists():
        raise HTTPException(status_code=400, detail="Upload the ChatGPT export first")
    candidates = json.loads(CHATGPT_IMPORT_CACHE.read_text(encoding="utf-8"))
    selected = set(payload.candidate_ids)
    imported = 0
    with connect() as db:
        for candidate in candidates:
            if candidate["id"] not in selected:
                continue
            title = str(candidate["conversation"])[:120]
            cursor = db.execute(
                "INSERT OR IGNORE INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, ?, ?, 0, 'chatgpt', 0)",
                (title, "ChatGPT Import", candidate["text"]),
            )
            imported += max(cursor.rowcount, 0)
    return {"imported": imported, "selected": len(selected)}


GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]
GOOGLE_PHOTOS_SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
GOOGLE_CREDENTIALS = UPLOAD_DIR.parent / "google_credentials.json"
GOOGLE_TOKEN = UPLOAD_DIR.parent / "google_token.json"
GOOGLE_STATE = UPLOAD_DIR.parent / "google_oauth_state.txt"


def google_credentials(required_scopes: list[str] | None = None):
    if not GOOGLE_TOKEN.exists():
        raise HTTPException(status_code=401, detail="Google Drive is not connected")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    credentials = Credentials.from_authorized_user_file(GOOGLE_TOKEN)
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            GOOGLE_TOKEN.write_text(credentials.to_json(), encoding="utf-8")
        except Exception as refresh_error:
            raise HTTPException(status_code=401, detail="Google needs to be connected again") from refresh_error
    if not credentials.valid:
        raise HTTPException(status_code=401, detail="Google Drive connection needs authorization")
    if required_scopes and not credentials.has_scopes(required_scopes):
        raise HTTPException(status_code=401, detail="Google Photos needs one permission update")
    return credentials


@app.get("/api/google/status")
def google_status() -> dict:
    connected = False
    email = None
    if GOOGLE_TOKEN.exists():
        try:
            from googleapiclient.discovery import build

            credentials = google_credentials(GOOGLE_SCOPES)
            if credentials.has_scopes(GOOGLE_SCOPES):
                about = build("drive", "v3", credentials=credentials).about().get(fields="user(displayName,emailAddress)").execute()
                email = about.get("user", {}).get("emailAddress")
                connected = True
        except Exception:
            connected = False
    configured = False
    if GOOGLE_CREDENTIALS.exists():
        try:
            saved = json.loads(GOOGLE_CREDENTIALS.read_text(encoding="utf-8"))
            client = saved.get("web") or saved.get("installed") or {}
            configured = bool(client.get("client_id") and client.get("client_secret"))
        except (OSError, ValueError):
            configured = False
    photos_connected = False
    if GOOGLE_TOKEN.exists():
        try:
            photos_connected = google_credentials([GOOGLE_PHOTOS_SCOPE]).has_scopes([GOOGLE_PHOTOS_SCOPE])
        except Exception:
            photos_connected = False
    return {"configured": configured, "connected": connected, "email": email, "photos_connected": photos_connected}


@app.post("/api/google/backup")
def backup_to_google_drive() -> dict:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload

    service = build("drive", "v3", credentials=google_credentials())
    root_id = ensure_google_backup_root(service)
    created_at = datetime.now(timezone.utc)
    timestamp = created_at.strftime("%Y-%m-%d_%H-%M-%S_UTC")
    folder = service.files().create(
        body={
            "name": f"Backup {timestamp}",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [root_id],
            "appProperties": {"blackcanvas_backup_set": "true", "backup_state": "creating"},
        },
        fields="id,name,webViewLink",
    ).execute()
    manifest = backup_data()
    manifest.update({"backup_format": 2, "created_at": created_at.isoformat(), "artwork_file_count": 0})
    uploaded_images = 0
    mime_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
    for artwork in manifest.get("artworks", []):
        image_path = UPLOAD_DIR / artwork["filename"]
        if not image_path.is_file():
            continue
        media = MediaFileUpload(
            str(image_path),
            mimetype=mime_types.get(image_path.suffix.lower(), "application/octet-stream"),
            resumable=True,
        )
        service.files().create(
            body={"name": artwork["filename"], "parents": [folder["id"]], "appProperties": {"blackcanvas_artwork": "true"}},
            media_body=media,
            fields="id",
        ).execute()
        uploaded_images += 1
    manifest["artwork_file_count"] = uploaded_images
    contents = json.dumps(manifest, indent=2).encode("utf-8")
    service.files().create(
        body={"name": "blackcanvas-backup.json", "parents": [folder["id"]], "appProperties": {"blackcanvas_manifest": "true"}},
        media_body=MediaInMemoryUpload(contents, mimetype="application/json", resumable=False),
        fields="id",
    ).execute()
    service.files().update(
        fileId=folder["id"],
        body={"appProperties": {"blackcanvas_backup_set": "true", "backup_state": "complete", "artwork_count": str(uploaded_images)}},
        fields="id",
    ).execute()
    return {
        "status": "backed_up",
        "name": folder["name"],
        "url": folder.get("webViewLink", ""),
        "artwork_files": uploaded_images,
        "prompts": len(manifest.get("prompts", [])),
    }


def ensure_google_backup_root(service) -> str:
    result = service.files().list(
        q="trashed=false and mimeType='application/vnd.google-apps.folder' and appProperties has { key='blackcanvas_backup_root' and value='true' }",
        pageSize=1,
        fields="files(id,name)",
    ).execute()
    if result.get("files"):
        return result["files"][0]["id"]
    folder = service.files().create(
        body={
            "name": "BlackCanvasAI Backups",
            "mimeType": "application/vnd.google-apps.folder",
            "appProperties": {"blackcanvas_backup_root": "true"},
        },
        fields="id",
    ).execute()
    return folder["id"]


@app.get("/api/google/backups")
def list_google_backups() -> dict[str, list[dict]]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    root_id = ensure_google_backup_root(service)
    result = service.files().list(
        q=f"'{root_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder' and appProperties has {{ key='blackcanvas_backup_set' and value='true' }}",
        orderBy="createdTime desc",
        pageSize=25,
        fields="files(id,name,createdTime,webViewLink,appProperties)",
    ).execute()
    backups = [item for item in result.get("files", []) if (item.get("appProperties") or {}).get("backup_state") == "complete"]
    return {"backups": backups}


@app.post("/api/google/restore/{backup_id}")
def restore_google_backup(backup_id: str) -> dict[str, int | str]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    folder = service.files().get(fileId=backup_id, fields="id,name,mimeType,appProperties").execute()
    properties = folder.get("appProperties") or {}
    if folder.get("mimeType") != "application/vnd.google-apps.folder" or properties.get("blackcanvas_backup_set") != "true" or properties.get("backup_state") != "complete":
        raise HTTPException(status_code=400, detail="That is not a complete BlackCanvasAI backup")
    children = service.files().list(
        q=f"'{backup_id}' in parents and trashed=false",
        pageSize=1000,
        fields="files(id,name,mimeType,appProperties)",
    ).execute().get("files", [])
    manifest_file = next((item for item in children if item["name"] == "blackcanvas-backup.json"), None)
    if not manifest_file:
        raise HTTPException(status_code=400, detail="The backup manifest is missing")
    try:
        manifest = json.loads(service.files().get_media(fileId=manifest_file["id"]).execute())
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="The backup manifest is invalid") from error

    snapshot_root = UPLOAD_DIR.parent / "restore-snapshots"
    snapshot_dir = snapshot_root / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%f_UTC")
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    with connect() as source_db, sqlite3.connect(snapshot_dir / "blackcanvas.db") as snapshot_db:
        source_db.backup(snapshot_db)
    if UPLOAD_DIR.exists():
        shutil.copytree(UPLOAD_DIR, snapshot_dir / "uploads")

    restored_prompts = 0
    restored_artworks = 0
    restored_images = 0
    remote_by_name = {item["name"]: item for item in children}
    with connect() as db:
        for prompt in manifest.get("prompts", []):
            cursor = db.execute(
                "INSERT OR IGNORE INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    prompt.get("title", "Restored prompt"), prompt.get("category", "Unsorted"), prompt.get("text", ""),
                    int(bool(prompt.get("favorite"))), prompt.get("source", "backup"), int(bool(prompt.get("reviewed", True))),
                ),
            )
            restored_prompts += max(cursor.rowcount, 0)
        for name, content in (manifest.get("styles") or {}).items():
            db.execute("INSERT OR REPLACE INTO styles(name, content) VALUES (?, ?)", (name, json.dumps(content)))
        for expense in manifest.get("expenses", []):
            db.execute(
                "INSERT OR IGNORE INTO expenses(description, category, amount, expense_date, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    expense.get("description", "Restored expense"), expense.get("category", "Other"),
                    max(float(expense.get("amount", 0) or 0), 0), expense.get("expense_date", ""),
                    expense.get("notes", ""), expense.get("created_at") or datetime.now(timezone.utc).isoformat(),
                ),
            )
        for setting in manifest.get("studio_settings", []):
            if setting.get("key") and setting.get("value") is not None:
                db.execute(
                    "INSERT OR REPLACE INTO studio_settings(key, value) VALUES (?, ?)",
                    (str(setting["key"]), str(setting["value"])),
                )
        for artwork in manifest.get("artworks", []):
            filename = Path(str(artwork.get("filename", ""))).name
            if not filename:
                continue
            image_path = UPLOAD_DIR / filename
            remote_image = remote_by_name.get(filename)
            if not image_path.exists() and remote_image:
                image_path.write_bytes(service.files().get_media(fileId=remote_image["id"]).execute())
                restored_images += 1
            existing = db.execute("SELECT id FROM artworks WHERE filename = ?", (filename,)).fetchone()
            if existing or not image_path.exists():
                continue
            db.execute(
                "INSERT INTO artworks(title, collection, tags, notes, favorite, dimensions, medium, price, sale_status, sale_price, sold_date, sales_channel, buyer_name, sale_notes, fulfillment_status, shipping_carrier, tracking_number, pricing_data, listing_url, filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artwork.get("title", "Restored artwork"), artwork.get("collection", "Unsorted"), artwork.get("tags", ""),
                    artwork.get("notes", ""), int(bool(artwork.get("favorite"))), artwork.get("dimensions", ""),
                    artwork.get("medium", ""), max(float(artwork.get("price", 0) or 0), 0),
                    artwork.get("sale_status", "In progress"), max(float(artwork.get("sale_price", 0) or 0), 0),
                    artwork.get("sold_date", ""), artwork.get("sales_channel", ""), artwork.get("buyer_name", ""),
                    artwork.get("sale_notes", ""), artwork.get("fulfillment_status", "Not started"),
                    artwork.get("shipping_carrier", ""), artwork.get("tracking_number", ""),
                    artwork.get("pricing_data", "{}"), artwork.get("listing_url", ""), filename,
                    artwork.get("created_at") or datetime.now(timezone.utc).isoformat(),
                ),
            )
            restored_artworks += 1
    return {
        "status": "restored",
        "prompts": restored_prompts,
        "artworks": restored_artworks,
        "images": restored_images,
        "safety_snapshot": snapshot_dir.name,
    }


@app.get("/api/google/prompt-files")
def google_prompt_files() -> dict[str, list[dict[str, str]]]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    compatible_types = ["application/vnd.google-apps.document", "text/plain", "text/markdown"]
    type_query = " or ".join(f"mimeType='{mime_type}'" for mime_type in compatible_types)
    result = service.files().list(
        q=f"trashed=false and ({type_query})",
        orderBy="modifiedTime desc",
        pageSize=50,
        fields="files(id,name,mimeType,modifiedTime,webViewLink)",
    ).execute()
    return {"files": result.get("files", [])}


@app.post("/api/google/import-prompt/{file_id}")
def import_google_prompt(file_id: str) -> dict[str, str | bool]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    metadata = service.files().get(fileId=file_id, fields="id,name,mimeType").execute()
    mime_type = metadata.get("mimeType", "")
    if mime_type == "application/vnd.google-apps.document":
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
    elif mime_type in {"text/plain", "text/markdown"}:
        content = service.files().get_media(fileId=file_id).execute()
    else:
        raise HTTPException(status_code=400, detail="This file type cannot be imported as a prompt yet")
    prompt_text = content.decode("utf-8", errors="replace").strip()
    if not prompt_text:
        raise HTTPException(status_code=400, detail="That document is empty")
    if len(prompt_text) > 100_000:
        raise HTTPException(status_code=400, detail="That document is too large to import as one prompt")
    title = re.sub(r"\.(txt|md)$", "", metadata["name"], flags=re.IGNORECASE).strip()
    with connect() as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO prompts(title, category, text, favorite, source, reviewed) VALUES (?, ?, ?, 0, 'drive', 0)",
            (title or "Imported prompt", "Imported", prompt_text),
        )
        imported = cursor.rowcount > 0
    return {"status": "imported" if imported else "already_exists", "title": title, "imported": imported}


@app.get("/api/google/artwork-files")
def google_artwork_files() -> dict[str, list[dict]]:
    from googleapiclient.discovery import build

    result = build("drive", "v3", credentials=google_credentials()).files().list(
        q="trashed=false and mimeType contains 'image/'",
        orderBy="modifiedTime desc",
        pageSize=60,
        fields="files(id,name,mimeType,modifiedTime,size)",
    ).execute()
    supported = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    return {"files": [item for item in result.get("files", []) if item.get("mimeType") in supported]}


def google_photos_client():
    """Create an authorized client only for images the user picks in Google Photos."""
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(google_credentials([GOOGLE_PHOTOS_SCOPE]))


def google_photos_response(response, fallback: str) -> dict:
    if response.ok:
        return response.json()
    try:
        detail = response.json().get("error", {}).get("message", fallback)
    except ValueError:
        detail = fallback
    raise HTTPException(status_code=response.status_code, detail=detail)


def picked_photo(session_id: str, photo_id: str) -> dict:
    client = google_photos_client()
    page_token = None
    while True:
        query = {"sessionId": session_id, "pageSize": 100}
        if page_token:
            query["pageToken"] = page_token
        response = client.get(f"https://photospicker.googleapis.com/v1/mediaItems?{urlencode(query)}")
        result = google_photos_response(response, "Could not read the photos you selected")
        item = next((candidate for candidate in result.get("mediaItems", []) if candidate.get("id") == photo_id), None)
        if item:
            return item
        page_token = result.get("nextPageToken")
        if not page_token:
            raise HTTPException(status_code=404, detail="That selected photo is no longer available. Choose it again in Google Photos.")


def picked_photo_details(item: dict) -> tuple[str, str, str]:
    media_file = item.get("mediaFile") or item
    base_url = media_file.get("baseUrl") or item.get("baseUrl")
    mime_type = media_file.get("mimeType") or item.get("mimeType") or ""
    filename = media_file.get("filename") or item.get("filename") or "Google Photos artwork"
    if not base_url or mime_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise HTTPException(status_code=400, detail="Choose a JPG, PNG, WebP, or GIF image from Google Photos.")
    return base_url, mime_type, filename


@app.post("/api/google/photos/session")
def create_google_photos_session() -> dict[str, str]:
    client = google_photos_client()
    response = client.post("https://photospicker.googleapis.com/v1/sessions", json={})
    session = google_photos_response(response, "Google Photos could not open the photo picker")
    picker_uri = session.get("pickerUri")
    if not picker_uri or not session.get("id"):
        raise HTTPException(status_code=502, detail="Google Photos did not return a picker. Try again.")
    # Keep Google's picker URI unchanged. Some browser shells invalidate the
    # short-lived selection session when an extra auto-close suffix is added.
    return {"id": session["id"], "pickerUri": picker_uri}


@app.get("/api/google/photos/selection")
def list_google_photos_selection(session_id: str, page_token: str | None = None) -> dict[str, object]:
    client = google_photos_client()
    query = {"sessionId": session_id, "pageSize": 60}
    if page_token:
        query["pageToken"] = page_token
    response = client.get("https://photospicker.googleapis.com/v1/mediaItems?" + urlencode(query))
    if not response.ok:
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        if error.get("status") == "FAILED_PRECONDITION":
            return {"ready": False, "photos": [], "wait_seconds": 3}
        return google_photos_response(response, "Could not read the photos you selected")
    result = google_photos_response(response, "Could not read the photos you selected")
    photos = []
    for item in result.get("mediaItems", []):
        try:
            base_url, mime_type, filename = picked_photo_details(item)
            photos.append({"id": item["id"], "name": filename, "mimeType": mime_type, "preview": f"/api/google/photos/preview?{urlencode({'session_id': session_id, 'photo_id': item['id']})}"})
        except HTTPException:
            continue
    return {"ready": True, "photos": photos, "next_page_token": result.get("nextPageToken")}


@app.get("/api/google/photos/preview")
def google_photos_preview(session_id: str, photo_id: str) -> Response:
    item = picked_photo(session_id, photo_id)
    base_url, mime_type, _ = picked_photo_details(item)
    response = google_photos_client().get(f"{base_url}=w1200")
    if not response.ok:
        raise HTTPException(status_code=502, detail="Google Photos could not load that image")
    return Response(content=response.content, media_type=mime_type, headers={"Cache-Control": "private, max-age=300"})


@app.post("/api/google/photos/import")
def import_google_photos_artwork(payload: GooglePhotosImportPayload) -> dict[str, str | int]:
    item = picked_photo(payload.session_id, payload.photo_id)
    base_url, mime_type, source_name = picked_photo_details(item)
    response = google_photos_client().get(f"{base_url}=w4096")
    if not response.ok:
        raise HTTPException(status_code=502, detail="Google Photos could not download that image")
    if len(response.content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="That image is larger than 20 MB. Use a smaller copy for now.")
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
    filename = f"{uuid.uuid4().hex}{extensions[mime_type]}"
    (UPLOAD_DIR / filename).write_bytes(response.content)
    artwork_id = execute(
        "INSERT INTO artworks(title, collection, tags, notes, favorite, filename) VALUES (?, ?, ?, ?, 0, ?)",
        (payload.title.strip() or source_name, payload.collection, payload.tags.strip(), payload.notes.strip(), filename),
    )
    return {"status": "imported", "id": artwork_id, "url": f"/uploads/{filename}"}


@app.get("/api/google/artwork-preview/{file_id}")
def google_artwork_preview(file_id: str) -> Response:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    metadata = service.files().get(fileId=file_id, fields="mimeType,size").execute()
    if metadata.get("mimeType") not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    if int(metadata.get("size") or 0) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be smaller than 10 MB")
    content = service.files().get_media(fileId=file_id).execute()
    return Response(content=content, media_type=metadata["mimeType"], headers={"Cache-Control": "private, max-age=300"})


@app.post("/api/google/import-artwork/{file_id}")
def import_google_artwork(file_id: str, payload: DriveArtworkPayload) -> dict[str, str | int]:
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=google_credentials())
    metadata = service.files().get(fileId=file_id, fields="name,mimeType,size").execute()
    mime_type = metadata.get("mimeType")
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
    if mime_type not in extensions:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    if int(metadata.get("size") or 0) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be smaller than 10 MB")
    image_bytes = service.files().get_media(fileId=file_id).execute()
    filename = f"{uuid.uuid4().hex}{extensions[mime_type]}"
    (UPLOAD_DIR / filename).write_bytes(image_bytes)
    artwork_id = execute(
        "INSERT INTO artworks(title, collection, tags, notes, favorite, filename) VALUES (?, ?, ?, ?, 0, ?)",
        (payload.title.strip() or metadata["name"], payload.collection, payload.tags.strip(), payload.notes.strip(), filename),
    )
    return {"status": "imported", "id": artwork_id, "url": f"/uploads/{filename}"}


@app.post("/api/google/credentials")
def save_google_credentials(payload: GoogleCredentialsPayload) -> dict[str, str]:
    credentials = payload.credentials
    if "installed" not in credentials and "web" not in credentials:
        raise HTTPException(status_code=400, detail="This is not a Google OAuth client file")
    GOOGLE_CREDENTIALS.write_text(json.dumps(credentials), encoding="utf-8")
    return {"status": "configured"}


@app.post("/api/google/client-id")
def save_google_client_id(payload: GoogleClientPayload) -> dict[str, str]:
    client_id = payload.client_id.strip()
    client_secret = payload.client_secret.strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise HTTPException(status_code=400, detail="Invalid Google OAuth Client ID")
    if not client_secret:
        raise HTTPException(status_code=400, detail="Google OAuth Client Secret is required")
    credentials = {
        "web": {
            "client_id": client_id,
            "project_id": "blackcanvas-local",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost:8010/google/callback"],
        }
    }
    GOOGLE_CREDENTIALS.write_text(json.dumps(credentials), encoding="utf-8")
    return {"status": "configured"}


@app.get("/google/connect")
def google_connect() -> RedirectResponse:
    return start_google_oauth(GOOGLE_SCOPES, "drive")


@app.get("/google/photos/connect")
def google_photos_connect() -> RedirectResponse:
    return start_google_oauth([*GOOGLE_SCOPES, GOOGLE_PHOTOS_SCOPE], "photos")


def start_google_oauth(scopes: list[str], connection: str) -> RedirectResponse:
    if not GOOGLE_CREDENTIALS.exists():
        return RedirectResponse("/connections?setup=needed")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS,
        scopes=scopes,
        autogenerate_code_verifier=True,
    )
    flow.redirect_uri = "http://localhost:8010/google/callback"
    authorization_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    GOOGLE_STATE.write_text(
        json.dumps({"state": state, "code_verifier": flow.code_verifier, "scopes": scopes, "connection": connection}),
        encoding="utf-8",
    )
    return RedirectResponse(authorization_url)


@app.get("/google/callback")
def google_callback(state: str, code: str | None = None, error: str | None = None) -> RedirectResponse:
    if error or not code:
        return RedirectResponse(f"/connections?error={error or 'authorization_cancelled'}")
    if not GOOGLE_STATE.exists():
        raise HTTPException(status_code=400, detail="Google authorization session expired")
    authorization = json.loads(GOOGLE_STATE.read_text(encoding="utf-8"))
    if state != authorization["state"]:
        raise HTTPException(status_code=400, detail="Invalid Google authorization state")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS,
        scopes=authorization.get("scopes", GOOGLE_SCOPES),
        state=state,
        code_verifier=authorization["code_verifier"],
    )
    flow.redirect_uri = "http://localhost:8010/google/callback"
    try:
        flow.oauth2session.fetch_token(
            flow.client_config["token_uri"],
            code=code,
            code_verifier=flow.code_verifier,
            client_secret=flow.client_config.get("client_secret"),
            include_client_id=True,
        )
    except Exception as exchange_error:
        (UPLOAD_DIR.parent / "google_oauth_error.txt").write_text(
            f"{type(exchange_error).__name__}: {exchange_error}",
            encoding="utf-8",
        )
        return RedirectResponse("/connections?error=token_exchange_failed")
    GOOGLE_TOKEN.write_text(flow.credentials.to_json(), encoding="utf-8")
    GOOGLE_STATE.unlink(missing_ok=True)
    if authorization.get("connection") == "photos":
        return RedirectResponse("/connections?photos=connected")
    return RedirectResponse("/connections?connected=true")
