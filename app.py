import base64
import json
import re
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.responses import RedirectResponse
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
    raw = await export_file.read()
    if len(raw) > 150 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="That export is too large to scan")
    try:
        if (export_file.filename or "").lower().endswith(".zip"):
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                conversation_name = next(
                    (name for name in archive.namelist() if name.lower().endswith("conversations.json")),
                    None,
                )
                if not conversation_name:
                    raise ValueError("conversations.json was not found in that ZIP")
                conversations = json.loads(archive.read(conversation_name))
        else:
            conversations = json.loads(raw)
        if not isinstance(conversations, list):
            raise ValueError("The conversation export is not a list")
    except (ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail=f"Could not read that ChatGPT export: {error}") from error
    candidates = chatgpt_candidates(conversations)
    CHATGPT_IMPORT_CACHE.write_text(json.dumps(candidates), encoding="utf-8")
    return {"count": len(candidates), "candidates": candidates[:500]}


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
                "INSERT OR IGNORE INTO prompts(title, category, text, favorite) VALUES (?, ?, ?, 0)",
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
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            credentials = Credentials.from_authorized_user_file(GOOGLE_TOKEN)
            if credentials.valid and credentials.has_scopes(GOOGLE_SCOPES):
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
def backup_to_google_drive() -> dict[str, str]:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaInMemoryUpload

    credentials = google_credentials()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S_UTC")
    filename = f"BlackCanvasAI-backup-{timestamp}.json"
    contents = json.dumps(backup_data(), indent=2).encode("utf-8")
    media = MediaInMemoryUpload(contents, mimetype="application/json", resumable=False)
    uploaded = (
        build("drive", "v3", credentials=credentials)
        .files()
        .create(
            body={
                "name": filename,
                "description": "BlackCanvasAI prompt, style, and artwork catalog backup",
                "appProperties": {"blackcanvas_backup": "true"},
            },
            media_body=media,
            fields="id,name,webViewLink",
        )
        .execute()
    )
    return {"status": "backed_up", "name": uploaded["name"], "url": uploaded.get("webViewLink", "")}


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
            "INSERT OR IGNORE INTO prompts(title, category, text, favorite) VALUES (?, ?, ?, 0)",
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
