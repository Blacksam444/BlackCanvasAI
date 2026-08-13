import json
import sqlite3
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "blackcanvas.db"

DEFAULT_PROMPTS = [
    ("Cosmic Royalty Portrait", "AfroNova", "Create a bold portrait where cosmic elegance meets street-art energy. Feature a regal Black subject, luminous celestial textures, deep violet and gold tones, and gallery-quality detail.", 1),
    ("Soft Morning Reflection", "Quiet Nova", "A contemplative Black figure in soft window light, surrounded by calm neutral tones, subtle texture, and generous negative space. The mood is intimate, grounded, and quietly powerful.", 0),
    ("Neon City Expression", "GraffitiX", "An explosive urban portrait blending layered graffiti marks, neon color, expressive typography, torn-paper texture, and the energy of a midnight city wall.", 1),
    ("Studio Process Reel", "Content", "Write a 30-second TikTok concept showing an artwork move from blank canvas to final reveal. Include a strong opening hook, three visual beats, on-screen text, and a natural call to action.", 0),
    ("Artwork Pricing Check", "Business", "Help me price an original artwork. Consider dimensions, materials, hours worked, experience, uniqueness, packaging, platform fees, and a healthy profit margin.", 0),
    ("Collection Story Builder", "AfroNova", "Develop a concise story for a cohesive art collection exploring Black identity, imagined futures, ancestry, and self-defined power.", 0),
]


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                text TEXT NOT NULL,
                favorite INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'manual',
                reviewed INTEGER NOT NULL DEFAULT 1,
                UNIQUE(title, text)
            );
            CREATE TABLE IF NOT EXISTS styles (
                name TEXT PRIMARY KEY,
                content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artworks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                collection TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                favorite INTEGER NOT NULL DEFAULT 0,
                filename TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS style_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                style_name TEXT NOT NULL,
                source_text TEXT NOT NULL,
                suggestions TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
        """)
        prompt_columns = {row[1] for row in db.execute("PRAGMA table_info(prompts)")}
        if "source" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        if "reviewed" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 1")
        db.execute("UPDATE prompts SET source = 'chatgpt', reviewed = 0 WHERE category = 'ChatGPT Import' AND source = 'manual'")
        db.execute("UPDATE prompts SET source = 'drive', reviewed = 0 WHERE category = 'Imported' AND source = 'manual'")
        if db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 0:
            db.executemany("INSERT INTO prompts(title, category, text, favorite) VALUES (?, ?, ?, ?)", DEFAULT_PROMPTS)


def rows(query: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute(query, values).fetchall()]


def execute(query: str, values: tuple[Any, ...] = ()) -> int:
    with connect() as db:
        cursor = db.execute(query, values)
        return int(cursor.lastrowid)


def backup_data() -> dict[str, Any]:
    styles = rows("SELECT name, content FROM styles ORDER BY name")
    return {
        "version": 1,
        "prompts": rows("SELECT id, title, category, text, favorite, source, reviewed FROM prompts ORDER BY id"),
        "styles": {item["name"]: json.loads(item["content"]) for item in styles},
        "artworks": rows("SELECT id, title, collection, tags, notes, favorite, filename, created_at FROM artworks ORDER BY id"),
        "style_updates": rows("SELECT id, style_name, source_text, suggestions, status, created_at FROM style_updates ORDER BY id"),
        "conversations": rows("SELECT id, title, created_at, updated_at FROM conversations ORDER BY id"),
        "chat_messages": rows("SELECT id, conversation_id, role, text, metadata, created_at FROM chat_messages ORDER BY id"),
    }
