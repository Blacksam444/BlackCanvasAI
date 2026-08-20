import base64
import csv
import io
import json
import re
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
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

from storage import UPLOAD_DIR, backup_data, connect, execute, initialize, rows

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ASPECT_RATIO = "4:5"
SUPPORTED_ASPECT_RATIOS = {"1:1", "4:5", "3:2", "16:9", "9:16"}
DEFAULT_NEGATIVE_INSTRUCTIONS = "no text, no watermark, no signature, no logo, no frame"
GRAFFITIX_NEGATIVE_INSTRUCTIONS = (
    "no digital smoothness, no glossy CGI finish, no polished 3D render, "
    "no clean vector edges, no random decorative symbols, no cluttered focal hierarchy, "
    f"{DEFAULT_NEGATIVE_INSTRUCTIONS}"
)
initialize()
app = FastAPI(title="Black Canvas AI")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def dashboard_file() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "dashboard.html")


class ChatMessage(BaseModel):
    message: str


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


def midjourney_v82_suffix(idea: str) -> str:
    requested_ratio = re.search(
        r"(?:^|[.;])\s*aspect ratio\s*:\s*([0-9]+:[0-9]+)", idea, flags=re.IGNORECASE
    )
    aspect_ratio = requested_ratio.group(1) if requested_ratio else DEFAULT_ASPECT_RATIO
    if aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
        aspect_ratio = DEFAULT_ASPECT_RATIO
    return f"--ar {aspect_ratio} --raw --v 8.2"


def create_image_prompt(message: str) -> tuple[str, str]:
    idea = clean_image_idea(message)
    collection, palette, style, mood = prompt_collection(idea)
    palette, style, mood, avoid = saved_style_direction(collection, palette, style, mood)
    lowered = idea.lower()
    subject = re.split(r"\s+in\s+the\s+(?:AfroNova|Quiet Nova|GraffitiX)\s+style", idea, maxsplit=1, flags=re.IGNORECASE)[0]
    requested_mood = re.search(r"with\s+(?:an?\s+)?(.+?)\s+mood", idea, flags=re.IGNORECASE)
    requested_colors = re.search(r"using\s+(.+?),\s+as\s+", idea, flags=re.IGNORECASE)
    requested_pose = re.search(r"(?:^|[.;])\s*pose\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_camera = re.search(r"(?:^|[.;])\s*camera\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    requested_hero = re.search(r"(?:^|[.;])\s*hero symbol\s*:\s*([^.;]+)", idea, flags=re.IGNORECASE)
    midjourney_suffix = midjourney_v82_suffix(idea)
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
            f"/imagine prompt: full-body {subject},{safety} presented as the unmistakable focal subject. "
            f"Engineer {pose_direction}. Use {camera_direction}, keeping the silhouette immediately readable. "
            "Build authentic 1990s streetwear with construction detail: oversized pleated chinos, stacked ankles, "
            "pocket tee or cropped tank, open flannel or vintage windbreaker, bandana or snapback, and retro sneakers. "
            f"Establish one dominant hero symbol—{hero_symbol}; use only one or two small supporting symbols, then restrained background writing. "
            "Render raw Black Canvas / 444 GraffitiX mixed-media fine art: heavy oil stick, oil pastel, dripping acrylic, "
            "impasto, aerosol haze, charcoal, chalk, scratches, collage, and exposed canvas. "
            f"Use {palette}, stark graphic directional lighting, brutal contrast, irregular hand-drawn edges, tactile matte surfaces, "
            f"and a {mood} emotional charge. Keep the figure emotionally present and dominant over every mark. "
            f"Museum-quality contemporary urban artwork, {GRAFFITIX_NEGATIVE_INSTRUCTIONS} {midjourney_suffix}"
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
        f"gallery-ready composition, ultra-detailed, cohesive, emotionally resonant{avoid}, "
        f"{DEFAULT_NEGATIVE_INSTRUCTIONS} {midjourney_suffix}"
    )
    return collection, prompt


@app.get("/")
def home() -> FileResponse:
    return dashboard_file()


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return dashboard_file()


