import json
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import storage
import test_projects as fixtures
from app import dashboard_summary, repair_midjourney_syntax
from projects import (ProjectDirectCreatePayload, create_direct_project, get_project, list_projects,
                      restore_projects, update_project, validate_project_backups)
from project_sheets import ProjectSheetPayload, create_project_sheet


class DirectProjectTests(TestCase):
    setUp = fixtures.ProjectTests.setUp
    update_payload = fixtures.ProjectTests.payload
    photo = fixtures.ProjectTests.photo

    def payload(self, **updates):
        return ProjectDirectCreatePayload(**{
            "id": "direct_" + "1" * 32, "title": "My own river study", **updates,
        })

    def test_title_only_starts_a_neutral_project_without_a_prompt(self):
        result = create_direct_project(self.payload(title="  My own river study  "))
        project = result["project"]
        self.assertTrue(result["created"])
        self.assertTrue(project["started_directly"])
        self.assertIsNone(project["source_prompt_id"])
        self.assertIsNone(project["source_prompt"])
        self.assertEqual(project["title"], "My own river study")
        self.assertEqual(project["status"], "planned")
        self.assertEqual(project["materials"], [])
        self.assertEqual(project["surface"], "")
        self.assertEqual(project["notes"], "")
        self.assertEqual(project["checklist"], [])
        self.assertEqual(project["revision"], 1)
        self.assertEqual(project["progress"]["total"], 0)
        self.assertEqual(storage.rows("SELECT * FROM prompts"), [])
        self.assertEqual(len(list_projects()), 1)

    def test_full_plan_preserves_user_choices_and_existing_editor_works(self):
        project = create_direct_project(self.payload(status="in_progress", materials=[" Graphite ", "My paper", "Graphite"],
            surface="  My surface  ", notes=" Try soft edges. ",
            checklist=[{"id": "first", "text": "Study the shapes"}, {"id": "second", "text": "Develop the edges"}]))["project"]
        self.assertEqual(project["materials"], ["Graphite", "My paper"])
        self.assertEqual(project["surface"], "My surface")
        self.assertEqual(project["notes"], "Try soft edges.")
        saved = update_project(project["id"], self.update_payload(project, status="completed",
            checklist=[{**step, "done": True} for step in project["checklist"]]))
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["progress"]["percent"], 100)
        self.assertIsNone(saved["source_prompt"])

    def test_same_creation_retry_is_idempotent_after_normalization(self):
        payload = self.payload(materials=["Graphite", "Graphite"], notes=" Notes ",
                               checklist=[{"id": "one", "text": " First pass "}])
        first = create_direct_project(payload)
        retried = create_direct_project(self.payload(materials=["Graphite"], notes="Notes",
                                                   checklist=[{"id": "one", "text": "First pass"}]))
        self.assertTrue(first["created"])
        self.assertFalse(retried["created"])
        self.assertEqual(first["project"], retried["project"])
        self.assertEqual(len(list_projects()), 1)

    def test_changed_retry_requires_explicit_separate_project_without_overwriting(self):
        project = create_direct_project(self.payload(notes="Original notes"))["project"]
        for changes in ({"title": "Another title"}, {"notes": "New notes"}, {"status": "paused"},
                        {"materials": ["Paint"]}, {"checklist": [{"id": "step", "text": "A new step"}]}):
            with self.subTest(changes=changes), self.assertRaises(HTTPException) as error:
                create_direct_project(self.payload(**{"notes": "Original notes", **changes}))
            self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(get_project(project["id"]), project)
        separate = create_direct_project(self.payload(id="direct_" + "2" * 32, notes="New notes"))["project"]
        self.assertNotEqual(separate["id"], project["id"])
        self.assertEqual(len(list_projects()), 2)
        self.assertEqual(storage.rows("SELECT * FROM prompts"), [])

    def test_simultaneous_identical_requests_create_exactly_one_project(self):
        payload = self.payload(notes="One project even if two requests arrive together")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create_direct_project(payload), range(2)))
        self.assertEqual(sorted(result["created"] for result in results), [False, True])
        self.assertEqual(results[0]["project"], results[1]["project"])
        self.assertEqual(len(list_projects()), 1)

    def test_retry_does_not_replace_progress_saved_on_another_device(self):
        original = self.payload(notes="Starting notes")
        project = create_direct_project(original)["project"]
        saved = update_project(project["id"], self.update_payload(project, status="paused", notes="Later notes"))
        with self.assertRaises(HTTPException) as error:
            create_direct_project(original)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(get_project(project["id"]), saved)

    def test_invalid_or_oversize_direct_plans_and_ids_do_not_write(self):
        for changes in ({"title": " "}, {"title": "x" * 201}, {"id": "a" * 32}, {"id": "direct_../unsafe"},
                        {"id": "direct_" + "A" * 32}, {"status": "invented"}, {"surface": "x" * 241},
                        {"materials": ["x" * 241]}, {"materials": [str(i) for i in range(31)]},
                        {"notes": "x" * 5001}, {"checklist": [{"id": "step", "text": " "}]},
                        {"checklist": [{"id": "same", "text": "One"}, {"id": "same", "text": "Two"}]}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.payload(**changes)
        self.assertEqual(list_projects(), [])

    def test_direct_project_backup_restores_without_creating_or_linking_prompts(self):
        original = create_direct_project(self.payload(status="paused", notes="Keep these notes"))["project"]
        manifest = storage.backup_data()
        self.assertEqual(manifest["version"], 12)
        self.assertEqual(manifest["prompts"], [])
        backups = validate_project_backups(json.loads(json.dumps(manifest)))
        with patch("storage.DB_PATH", self.directory / "restored.db"):
            storage.initialize()
            with storage.connect() as db:
                self.assertEqual(restore_projects(db, backups, manifest, repair_midjourney_syntax), 1)
            restored = get_project(original["id"])
            self.assertEqual(restored, original)
            updated = update_project(restored["id"], self.update_payload(restored, notes="Work after restore"))
            with storage.connect() as db:
                self.assertEqual(restore_projects(db, backups, manifest, repair_midjourney_syntax), 0)
            self.assertEqual(get_project(original["id"]), updated)
            self.assertEqual(storage.rows("SELECT * FROM prompts"), [])

    def test_direct_project_supports_photos_home_and_portable_sheets(self):
        project = create_direct_project(self.payload(materials=["Graphite"], notes="My studio notes"))["project"]
        photo = self.photo(project["id"], "progress")
        home = dashboard_summary()
        self.assertEqual(home["counts"]["projects"], 1)
        self.assertEqual(home["counts"]["prompts"], 0)
        self.assertEqual(home["projects"]["recent"][0]["id"], project["id"])
        self.assertEqual(home["projects"]["recent"][0]["cover"]["url"], photo["url"])
        sheet = create_project_sheet(project["id"], ProjectSheetPayload(plan=self.update_payload(project),
                                     include_source=True, photo_ids=[photo["id"]]))
        self.assertIn("Started directly in Projects; no source idea linked.", sheet["text"])
        self.assertNotIn("Source idea unavailable", sheet["html"])
        self.assertIn("data:image/png;base64,", sheet["html"])
        self.assertEqual(get_project(project["id"])["revision"], 1)
