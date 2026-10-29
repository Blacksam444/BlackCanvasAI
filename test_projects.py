import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import (PromptPayload, ThinkTankPayload, create_prompt, generate_think_tank_ideas, repair_midjourney_syntax,
                 ArtworkPayload, create_artwork, delete_artwork, list_artworks, restore_google_backup)
from projects import (
    ProjectCreatePayload, ProjectUpdatePayload, create_project, get_project, list_projects,
    projects_page, restore_projects, seed_project, update_project, validate_project_backups,
    ProjectArtworkPayload, link_project_artwork, unlink_project_artwork, validate_project_artwork_backups,
    restore_project_artworks,
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
        self.stack.enter_context(patch("app.UPLOAD_DIR", self.directory / "uploads"))
        self.stack.enter_context(patch("storage.DB_PATH", self.directory / "source.db"))

        def connect():
            db = sqlite3.connect(storage.DB_PATH, factory=ClosingConnection)
            db.row_factory = sqlite3.Row
            return db

        self.stack.enter_context(patch("storage.connect", connect))
        self.stack.enter_context(patch("app.connect", connect))
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
        self.assertEqual(manifest["version"], 8)
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

    def photo(self, project_id=None, stage="progress"):
        return create_artwork(ArtworkPayload(
            title="My studio photo", collection="My collection", notes="Testing the texture.",
            data_url="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=",
            project_id=project_id, project_stage=stage,
        ))

    def test_upload_links_one_catalog_image_without_changing_the_project_plan(self):
        project = self.project()
        photo = self.photo(project["id"], "finished")
        reopened = get_project(project["id"])
        self.assertEqual(reopened["revision"], project["revision"])
        self.assertEqual(reopened["status"], "planned")
        self.assertEqual(reopened["checklist"], project["checklist"])
        self.assertEqual([(item["id"], item["stage"]) for item in reopened["artworks"]], [(photo["id"], "finished")])
        self.assertEqual(len(list_artworks()), 1)
        self.assertEqual(list_artworks()[0]["projects"][0]["project_id"], project["id"])
        self.assertEqual(len(list(storage.UPLOAD_DIR.iterdir())), 1)

    def test_existing_artwork_link_is_idempotent_and_unlink_keeps_catalog_image(self):
        project = self.project()
        photo = self.photo()
        payload = ProjectArtworkPayload(artwork_id=photo["id"], stage="reference")
        self.assertTrue(link_project_artwork(project["id"], payload)["created"])
        self.assertFalse(link_project_artwork(project["id"], payload)["created"])
        self.assertEqual(len(get_project(project["id"])["artworks"]), 1)
        self.assertEqual(unlink_project_artwork(project["id"], photo["id"])["artworks"], [])
        self.assertEqual(list_artworks()[0]["projects"], [])
        self.assertEqual(len(list(storage.UPLOAD_DIR.iterdir())), 1)
        self.assertEqual(unlink_project_artwork(project["id"], photo["id"])["artworks"], [])

    def test_photo_can_belong_to_two_projects_and_catalog_deletion_cleans_all_links(self):
        first = self.project()
        source = create_prompt(PromptPayload(title="Another idea", category="My own direction", text="A river study"))
        second = create_project(ProjectCreatePayload(prompt_id=source["id"]))["project"]
        photo = self.photo(first["id"])
        link_project_artwork(second["id"], ProjectArtworkPayload(artwork_id=photo["id"], stage="reference"))
        self.assertEqual(len(list_artworks()[0]["projects"]), 2)
        delete_artwork(photo["id"])
        self.assertEqual(get_project(first["id"])["artworks"], [])
        self.assertEqual(get_project(second["id"])["artworks"], [])
        self.assertEqual(storage.rows("SELECT * FROM project_artworks"), [])
        self.assertEqual(list(storage.UPLOAD_DIR.iterdir()), [])

    def test_missing_photo_or_project_cannot_create_a_link_or_upload(self):
        project = self.project()
        photo = self.photo()
        for project_id, photo_id in (("missing", photo["id"]), (project["id"], 999999)):
            with self.assertRaises(HTTPException) as error:
                link_project_artwork(project_id, ProjectArtworkPayload(artwork_id=photo_id))
            self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as error:
            self.photo("missing")
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(len(list_artworks()), 1)
        self.assertEqual(len(list(storage.UPLOAD_DIR.iterdir())), 1)
        with self.assertRaises(ValidationError):
            ProjectArtworkPayload(artwork_id=photo["id"], stage="invented")

    def test_failed_upload_transaction_removes_file_and_catalog_row(self):
        project = self.project()
        with patch("app.attach_artwork", side_effect=RuntimeError("Simulated failure")):
            with self.assertRaises(RuntimeError):
                self.photo(project["id"])
        self.assertEqual(list_artworks(), [])
        self.assertEqual(get_project(project["id"])["artworks"], [])
        self.assertEqual(list(storage.UPLOAD_DIR.iterdir()), [])

    def test_invalid_photo_data_is_rejected_without_writing_files(self):
        for data in ("data:image/png;base64,%%%%", "data:text/plain;base64,aGVsbG8=", "data:image/png;base64,"):
            with self.subTest(data=data), self.assertRaises(HTTPException) as error:
                create_artwork(ArtworkPayload(title="My image", collection="Unsorted", data_url=data))
            self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(list(storage.UPLOAD_DIR.iterdir()), [])

    def test_photo_backup_remaps_catalog_ids_and_preserves_existing_unlinks(self):
        project = self.project()
        original = self.photo(project["id"], "reference")
        manifest = storage.backup_data()
        links = validate_project_artwork_backups(manifest)
        self.assertEqual(len(links), 1)
        self.assertNotIn("artwork_id", manifest["project_artworks"][0])
        with patch("storage.DB_PATH", self.directory / "photo-restore.db"):
            storage.initialize()
            self.photo()  # Occupy the previous catalog ID.
            filename = manifest["artworks"][0]["filename"]
            remapped_id = storage.execute("INSERT INTO artworks(title, collection, filename) VALUES (?, ?, ?)", ("Restored photo", "My collection", filename))
            with storage.connect() as db:
                restore_projects(db, validate_project_backups(manifest), manifest, repair_midjourney_syntax)
                self.assertEqual(restore_project_artworks(db, links, {project["id"]}), 1)
            restored = get_project(project["id"])["artworks"][0]
            self.assertEqual(restored["id"], remapped_id)
            self.assertNotEqual(restored["id"], original["id"])
            self.assertEqual(restored["stage"], "reference")
            unlink_project_artwork(project["id"], remapped_id)
            with storage.connect() as db:
                self.assertEqual(restore_project_artworks(db, links, set()), 0)
            self.assertEqual(get_project(project["id"])["artworks"], [])

    def test_old_photo_backups_and_missing_catalog_items_restore_without_broken_links(self):
        self.assertEqual(validate_project_artwork_backups({"version": 7}), [])
        project = self.project()
        self.photo(project["id"])
        links = validate_project_artwork_backups(storage.backup_data())
        with storage.connect() as db:
            db.execute("DELETE FROM project_artworks")
            db.execute("DELETE FROM artworks")
            self.assertEqual(restore_project_artworks(db, links, {project["id"]}), 0)
        self.assertEqual(get_project(project["id"])["artworks"], [])

    def test_photo_backup_uses_one_snapshot_when_an_image_arrives_during_export(self):
        project = self.project()
        self.photo(project["id"])
        with storage.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
        original_rows = storage.rows
        late = {}

        def read_during_upload(query, values=(), *, connection=None):
            result = original_rows(query, values, connection=connection)
            if "FROM artworks ORDER BY id" in query and not late:
                late["photo"] = self.photo(project["id"], "finished")["id"]
            return result

        with patch("storage.rows", read_during_upload):
            manifest = storage.backup_data()
        self.assertEqual(len(manifest["artworks"]), 1)
        self.assertEqual(len(manifest["project_artworks"]), 1)
        self.assertNotIn(late["photo"], {item["id"] for item in manifest["artworks"]})
        self.assertEqual(manifest["project_artworks"][0]["filename"], manifest["artworks"][0]["filename"])
        self.assertEqual(len(get_project(project["id"])["artworks"]), 2)

    def test_photo_backup_rejects_invalid_stages_and_paths_before_restore(self):
        project = self.project()
        self.photo(project["id"])
        link = storage.backup_data()["project_artworks"][0]
        for filename in ("../escape.png", "..\\escape.png", "C:escape.png", ".", ".."):
            with self.subTest(filename=filename), self.assertRaises(HTTPException):
                validate_project_artwork_backups({"project_artworks": [{**link, "filename": filename}]})
        for manifest in ({"project_artworks": {}}, {"project_artworks": [{**link, "stage": "invalid"}]}):
            with self.assertRaises(HTTPException):
                validate_project_artwork_backups(manifest)

    def test_folder_restore_recovers_photo_files_and_links_without_live_drive_calls(self):
        project = self.project()
        self.photo(project["id"], "finished")
        manifest = storage.backup_data()
        filename = manifest["artworks"][0]["filename"]
        image_bytes = (storage.UPLOAD_DIR / filename).read_bytes()
        files = MagicMock()
        files.get.return_value.execute.return_value = {"mimeType": "application/vnd.google-apps.folder",
            "appProperties": {"blackcanvas_backup_set": "true", "backup_state": "complete"}}
        files.list.return_value.execute.return_value = {"files": [
            {"id": "manifest", "name": "blackcanvas-backup.json"}, {"id": "image", "name": filename},
        ]}

        def get_media(*, fileId):
            request = MagicMock()
            request.execute.return_value = json.dumps(manifest).encode() if fileId == "manifest" else image_bytes
            return request

        files.get_media.side_effect = get_media
        service = MagicMock()
        service.files.return_value = files
        upload_path = self.directory / "restored-uploads"
        with patch("storage.DB_PATH", self.directory / "folder-restore.db"), patch("storage.UPLOAD_DIR", upload_path), \
             patch("app.UPLOAD_DIR", upload_path), patch("app.google_credentials", return_value=object()), \
             patch("googleapiclient.discovery.build", return_value=service), patch("app.restore_midjourney_rules_from_manifest", return_value=False):
            storage.initialize()
            self.source("An unrelated idea occupying the old prompt ID")
            self.photo()  # The old catalog ID also belongs to unrelated work.
            restored = restore_google_backup("local-fixture")
            self.assertEqual((restored["projects"], restored["project_photos"], restored["images"]), (1, 1, 1))
            photo = get_project(project["id"])["artworks"][0]
            self.assertEqual(photo["stage"], "finished")
            self.assertEqual((upload_path / filename).read_bytes(), image_bytes)
            self.assertNotEqual(photo["id"], manifest["artworks"][0]["id"])
            unlink_project_artwork(project["id"], photo["id"])
            repeated = restore_google_backup("local-fixture")
            self.assertEqual((repeated["projects"], repeated["project_photos"]), (0, 0))
            self.assertEqual(get_project(project["id"])["artworks"], [])
            self.assertEqual(len(list_artworks()), 2)


if __name__ == "__main__":
    unittest.main()