@app.get("/chat")
def chat() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "chat.html")


@app.get("/prompts")
def prompts() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "prompts.html")


@app.get("/image-studio")
def image_studio() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "image-studio.html")


@app.get("/style-bible")
def style_bible() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "style-bible.html")


@app.get("/connections")
def connections() -> FileResponse:
    return FileResponse(
        BASE_DIR / "templates" / "connections.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.post("/api/chat")
def chat_reply(payload: ChatMessage) -> dict[str, object]:
    topic = payload.message.strip()
    topic_lower = topic.lower()
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
                "Start with **Duplicates first** in Prompt Library. Keep one strong copy, choose its collection, "
                "and remove extra copies only when you confirm they are truly identical. Then review the detailed "
                "prompts before the short entries."
            ),
            "actions": [{"label": "Open Prompt Library", "href": "/prompts"}]
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
    creative_triggers = ("prompt", "image", "portrait", "painting", "photo", "artwork", "style",
                         "afronova", "afro nova", "quiet nova", "graffitix", "graffiti x")
    if any(word in topic_lower for word in creative_triggers):
        collection, prompt = create_image_prompt(topic)
        idea = clean_image_idea(topic)
        title = re.sub(r"\s+", " ", idea).strip().title()[:70] or "Generated Image Prompt"
        return {
            "reply": (
                f"**Your {collection} image prompt**\n\n{prompt}\n\n"
                f"This uses your current {collection} Style Bible rules. You can copy it into your image "
                "generator. It was created locally, so it did not use a paid AI key."
            ),
            "generated_prompt": prompt,
            "prompt_title": title,
            "prompt_category": collection,
        }
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
    prompt = payload.prompt.strip()
    category = payload.category if payload.category in ("AfroNova", "Quiet Nova", "GraffitiX") else "AfroNova"
    labels = {
        "cinematic": "Cinematic variation",
        "detailed": "Detailed variation",
        "simple": "Simplified variation",
        "style": f"Stronger {category} variation",
    }
    if payload.mode not in labels:
        raise HTTPException(status_code=400, detail="Unknown refinement")

    if payload.mode == "cinematic":
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
    return {
        "reply": f"**{labels[payload.mode]}**\n\n{refined}",
        "generated_prompt": refined,
        "prompt_title": labels[payload.mode],
        "prompt_category": category,
    }


@app.get("/api/prompts")
def list_prompts() -> list[dict]:
    return rows("SELECT id, title, category, text, favorite, source, reviewed FROM prompts ORDER BY id DESC")


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
        catalog_value = db.execute(
            "SELECT COALESCE(SUM(price), 0) FROM artworks WHERE sale_status != 'Sold'"
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
            "SELECT COUNT(*) FROM artworks WHERE price <= 0 AND sale_status != 'Sold'"
        ).fetchone()[0]
        incomplete_artwork = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE TRIM(dimensions) = '' OR TRIM(medium) = '' OR TRIM(notes) = ''"
        ).fetchone()[0]
        prompt_rows = [dict(item) for item in db.execute(
            "SELECT id, title, category, text FROM prompts ORDER BY id DESC LIMIT 3"
        ).fetchall()]
        artwork_rows = [dict(item) for item in db.execute(
            "SELECT id, title, collection, notes FROM artworks ORDER BY id DESC LIMIT 3"
        ).fetchall()]
        prompt_of_day = db.execute(
            "SELECT id, title, category, text FROM prompts "
            "ORDER BY favorite DESC, id DESC LIMIT 1 OFFSET ?",
            ((datetime.now().timetuple().tm_yday - 1) % max(prompt_count, 1),),
        ).fetchone() if prompt_count else None

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
    if unpriced_artwork:
        priorities.append({"icon": "$", "title": "Price your available artwork", "count": unpriced_artwork,
                           "detail": "Use the calculator so catalog value reflects your work.", "href": "/image-studio?focus=unpriced", "tone": "purple"})
    if incomplete_artwork:
        priorities.append({"icon": "✓", "title": "Complete artwork details", "count": incomplete_artwork,
                           "detail": "Add missing size, medium, or descriptions.", "href": "/image-studio?focus=incomplete", "tone": "amber"})
    if ready_to_list:
        priorities.append({"icon": "✦", "title": "Publish ready artwork", "count": ready_to_list,
                           "detail": "These pieces have been marked Ready to List.", "href": "/image-studio?focus=ready", "tone": "pink"})
    if review_count:
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
        "recent": activity[:3],
        "priorities": priorities[:4],
    }


