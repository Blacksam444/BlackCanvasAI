import json
import sqlite3
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "blackcanvas.db"
MIDJOURNEY_RULES_PATH = BASE_DIR / "midjourney_rules.json"

DEFAULT_PROMPTS = []


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
                trashed INTEGER NOT NULL DEFAULT 0,
                parent_prompt_id INTEGER,
                migrated_from_version TEXT,
                version_test_result TEXT,
                version_test_notes TEXT NOT NULL DEFAULT '',
                version_tested_at TEXT,
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
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                source_prompt_id INTEGER UNIQUE,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned',
                materials TEXT NOT NULL DEFAULT '[]',
                surface TEXT NOT NULL DEFAULT '',
                checklist TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 1,
                archived INTEGER NOT NULL DEFAULT 0,
                archive_revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_artworks (
                project_id TEXT NOT NULL,
                artwork_id INTEGER NOT NULL,
                stage TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (project_id, artwork_id)
            );
            CREATE TABLE IF NOT EXISTS project_covers (
                project_id TEXT PRIMARY KEY,
                artwork_id INTEGER,
                revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS project_journal (
                project_id TEXT NOT NULL,
                id TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                body TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (project_id, id)
            );
            CREATE TABLE IF NOT EXISTS creative_kits (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                name_key TEXT NOT NULL UNIQUE,
                preferences TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS marketing_plans (
                id TEXT PRIMARY KEY NOT NULL,
                artwork_filename TEXT NOT NULL,
                artwork_title TEXT NOT NULL,
                start_date TEXT NOT NULL,
                listing_url TEXT NOT NULL,
                posts TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 1,
                UNIQUE(artwork_filename, start_date)
            );
            CREATE TABLE IF NOT EXISTS marketing_buffer_posts (
                plan_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                channel_name TEXT NOT NULL,
                due_at TEXT NOT NULL,
                state TEXT NOT NULL,
                buffer_id TEXT,
                PRIMARY KEY (plan_id, platform)
            );
        """)
        project_columns = {row[1] for row in db.execute("PRAGMA table_info(projects)")}
        if "archived" not in project_columns:
            db.execute("ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        if "archive_revision" not in project_columns:
            db.execute("ALTER TABLE projects ADD COLUMN archive_revision INTEGER NOT NULL DEFAULT 1")
        prompt_columns = {row[1] for row in db.execute("PRAGMA table_info(prompts)")}
        if "source" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        if "reviewed" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 1")
        if "trashed" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN trashed INTEGER NOT NULL DEFAULT 0")
        if "parent_prompt_id" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN parent_prompt_id INTEGER")
        if "migrated_from_version" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN migrated_from_version TEXT")
        if "version_test_result" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN version_test_result TEXT")
        if "version_test_notes" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN version_test_notes TEXT NOT NULL DEFAULT ''")
        if "version_tested_at" not in prompt_columns:
            db.execute("ALTER TABLE prompts ADD COLUMN version_tested_at TEXT")
        db.execute("UPDATE prompts SET source = 'chatgpt', reviewed = 0 WHERE category = 'ChatGPT Import' AND source = 'manual'")
        db.execute("UPDATE prompts SET source = 'drive', reviewed = 0 WHERE category = 'Imported' AND source = 'manual'")
        if db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 0:
            db.executemany("INSERT INTO prompts(title, category, text, favorite) VALUES (?, ?, ?, ?)", DEFAULT_PROMPTS)


def rows(query: str, values: tuple[Any, ...] = (), *, connection=None) -> list[dict[str, Any]]:
    if connection is not None:
        return [dict(row) for row in connection.execute(query, values).fetchall()]
    with connect() as db:
        return [dict(row) for row in db.execute(query, values).fetchall()]


def execute(query: str, values: tuple[Any, ...] = ()) -> int:
    with connect() as db:
        cursor = db.execute(query, values)
        return int(cursor.lastrowid)


def backup_data() -> dict[str, Any]:
    with connect() as db:
        # Keep linked projects and prompts in one point-in-time database snapshot.
        db.execute("BEGIN")
        styles = rows("SELECT name, content FROM styles ORDER BY name", connection=db)
        return {
            "version": 12,
            "prompts": rows("SELECT id, title, category, text, favorite, source, reviewed, trashed, parent_prompt_id, migrated_from_version, version_test_result, version_test_notes, version_tested_at FROM prompts ORDER BY id", connection=db),
            "styles": {item["name"]: json.loads(item["content"]) for item in styles},
            "midjourney_rules": json.loads(MIDJOURNEY_RULES_PATH.read_text(encoding="utf-8")),
            "artworks": rows("SELECT id, title, collection, tags, notes, favorite, filename, created_at FROM artworks ORDER BY id", connection=db),
            "projects": [{**item, "materials": json.loads(item["materials"]), "checklist": json.loads(item["checklist"]), "archived": bool(item["archived"])}
                         for item in rows("SELECT * FROM projects ORDER BY created_at, id", connection=db)],
            "project_artworks": rows(
                "SELECT pa.project_id, a.filename, pa.stage, pa.created_at FROM project_artworks pa "
                "JOIN artworks a ON a.id = pa.artwork_id JOIN projects p ON p.id = pa.project_id "
                "ORDER BY pa.created_at, pa.artwork_id", connection=db),
            "project_covers": rows(
                "SELECT pc.project_id, a.filename, pc.revision FROM project_covers pc "
                "JOIN projects p ON p.id = pc.project_id LEFT JOIN artworks a ON a.id = pc.artwork_id "
                "ORDER BY pc.project_id", connection=db),
            "project_journal": [{**item, "deleted": bool(item["deleted"])} for item in rows(
                "SELECT j.* FROM project_journal j JOIN projects p ON p.id = j.project_id "
                "ORDER BY j.project_id, j.entry_date, j.id", connection=db)],
            "creative_kits": [{**item, "preferences": json.loads(item["preferences"])} for item in rows(
                "SELECT id, name, preferences, revision, created_at, updated_at FROM creative_kits ORDER BY name_key, id", connection=db)],
            "marketing_plans": rows(
                "SELECT id, artwork_filename, artwork_title, start_date, listing_url, posts, approved, revision "
                "FROM marketing_plans ORDER BY start_date, id", connection=db
            ),
            "marketing_buffer_posts": rows(
                "SELECT plan_id, platform, channel_name, due_at, state, buffer_id "
                "FROM marketing_buffer_posts ORDER BY plan_id, platform", connection=db
            ),
        }
