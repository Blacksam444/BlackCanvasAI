import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import PromptPayload, ThinkTankPayload, create_prompt, generate_think_tank_ideas, repair_midjourney_syntax
from projects import (
    ProjectCreatePayload, ProjectUpdatePayload, create_project, get_project, list_projects,
    projects_page, restore_projects, seed_project, update_project, validate_project_backups,
)
import storage


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch("storage.DATA_DIR", self.directory))
        self.stack.enter_context(patch("storage.UPLOAD_DIR", self.directory / "uploads"))
        self.stack.enter_context(patch("storage.DB_PATH", self.directory / "source.db"))

        def connect():
            db = sqlite3.connect(storage.DB_PATH, factory=ClosingConnection)
            db.row_factory = sqlite3.Row
            return db

        self.stack.enter_context(patch("storage.connect", connect))
        storage.initialize()

    def source(self, text=None):
        if text is None:
            text = generate_think_tank_ideas(ThinkTankPayload(
                direction="A misty forest", other_materials="Graphite", surface="paper",
                studio_notes="Test a small study first.",
            ))["ideas"][0]["text"]
        return create_prompt(PromptPayload(title="My forest idea", category="My own direction", text=text))

    def project(self):
        return create_project(ProjectCreatePayload(prompt_id=self.source()["id"]))["project"]

    def payload(self, project, **updates):
        keys = ("title", "status", "materials", "surface", "checklist", "notes", "revision")
        return ProjectUpdatePayload(**{**{key: project[key] for key in keys}, **updates})

    def test_project_starts_from_library_without_duplicating_the_prompt(self):
        source = self.source()
        result = create_project(ProjectCreatePayload(prompt_id=source["id"]))
        project = result["project"]
        self.assertTrue(result["created"])
        self.assertEqual(project["source_prompt_id"], source["id"])
        self.assertEqual(project["source_prompt"]["text"], source["text"])
        self.assertEqual(project["materials"], ["Graphite"])
        self.assertEqual(project["surface"], "Heavy mixed-media paper")
        self.assertEqual(project["notes"], "Test a small study first.")
        self.assertGreater(len(project["checklist"]), 2)
        self.assertEqual(project["progress"]["done"], 0)
        self.assertEqual(len(storage.rows("SELECT id FROM prompts")), 1)

    def test_repeated_start_opens_the_same_project_and_keeps_existing_work(self):
        project = self.project()
        updated = update_project(project["id"], self.payload(project, notes="My saved work"))
        reopened = create_project(ProjectCreatePayload(prompt_id=project["source_prompt_id"]))
        self.assertFalse(reopened["created"])
        self.assertEqual(reopened["project"]["id"], project["id"])
        self.assertEqual(reopened["project"]["notes"], updated["notes"])
        self.assertEqual(len(list_projects()), 1)

    def test_direct_handoff_preserves_structured_steps_and_material_descriptions(self):
        source = self.source()
        seed = {"materials": ["My mix, including salt"], "surface": "My chosen surface", "notes": "My studio notes",
                "checklist": [{"id": "step_1", "text": "My own multiline\nstudio step", "done": False}]}
        project = create_project(ProjectCreatePayload(prompt_id=source["id"], seed=seed))["project"]
        self.assertEqual(project["materials"], seed["materials"])
        self.assertEqual(project["checklist"], seed["checklist"])
        self.assertEqual(project["surface"], seed["surface"])

    def test_progress_title_materials_steps_notes_and_status_survive_reload(self):
        project = self.project()
        steps = [{**step, "done": index == 0} for index, step in enumerate(project["checklist"])]
        updated = update_project(project["id"], self.payload(project, title="My finished study", status="in_progress",
            checklist=steps, materials=["Graphite", " Graphite ", "Soft paper"], notes="Keep the edges quiet."))
        reloaded = get_project(project["id"])
        self.assertEqual(reloaded["revision"], 2)
        self.assertEqual(reloaded["title"], "My finished study")
        self.assertEqual(reloaded["status"], "in_progress")
        self.assertEqual(reloaded["materials"], ["Graphite", "Soft paper"])
        self.assertEqual(reloaded["notes"], "Keep the edges quiet.")
        self.assertEqual(reloaded["progress"]["done"], 1)
        self.assertEqual(reloaded["progress"]["percent"], round(100 / len(steps)))
        self.assertEqual(updated, reloaded)

    def test_stale_device_cannot_overwrite_a_newer_save(self):
        original = self.project()
        update_project(original["id"], self.payload(original, notes="Saved on my phone"))
        with self.assertRaises(HTTPException) as error:
            update_project(original["id"], self.payload(original, notes="Stale computer edits"))
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(get_project(original["id"])["notes"], "Saved on my phone")

    def test_regular_prompts_start_without_imposed_project_materials_or_steps(self):
        source = self.source("I want to explore botanical line work in my own way.")
        project = create_project(ProjectCreatePayload(prompt_id=source["id"]))["project"]
        self.assertEqual(project["checklist"], [])
        self.assertEqual(project["materials"], [])
        self.assertEqual(project["surface"], "")
        self.assertEqual(project["progress"], {"done": 0, "total": 0, "percent": 0})

    def test_trashed_source_does_not_remove_an_existing_project(self):
        project = self.project()
        storage.execute("UPDATE prompts SET trashed = 1 WHERE id = ?", (project["source_prompt_id"],))
        reopened = create_project(ProjectCreatePayload(prompt_id=project["source_prompt_id"]))["project"]
        self.assertTrue(reopened["source_prompt"]["trashed"])
        self.assertEqual(len(reopened["checklist"]), len(project["checklist"]))
        self.assertEqual(reopened["id"], project["id"])

    def test_new_projects_need_an_existing_active_source(self):
        source = self.source()
        storage.execute("UPDATE prompts SET trashed = 1 WHERE id = ?", (source["id"],))
        for source_id in (source["id"], 999999):
            with self.assertRaises(HTTPException) as error:
                create_project(ProjectCreatePayload(prompt_id=source_id))
            self.assertEqual(error.exception.status_code, 404)

    def test_validation_rejects_empty_steps_duplicate_ids_and_invalid_status(self):
        project = self.project()
        for updates in ({"title": "  "}, {"status": "invented"}, {"notes": "x" * 5001},
                        {"materials": ["x" * 241]}, {"checklist": [{"id": "one", "text": " "}]},
                        {"checklist": [{"id": "one", "text": "First"}, {"id": "one", "text": "Second"}]}):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                self.payload(project, **updates)

    def test_missing_projects_return_404_without_affecting_other_data(self):
        project = self.project()
        for missing in ("missing", "' OR 1=1 --"):
            with self.assertRaises(HTTPException) as error:
                get_project(missing)
            self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as error:
            update_project("missing", self.payload(project))
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(len(list_projects()), 1)

    def test_backup_restores_progress_with_remapped_source_ids_and_keeps_newer_work(self):
        project = self.project()
        project = update_project(project["id"], self.payload(project, status="paused", notes="Try a wider surface.",
            checklist=[{**step, "done": True} for step in project["checklist"]]))
        manifest = storage.backup_data()
        self.assertEqual(manifest["version"], 7)
        self.assertIsInstance(manifest["projects"][0]["checklist"], list)
        backups = validate_project_backups(json.loads(json.dumps(manifest)))
        with patch("storage.DB_PATH", self.directory / "restored.db"):
            storage.initialize()
            self.source("Unrelated prompt occupying the old ID")
            restored_source = self.source(manifest["prompts"][0]["text"])
            with storage.connect() as db:
                self.assertEqual(restore_projects(db, backups, manifest, repair_midjourney_syntax), 1)
            restored = get_project(project["id"])
            self.assertEqual(restored["source_prompt_id"], restored_source["id"])
            self.assertNotEqual(restored["source_prompt_id"], project["source_prompt_id"])
            self.assertEqual(restored["notes"], project["notes"])
            self.assertEqual(restored["checklist"], project["checklist"])
            updated = update_project(restored["id"], self.payload(restored, notes="Work after the restore"))
            with storage.connect() as db:
                self.assertEqual(restore_projects(db, backups, manifest, repair_midjourney_syntax), 0)
            self.assertEqual(get_project(project["id"])["notes"], updated["notes"])

    def test_backup_with_missing_source_still_recovers_project_work(self):
        project = self.project()
        manifest = storage.backup_data()
        manifest["prompts"] = []
        with patch("storage.DB_PATH", self.directory / "orphan.db"):
            storage.initialize()
            with storage.connect() as db:
                restore_projects(db, validate_project_backups(manifest), manifest, repair_midjourney_syntax)
            restored = get_project(project["id"])
            self.assertIsNone(restored["source_prompt"])
            self.assertEqual(restored["checklist"], project["checklist"])

    def test_backup_keeps_projects_and_sources_in_one_snapshot_during_concurrent_saves(self):
        self.project()
        with storage.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
        original_rows = storage.rows
        late = {}

        def read_with_concurrent_save(query, values=(), *, connection=None):
            result = original_rows(query, values, connection=connection)
            if "FROM prompts" in query and not late:
                source = create_prompt(PromptPayload(title="A later save", category="My own direction", text="New work during backup"))
                late["source"] = source["id"]
                late["project"] = create_project(ProjectCreatePayload(prompt_id=source["id"]))["project"]["id"]
            return result

        with patch("storage.rows", read_with_concurrent_save):
            manifest = storage.backup_data()
        self.assertNotIn(late["source"], {item["id"] for item in manifest["prompts"]})
        self.assertNotIn(late["project"], {item["id"] for item in manifest["projects"]})
        self.assertEqual(len(list_projects()), 2)

    def test_old_backups_work_and_invalid_project_backups_are_rejected(self):
        self.assertEqual(validate_project_backups({"version": 6, "prompts": []}), [])
        for manifest in ([], {"projects": {}}, {"projects": [{"id": "invalid"}]}):
            with self.subTest(manifest=manifest), self.assertRaises(HTTPException) as error:
                validate_project_backups(manifest)
            self.assertEqual(error.exception.status_code, 400)

    def test_schema_initialization_preserves_project_progress(self):
        project = self.project()
        storage.initialize()
        self.assertEqual(get_project(project["id"])["checklist"], project["checklist"])

    def test_project_page_and_all_navigation_links_exist(self):
        self.assertTrue(Path(projects_page().path).is_file())
        for path in Path("templates").glob("*.html"):
            self.assertIn('href="/projects"', path.read_text(encoding="utf-8"))

    def test_plain_or_incomplete_plan_text_does_not_invent_a_checklist(self):
        for text in ("Materials: blue paint\n1. An ordinary prompt", "ART THINK TANK · PHYSICAL ART\nNo studio plan"):
            self.assertEqual(seed_project(text)["checklist"], [])


if __name__ == "__main__":
    unittest.main()
