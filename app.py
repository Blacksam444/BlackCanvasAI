import base64
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
from spellchecker import SpellChecker

from storage import UPLOAD_DIR, backup_data, connect, execute, initialize, rows

BASE_DIR = Path(__file__).resolve().parent
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
    data_url: str


class ArtworkDetailsPayload(BaseModel):
    title: str
    collection: str
    tags: str = ""
    notes: str = ""


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


def create_image_prompt(message: str) -> tuple[str, str]:
    idea = clean_image_idea(message)
    collection, palette, style, mood = prompt_collection(idea)
    palette, style, mood, avoid = saved_style_direction(collection, palette, style, mood)
    lowered = idea.lower()
    subject = re.split(r"\s+in\s+the\s+(?:AfroNova|Quiet Nova|GraffitiX)\s+style", idea, maxsplit=1, flags=re.IGNORECASE)[0]
    requested_mood = re.search(r"with\s+(?:an?\s+)?(.+?)\s+mood", idea, flags=re.IGNORECASE)
    requested_colors = re.search(r"using\s+(.+?),\s+as\s+", idea, flags=re.IGNORECASE)
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
    prompt = (
        f"Create {medium} of {subject},{safety} presented as the unmistakable focal subject. "
        f"Use a balanced three-quarter composition at eye level, with confident posture, expressive eyes, "
        f"and carefully observed facial features. Build the visual direction around {style}. "
        f"Illuminate the subject with soft directional key light and a subtle luminous rim light, creating "
        f"dimensional skin tones, controlled highlights, and rich shadow detail. Use a refined palette of "
        f"{palette}. Place the subject against an atmospheric, story-rich background that supports the idea "
        f"without competing with the face. The mood is {mood}. Include believable materials, finely rendered "
        f"fabric and accessories, natural depth of field, sophisticated color grading, crisp focal detail, "
        f"gallery-ready composition, ultra-detailed, cohesive, emotionally resonant{avoid}, no text, no watermark."
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
def chat_reply(payload: ChatMessage) -> dict[str, str]:
    topic = payload.message.strip()
    creative_triggers = ("prompt", "image", "portrait", "painting", "photo", "artwork", "style",
                         "afronova", "afro nova", "quiet nova", "graffitix", "graffiti x")
    if any(word in topic.lower() for word in creative_triggers):
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
            f"I’m ready to help you develop **{topic}**.\n\n"
            "Here’s a strong way to begin:\n"
            "- Define the goal and who it is for.\n"
            "- Choose the Black Canvas style or collection it belongs to.\n"
            "- Turn the idea into one clear, testable creative direction.\n\n"
            "The chat workspace is working. The next connection will replace this preview "
            "response with live AI reasoning."
        )
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
    return {
        "counts": {"prompts": prompt_count, "artworks": artwork_count,
                   "favorites": favorite_count, "to_review": review_count},
        "prompt_of_day": dict(prompt_of_day) if prompt_of_day else None,
        "recent": activity[:3],
    }


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
    items = rows("SELECT id, title, collection, tags, notes, favorite, filename, created_at FROM artworks ORDER BY id DESC")
    for item in items:
        item["url"] = f"/uploads/{item['filename']}"
    return items


@app.get("/api/artworks/{artwork_id}/content-kit")
def artwork_content_kit(artwork_id: int) -> dict:
    matches = rows("SELECT id, title, collection, tags, notes FROM artworks WHERE id = ?", (artwork_id,))
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
            "This statement artwork is designed for collectors who value distinctive contemporary Black art, "
            "intentional storytelling, and work with a strong visual presence.\n\n"
            "Please review the artwork photographs and listing details carefully for size, materials, framing, "
            "and shipping information before purchasing."
        ),
        "listing_tags": etsy_tags,
    }


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
        "INSERT INTO artworks(title, collection, tags, notes, favorite, filename) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.title.strip(), payload.collection, payload.tags.strip(), payload.notes.strip(), int(payload.favorite), filename),
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
            "UPDATE artworks SET title = ?, collection = ?, tags = ?, notes = ? WHERE id = ?",
            (title, payload.collection, payload.tags.strip(), payload.notes.strip(), artwork_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Artwork not found")
    return {"id": artwork_id, "title": title, "collection": payload.collection,
            "tags": payload.tags.strip(), "notes": payload.notes.strip()}


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
                "INSERT INTO artworks(title, collection, tags, notes, favorite, filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    artwork.get("title", "Restored artwork"), artwork.get("collection", "Unsorted"), artwork.get("tags", ""),
                    artwork.get("notes", ""), int(bool(artwork.get("favorite"))), filename,
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