@app.get("/api/agent-brief")
def agent_brief() -> dict[str, str]:
    """Return a local, data-aware studio brief without sending data to an AI provider."""
    with connect() as db:
        prompt_count = db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
        review_count = db.execute("SELECT COUNT(*) FROM prompts WHERE reviewed = 0").fetchone()[0]
        artwork_count = db.execute("SELECT COUNT(*) FROM artworks").fetchone()[0]
        ready_to_list = db.execute("SELECT COUNT(*) FROM artworks WHERE sale_status = 'Ready to list'").fetchone()[0]
        unpriced = db.execute("SELECT COUNT(*) FROM artworks WHERE price <= 0 AND sale_status != 'Sold'").fetchone()[0]
        active_orders = db.execute(
            "SELECT COUNT(*) FROM artworks WHERE sale_status = 'Sold' "
            "AND fulfillment_status NOT IN ('Delivered', 'Local pickup complete')"
        ).fetchone()[0]
        favorites = db.execute("SELECT COUNT(*) FROM prompts WHERE favorite = 1").fetchone()[0]

    if active_orders:
        next_step = f"Move {active_orders} active {'order' if active_orders == 1 else 'orders'} forward in Image Studio."
    elif unpriced:
        next_step = f"Price {unpriced} available {'artwork' if unpriced == 1 else 'artworks'} before listing."
    elif ready_to_list:
        next_step = f"Prepare {ready_to_list} {'piece' if ready_to_list == 1 else 'pieces'} that are ready to list."
    elif review_count:
        next_step = f"Review your {review_count} imported {'prompt' if review_count == 1 else 'prompts'} in a focused session."
    else:
        next_step = "Create a new prompt or add your next artwork to the studio."

    return {"reply": (
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
    changes: list[dict[str, str]] = []

    def correct_word(match: re.Match) -> str:
        word = match.group(0)
        lowered = word.lower()
        if len(word) < 4 or lowered in protected or word.isupper() or any(char.isdigit() for char in word):
            return word
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
    items = rows("SELECT id, title, collection, tags, notes, favorite, dimensions, medium, price, sale_status, sale_price, sold_date, sales_channel, buyer_name, sale_notes, fulfillment_status, shipping_carrier, tracking_number, filename, created_at FROM artworks ORDER BY id DESC")
    for item in items:
        item["url"] = f"/uploads/{item['filename']}"
    return items


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
    certificate_dir = BASE_DIR / "data" / "certificates"
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
    receipt_dir = BASE_DIR / "data" / "receipts"
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
    label_dir = BASE_DIR / "data" / "gallery-labels"
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
    matches = rows("SELECT id, title, collection, tags, notes, dimensions, medium, price, sale_status FROM artworks WHERE id = ?", (artwork_id,))
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
    return {
        "artwork_title": title,
        "instagram": (
            f"{title}. A {tone} piece from the {collection} collection, shaped by {story}.\n\n"
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
    }


def artwork_image_record(artwork_id: int) -> tuple[dict, Path]:
    matches = rows("SELECT id, title, filename FROM artworks WHERE id = ?", (artwork_id,))
    if not matches:
        raise HTTPException(status_code=404, detail="Artwork not found")
    image_path = UPLOAD_DIR / matches[0]["filename"]
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Artwork image file not found")
    return matches[0], image_path


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
        export_dir = BASE_DIR / "data" / "print_exports"
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
    package_dir = BASE_DIR / "data" / "seller_packages"
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
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}[match.group(1)]
    filename = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(image_bytes)
    artwork_id = execute(
        "INSERT INTO artworks(title, collection, tags, notes, favorite, dimensions, medium, price, sale_status, filename) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (payload.title.strip(), payload.collection, payload.tags.strip(), payload.notes.strip(), int(payload.favorite),
         payload.dimensions.strip(), payload.medium.strip(), max(payload.price, 0), payload.sale_status, filename),
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
    with connect() as db:
        cursor = db.execute(
            "UPDATE artworks SET title = ?, collection = ?, tags = ?, notes = ?, dimensions = ?, medium = ?, price = ?, sale_status = ? WHERE id = ?",
            (title, payload.collection, payload.tags.strip(), payload.notes.strip(), payload.dimensions.strip(),
             payload.medium.strip(), max(payload.price, 0), payload.sale_status, artwork_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Artwork not found")
    return {"id": artwork_id, "title": title, "collection": payload.collection,
            "tags": payload.tags.strip(), "notes": payload.notes.strip(), "dimensions": payload.dimensions.strip(),
            "medium": payload.medium.strip(), "price": max(payload.price, 0), "sale_status": payload.sale_status}


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


def chatgpt_candidates(conversations: list[dict]) -> list[dict[str, str | float]]:
    candidates: list[dict[str, str | float]] = []
    seen: set[str] = set()
    for conversation in conversations:
        conversation_title = str(conversation.get("title") or "Untitled conversation")
        for node_id, node in (conversation.get("mapping") or {}).items():
            message = (node or {}).get("message") or {}
            if (message.get("author") or {}).get("role") != "user":
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
GOOGLE_CREDENTIALS = UPLOAD_DIR.parent / "google_credentials.json"
GOOGLE_TOKEN = UPLOAD_DIR.parent / "google_token.json"
GOOGLE_STATE = UPLOAD_DIR.parent / "google_oauth_state.txt"


def google_credentials():
    if not GOOGLE_TOKEN.exists():
        raise HTTPException(status_code=401, detail="Google Drive is not connected")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    credentials = Credentials.from_authorized_user_file(GOOGLE_TOKEN)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        GOOGLE_TOKEN.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise HTTPException(status_code=401, detail="Google Drive connection needs authorization")
    return credentials


@app.get("/api/google/status")
def google_status() -> dict:
    connected = False
    email = None
    if GOOGLE_TOKEN.exists():
        try:
            from googleapiclient.discovery import build

            credentials = google_credentials()
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
    return {"configured": configured, "connected": connected, "email": email}


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
                "INSERT INTO artworks(title, collection, tags, notes, favorite, dimensions, medium, price, sale_status, sale_price, sold_date, sales_channel, buyer_name, sale_notes, fulfillment_status, shipping_carrier, tracking_number, pricing_data, filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artwork.get("title", "Restored artwork"), artwork.get("collection", "Unsorted"), artwork.get("tags", ""),
                    artwork.get("notes", ""), int(bool(artwork.get("favorite"))), artwork.get("dimensions", ""),
                    artwork.get("medium", ""), max(float(artwork.get("price", 0) or 0), 0),
                    artwork.get("sale_status", "In progress"), max(float(artwork.get("sale_price", 0) or 0), 0),
                    artwork.get("sold_date", ""), artwork.get("sales_channel", ""), artwork.get("buyer_name", ""),
                    artwork.get("sale_notes", ""), artwork.get("fulfillment_status", "Not started"),
                    artwork.get("shipping_carrier", ""), artwork.get("tracking_number", ""),
                    artwork.get("pricing_data", "{}"), filename,
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
    if not GOOGLE_CREDENTIALS.exists():
        return RedirectResponse("/connections?setup=needed")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS,
        scopes=GOOGLE_SCOPES,
        autogenerate_code_verifier=True,
    )
    flow.redirect_uri = "http://localhost:8010/google/callback"
    authorization_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    GOOGLE_STATE.write_text(
        json.dumps({"state": state, "code_verifier": flow.code_verifier}),
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
        scopes=GOOGLE_SCOPES,
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
    return RedirectResponse("/connections?connected=true")
