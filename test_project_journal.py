import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest import TestCase
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

import storage
import test_projects as fixtures
from project_journal import (JournalCreate, JournalRevision, JournalUpdate, create_journal_entry,
                             delete_journal_entry, get_journal_entry, list_journal, restore_journal,
                             update_journal_entry, validate_journal_backups)
from projects import (ProjectArchivePayload, ProjectDirectCreatePayload, create_direct_project, get_project,
                      restore_projects, update_project, update_project_archive, validate_project_backups)


class ProjectJournalTests(TestCase):
    setUp = fixtures.ProjectTests.setUp
    payload = fixtures.ProjectTests.payload

    def project(self, suffix="1"):
        return create_direct_project(ProjectDirectCreatePayload(id="direct_" + suffix * 32, title="My study"))["project"]

    def add(self, project_id, suffix="a", **updates):
        return create_journal_entry(project_id, JournalCreate(**{
            "id": "journal_" + suffix * 32, "entry_date": "2026-11-08", "body": "  First glaze\nLet it dry.  ", **updates}))

    def edit(self, entry, **updates):
        return update_journal_entry(entry["project_id"], entry["id"], JournalUpdate(**{
            "entry_date": entry["entry_date"], "body": entry["body"], "revision": entry["revision"], **updates}))

    def test_dated_entries_keep_the_plan_prompt_and_photo_stores_unchanged(self):
        project = self.project()
        before = storage.backup_data()
        entry = self.add(project["id"])["entry"]
        self.assertEqual(entry["body"], "First glaze\nLet it dry.")
        self.assertEqual(entry["entry_date"], "2026-11-08")
        self.assertEqual(entry["revision"], 1)
        self.assertEqual(get_journal_entry(project["id"], entry["id"]), entry)
        self.assertEqual(get_project(project["id"]), project)
        after = storage.backup_data()
        for key in ("projects", "project_covers", "project_artworks", "prompts", "artworks"):
            self.assertEqual(before[key], after[key])

    def test_list_orders_by_artists_calendar_date_and_isolates_projects(self):
        first, second = self.project(), self.project("2")
        older = self.add(first["id"], "a", entry_date="2026-10-30")["entry"]
        newer = self.add(first["id"], "b", entry_date="2026-11-09")["entry"]
        self.add(second["id"], "a", body="Another project")
        self.assertEqual([item["id"] for item in list_journal(first["id"])], [newer["id"], older["id"]])
        self.assertEqual(list_journal(second["id"])[0]["body"], "Another project")
        with self.assertRaises(HTTPException) as error:
            get_journal_entry(second["id"], newer["id"])
        self.assertEqual(error.exception.status_code, 404)

    def test_create_retries_do_not_duplicate_or_replace_later_work(self):
        project = self.project()
        entry = self.add(project["id"])["entry"]
        self.assertEqual(self.add(project["id"]), {"created": False, "entry": entry})
        self.edit(entry, body="Newer reflection")
        with self.assertRaises(HTTPException) as error:
            self.add(project["id"])
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(list_journal(project["id"])), 1)

    def test_update_retry_noop_and_conflict_review_protect_newer_text(self):
        entry = self.add(self.project()["id"])["entry"]
        self.assertEqual(self.edit(entry), entry)
        updated = self.edit(entry, body="A changed reflection", entry_date="2026-11-07")
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(self.edit(entry, body=updated["body"], entry_date=updated["entry_date"]), updated)
        with self.assertRaises(HTTPException) as error:
            self.edit(entry, body="Outdated other-device text")
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(get_journal_entry(entry["project_id"], entry["id"]), updated)

    def test_removal_requires_viewed_revision_and_prevents_late_resurrection(self):
        project = self.project()
        entry = self.add(project["id"])["entry"]
        updated = self.edit(entry, body="New text")
        with self.assertRaises(HTTPException) as error:
            delete_journal_entry(project["id"], entry["id"], JournalRevision(revision=1))
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(list_journal(project["id"])), 1)
        for _ in range(2):
            self.assertEqual(delete_journal_entry(project["id"], entry["id"], JournalRevision(revision=updated["revision"])), {"removed": entry["id"]})
        self.assertEqual(list_journal(project["id"]), [])
        with self.assertRaises(HTTPException) as error:
            self.add(project["id"])
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException) as error:
            self.edit(updated, body="Late edit")
        self.assertEqual(error.exception.status_code, 404)
        removed = storage.backup_data()["project_journal"][0]
        self.assertTrue(removed["deleted"])
        self.assertEqual(removed["body"], "")

    def test_two_concurrent_edits_have_one_winner(self):
        entry = self.add(self.project()["id"])["entry"]
        def attempt(body):
            try:
                return self.edit(entry, body=body)["revision"]
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, ["First device", "Second device"])), [2, 409])

    def test_concurrent_creation_retries_keep_one_entry(self):
        project = self.project()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.add(project["id"])["created"], range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(len(list_journal(project["id"])), 1)

    def test_plan_save_archive_and_reinitialization_preserve_journal_and_reused_plan_starts_empty(self):
        project = self.project()
        entry = self.add(project["id"])["entry"]
        update_project(project["id"], self.payload(project, notes="Independent plan edit"))
        update_project_archive(project["id"], ProjectArchivePayload(archived=True, archive_revision=1))
        updated = self.edit(entry, body="Works while archived")
        storage.initialize()
        self.assertEqual(list_journal(project["id"]), [updated])
        copied = create_direct_project(ProjectDirectCreatePayload(**{
            **{key: project[key] for key in ("title", "status", "materials", "surface", "checklist", "notes")},
            "id": "direct_" + "2" * 32}))["project"]
        self.assertEqual(list_journal(copied["id"]), [])

    def test_validation_rejects_blank_text_timestamps_oversize_and_invalid_revisions(self):
        for updates in ({"body": " \n "}, {"body": "x" * 5001}, {"entry_date": "2026-02-30"},
                        {"entry_date": "2026-11-08T00:00:00Z"}, {"entry_date": 1234}, {"id": "../bad"}):
            with self.subTest(updates=str(updates)[:100]), self.assertRaises(ValidationError):
                JournalCreate(**{"id": "journal_" + "a" * 32, "entry_date": "2026-11-08", "body": "Text", **updates})
        for value in (0, True, "1"):
            with self.assertRaises(ValidationError):
                JournalRevision(revision=value)
        with self.assertRaises(HTTPException) as error:
            self.add("missing")
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(storage.rows("SELECT * FROM project_journal"), [])

    def test_backup_round_trip_restores_entries_and_retry_markers_only_for_new_projects(self):
        project = self.project()
        entry = self.add(project["id"])["entry"]
        removed = self.add(project["id"], "b")["entry"]
        delete_journal_entry(project["id"], removed["id"], JournalRevision(revision=1))
        manifest = json.loads(json.dumps(storage.backup_data()))
        self.assertEqual(manifest["version"], 12)
        backups = validate_journal_backups(manifest)
        with patch("storage.DB_PATH", self.directory / "journal-restored.db"):
            storage.initialize()
            with closing(storage.connect()) as db, db:
                self.assertEqual(restore_journal(db, backups, {project["id"]}), 0)
                restore_projects(db, validate_project_backups(manifest), manifest, lambda text: text)
                self.assertEqual(restore_journal(db, backups, {project["id"]}), 2)
            self.assertEqual(list_journal(project["id"]), [entry])
            updated = self.edit(entry, body="After restore")
            delete_journal_entry(project["id"], entry["id"], JournalRevision(revision=updated["revision"]))
            with closing(storage.connect()) as db, db:
                self.assertEqual(restore_journal(db, backups, set()), 0)
            self.assertEqual(list_journal(project["id"]), [])
            with self.assertRaises(HTTPException):
                self.add(project["id"], "b")

    def test_older_and_invalid_manifests(self):
        self.assertEqual(validate_journal_backups({"version": 11}), [])
        self.add(self.project()["id"])
        entry = storage.backup_data()["project_journal"][0]
        for values in (None, {}, [entry, entry], [{**entry, "body": " "}], [{**entry, "entry_date": 12}],
                       [{**entry, "deleted": "false"}], [{**entry, "project_id": "../bad"}]):
            with self.subTest(values=str(values)[:100]), self.assertRaises(HTTPException) as error:
                validate_journal_backups({"project_journal": values})
            self.assertEqual(error.exception.status_code, 400)

    def test_drive_backup_uses_current_format_and_includes_journal_without_live_calls(self):
        from app import backup_to_google_drive
        entry = self.add(self.project()["id"])["entry"]
        service = MagicMock()
        service.files.return_value.create.return_value.execute.return_value = {"id": "folder", "name": "Local test backup"}
        with patch("app.google_credentials", return_value=object()), \
             patch("app.ensure_google_backup_root", return_value="root"), \
             patch("googleapiclient.discovery.build", return_value=service):
            result = backup_to_google_drive()
        self.assertEqual(result["status"], "backed_up")
        calls = service.files.return_value.create.call_args_list
        manifest_call = next(call for call in calls if call.kwargs["body"]["name"] == "blackcanvas-backup.json")
        media = manifest_call.kwargs["media_body"]
        manifest = json.loads(media.getbytes(0, media.size()))
        self.assertEqual(manifest["backup_format"], manifest["version"])
        self.assertEqual(manifest["version"], 12)
        self.assertEqual(manifest["project_journal"][0]["body"], entry["body"])
