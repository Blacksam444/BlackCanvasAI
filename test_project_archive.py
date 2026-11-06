import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import storage
import test_projects as fixtures
from app import dashboard_summary, list_artworks, repair_midjourney_syntax
from projects import (ProjectArchivePayload, ProjectCreatePayload, ProjectDirectCreatePayload,
                      create_direct_project, create_project, get_project, get_project_archive,
                      restore_projects, update_project, update_project_archive, validate_project_backups)


class ProjectArchiveTests(TestCase):
    setUp = fixtures.ProjectTests.setUp
    project = fixtures.ProjectTests.project
    source = fixtures.ProjectTests.source
    payload = fixtures.ProjectTests.payload
    photo = fixtures.ProjectTests.photo

    def archive(self, project, archived=True):
        return update_project_archive(project["id"], ProjectArchivePayload(
            archived=archived, archive_revision=project["archive_revision"]))

    def test_archive_and_restore_keep_the_plan_status_source_photos_and_image_bytes(self):
        project = self.project()
        project = update_project(project["id"], self.payload(project, status="paused", notes="Try another surface"))
        self.photo(project["id"], "progress")
        before = get_project(project["id"])
        images = {path.name: path.read_bytes() for path in storage.UPLOAD_DIR.iterdir()}
        self.assertEqual(self.archive(before), {"archived": True, "archive_revision": 2})
        archived = get_project(project["id"])
        self.assertEqual({k: v for k, v in archived.items() if k not in {"archived", "archive_revision"}},
                         {k: v for k, v in before.items() if k not in {"archived", "archive_revision"}})
        self.assertTrue(list_artworks()[0]["projects"][0]["archived"])
        self.assertEqual(self.archive(archived, False), {"archived": False, "archive_revision": 3})
        restored = get_project(project["id"])
        self.assertEqual(restored["status"], "paused")
        self.assertEqual(restored["revision"], project["revision"])
        self.assertEqual(restored["checklist"], before["checklist"])
        self.assertEqual(images, {path.name: path.read_bytes() for path in storage.UPLOAD_DIR.iterdir()})

    def test_archive_conflicts_need_review_and_noop_keeps_the_archive_revision(self):
        project = self.project()
        self.archive(project)
        with self.assertRaises(HTTPException) as error:
            self.archive(project)
        self.assertEqual(error.exception.status_code, 409)
        state = get_project_archive(project["id"])
        self.assertEqual(update_project_archive(project["id"], ProjectArchivePayload(archived=True, archive_revision=state["archive_revision"])), state)
        self.assertEqual(update_project_archive(project["id"], ProjectArchivePayload(archived=False, archive_revision=2))["archive_revision"], 3)
        with self.assertRaises(HTTPException) as error:
            update_project_archive(project["id"], ProjectArchivePayload(archived=True, archive_revision=2))
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(get_project_archive(project["id"])["archived"])

    def test_plan_and_archive_writes_are_independent_and_plan_conflicts_still_apply(self):
        project = self.project()
        with ThreadPoolExecutor(max_workers=2) as pool:
            plan = pool.submit(update_project, project["id"], self.payload(project, notes="Saved on another device"))
            archive = pool.submit(self.archive, project)
            plan.result()
            archive.result()
        saved = get_project(project["id"])
        self.assertTrue(saved["archived"])
        self.assertEqual(saved["notes"], "Saved on another device")
        self.assertEqual(saved["revision"], project["revision"] + 1)
        with self.assertRaises(HTTPException) as error:
            update_project(project["id"], self.payload(project, notes="Older plan overwrite"))
        self.assertEqual(error.exception.status_code, 409)
        update_project(project["id"], self.payload(saved, notes="Edit while archived"))
        self.assertTrue(get_project_archive(project["id"])["archived"])

    def test_simultaneous_archive_requests_have_only_one_winner(self):
        project = self.project()
        def attempt(_):
            try:
                return self.archive(project)["archive_revision"]
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(sorted(results), [2, 409])

    def test_home_keeps_total_count_but_excludes_archived_status_counts_and_resume(self):
        active = self.project()
        direct = create_direct_project(ProjectDirectCreatePayload(id="direct_" + "5" * 32,
                                        title="Completed original", status="completed"))["project"]
        self.archive(active)
        self.archive(direct)
        home = dashboard_summary()
        self.assertEqual(home["counts"]["projects"], 2)
        self.assertEqual(home["projects"]["counts"], {
            "planned": 0, "in_progress": 0, "paused": 0, "completed": 0,
            "total": 2, "ongoing": 0, "archived": 2,
        })
        self.assertEqual(home["projects"]["recent"], [])
        self.archive(get_project(active["id"]), False)
        home = dashboard_summary()
        self.assertEqual([p["id"] for p in home["projects"]["recent"]], [active["id"]])
        self.assertEqual(home["projects"]["counts"]["archived"], 1)

    def test_backup_restores_archive_flags_but_preserves_existing_restore_choices(self):
        project = self.project()
        self.archive(project)
        manifest = storage.backup_data()
        self.assertEqual(manifest["version"], 11)
        self.assertIs(manifest["projects"][0]["archived"], True)
        backups = validate_project_backups(json.loads(json.dumps(manifest)))
        with patch("storage.DB_PATH", self.directory / "restored.db"):
            storage.initialize()
            with closing(storage.connect()) as db, db:
                self.assertEqual(restore_projects(db, backups, manifest, repair_midjourney_syntax), 1)
            saved = get_project(project["id"])
            self.assertTrue(saved["archived"])
            self.assertEqual(saved["archive_revision"], 2)
            self.archive(saved, False)
            with closing(storage.connect()) as db, db:
                self.assertEqual(restore_projects(db, backups, manifest, repair_midjourney_syntax), 0)
            self.assertFalse(get_project_archive(project["id"])["archived"])

    def test_older_backups_default_to_current_and_opening_existing_ideas_never_unarchives(self):
        project = self.project()
        manifest = storage.backup_data()
        manifest["version"] = 9
        for item in manifest["projects"]:
            item.pop("archived")
            item.pop("archive_revision")
        backup = validate_project_backups(manifest)[0]
        self.assertFalse(backup.archived)
        self.assertEqual(backup.archive_revision, 1)
        self.archive(project)
        with closing(storage.connect()) as db, db:
            self.assertEqual(restore_projects(db, [backup], manifest, repair_midjourney_syntax), 0)
        self.assertTrue(get_project_archive(project["id"])["archived"])
        reopened = create_project(ProjectCreatePayload(prompt_id=project["source_prompt_id"]))
        self.assertFalse(reopened["created"])
        self.assertTrue(reopened["project"]["archived"])
        payload = ProjectDirectCreatePayload(id="direct_" + "6" * 32, title="My own plan")
        direct = create_direct_project(payload)["project"]
        self.archive(direct)
        self.assertTrue(create_direct_project(payload)["project"]["archived"])

    def test_missing_projects_and_invalid_archive_payloads_do_not_change_data(self):
        for method in (lambda: get_project_archive("missing"), lambda: update_project_archive("missing", ProjectArchivePayload(archived=True, archive_revision=1))):
            with self.assertRaises(HTTPException) as error:
                method()
            self.assertEqual(error.exception.status_code, 404)
        for fields in ({"archived": "true", "archive_revision": 1}, {"archived": 1, "archive_revision": 1},
                       {"archived": True, "archive_revision": 0}, {"archived": True, "archive_revision": "1"}, {"archived": True}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                ProjectArchivePayload(**fields)

    def test_migration_preserves_an_old_project_and_is_safe_to_repeat(self):
        with patch("storage.DB_PATH", self.directory / "legacy.db"):
            with closing(sqlite3.connect(storage.DB_PATH)) as db, db:
                db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, source_prompt_id INTEGER UNIQUE, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned', materials TEXT NOT NULL DEFAULT '[]', surface TEXT NOT NULL DEFAULT '', checklist TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
                db.execute("INSERT INTO projects(id,title,status,notes,created_at,updated_at) VALUES ('legacy','Existing plan','paused','Keep this work','2026-10-27','2026-11-01')")
            storage.initialize()
            storage.initialize()
            saved = get_project("legacy")
            self.assertFalse(saved["archived"])
            self.assertEqual(saved["archive_revision"], 1)
            self.assertEqual(saved["notes"], "Keep this work")
            self.assertEqual(saved["status"], "paused")
            self.assertEqual(saved["updated_at"], "2026-11-01")
