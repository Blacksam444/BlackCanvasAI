import base64
import json
import re
import sqlite3
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

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


class PromptPayload(BaseModel):
    title: str
    category: str
    text: str
    favorite: bool = False


class StylePayload(BaseModel):
    content: dict


class ArtworkPayload(BaseModel):
    title: str
    collection: str
    tags: str = ""
    notes: str = ""
    favorite: bool = False
    data_url: str


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


@app.post("/api/chat")
def chat_reply(payload: ChatMessage) -> dict[str, str]:
    topic = payload.message.strip()
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


@app.get("/api/prompts")
def list_prompts() -> list[dict]:
    return rows("SELECT id, title, category, text, favorite FROM prompts ORDER BY id DESC")


@app.post("/api/prompts")
def create_prompt(payload: PromptPayload) -> dict:
    try:
        prompt_id = execute(
            "INSERT INTO prompts(title, category, text, favorite) VALUES (?, ?, ?, ?)",
            (payload.title.strip(), payload.category, payload.text.strip(), int(payload.favorite)),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Prompt already exists")
    return {"id": prompt_id, **payload.model_dump()}


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


@app.get("/api/artworks")
def list_artworks() -> list[dict]:
    items = rows("SELECT id, title, collection, tags, notes, favorite, filename, created_at FROM artworks ORDER BY id DESC")
    for item in items:
        item["url"] = f"/uploads/{item['filename']}"
    return items


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
