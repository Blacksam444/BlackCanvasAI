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
        """)
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
        "prompts": rows("SELECT id, title, category, text, favorite FROM prompts ORDER BY id"),
        "styles": {item["name"]: json.loads(item["content"]) for item in styles},
        "artworks": rows("SELECT id, title, collection, tags, notes, favorite, filename, created_at FROM artworks ORDER BY id"),
    }
