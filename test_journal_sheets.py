from contextlib import closing
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import storage
import test_projects as fixtures
from project_journal import (JournalCreate, JournalRevision, JournalUpdate, create_journal_entry,
                             delete_journal_entry, get_journal_entry, update_journal_entry)
from project_sheets import JournalSheetSelection, ProjectSheetPayload, create_project_sheet
from projects import (ProjectArchivePayload, ProjectDirectCreatePayload, create_direct_project,
                      get_project, read_project, update_project, update_project_archive)


class JournalSheetTests(TestCase):
    setUp = fixtures.ProjectTests.setUp
    payload = fixtures.ProjectTests.payload
    photo = fixtures.ProjectTests.photo

    def project(self, suffix="1"):
        return create_direct_project(ProjectDirectCreatePayload(id="direct_" + suffix * 32, title="My layers study",
                                                               notes="Private plan notes"))["project"]

    def entry(self, project, suffix="a", **updates):
        return create_journal_entry(project["id"], JournalCreate(**{
            "id": "journal_" + suffix * 32, "entry_date": "2026-11-08", "body": "A session reflection", **updates}))["entry"]

    def selection(self, *entries):
        return [{"id": entry["id"], "revision": entry["revision"]} for entry in entries]

    def sheet(self, project, **updates):
        return create_project_sheet(project["id"], ProjectSheetPayload(**{"plan": self.payload(project), **updates}))

    def test_default_sheet_omits_every_journal_entry_and_explicit_selection_exports_only_those_chosen(self):
        project = self.project()
        older = self.entry(project, "a", entry_date="2026-10-28", body="Older chosen session")
        newer = self.entry(project, "b", body="Newer chosen session")
        self.entry(project, "c", body="Private unselected session")
        before = storage.backup_data()
        default = self.sheet(project)
        self.assertEqual(default["journal_count"], 0)
        for key in ("html", "text"):
            self.assertNotIn("chosen session", default[key])
            self.assertNotIn("Private unselected session", default[key])
        sheet = self.sheet(project, journal_entries=self.selection(older, newer))
        self.assertEqual(sheet["journal_count"], 2)
        for key in ("html", "text"):
            self.assertLess(sheet[key].index("Newer chosen session"), sheet[key].index("Older chosen session"))
            self.assertNotIn("Private unselected session", sheet[key])
            self.assertNotIn(older["id"], sheet[key])
        self.assertEqual(storage.backup_data(), before)

    def test_saved_journal_is_independent_of_plan_notes_source_and_current_plan_edits(self):
        project = self.project()
        entry = self.entry(project, body="My explicitly chosen reflection")
        sheet = self.sheet(project, include_notes=False, include_source=False, journal_entries=self.selection(entry),
                           plan=self.payload(project, title="My unsaved title", notes="Private unfinished plan notes"))
        self.assertEqual(sheet["snapshot"], "Copy of current edits")
        for key in ("html", "text"):
            self.assertIn("My explicitly chosen reflection", sheet[key])
            self.assertIn("My unsaved title", sheet[key])
            self.assertNotIn("Private plan notes", sheet[key])
            self.assertNotIn("Private unfinished plan notes", sheet[key])
        self.assertEqual(get_project(project["id"]), project)
        self.assertEqual(get_journal_entry(project["id"], entry["id"]), entry)

    def test_selected_entry_text_is_escaped_and_multiline_calendar_dates_are_preserved(self):
        project = self.project()
        body = '<script>alert("journal")</script>\nPaper & ink <img src=x onerror=alert(1)>'
        entry = self.entry(project, entry_date="2026-01-01", body=body)
        sheet = self.sheet(project, journal_entries=self.selection(entry))
        self.assertIn(body, sheet["text"])
        self.assertIn("&lt;script&gt;", sheet["html"])
        self.assertNotIn("<script>", sheet["html"])
        self.assertNotIn("<img src=x", sheet["html"])
        self.assertIn('<time datetime="2026-01-01">2026-01-01</time>', sheet["html"])
        self.assertIn("Paper &amp; ink", sheet["html"])

    def test_changed_removed_missing_and_other_project_entries_require_review(self):
        project, other = self.project(), self.project("2")
        changed = self.entry(project)
        update_journal_entry(project["id"], changed["id"], JournalUpdate(entry_date=changed["entry_date"], body="Saved elsewhere", revision=1))
        removed = self.entry(project, "b")
        delete_journal_entry(project["id"], removed["id"], JournalRevision(revision=1))
        foreign = self.entry(other, "c")
        missing = {"id": "journal_" + "d" * 32, "revision": 1}
        for entry in (changed, removed, foreign, missing):
            with self.subTest(id=entry["id"]), self.assertRaises(HTTPException) as error:
                self.sheet(project, journal_entries=self.selection(entry))
            self.assertEqual(error.exception.status_code, 409)
            self.assertIn("Refresh saved entries", error.exception.detail)
        latest = get_journal_entry(project["id"], changed["id"])
        self.assertIn("Saved elsewhere", self.sheet(project, journal_entries=self.selection(latest))["text"])

    def test_entry_selection_rejects_duplicates_missing_versions_noninteger_versions_and_more_than_thirty(self):
        project = self.project()
        entry = self.entry(project)
        for values in (self.selection(entry, entry), [{"id": entry["id"]}], [{"id": entry["id"], "revision": 0}],
                       [{"id": entry["id"], "revision": True}], [{"id": entry["id"], "revision": "1"}],
                       [{"id": "../invalid", "revision": 1}],
                       [{"id": f"journal_{index:032x}", "revision": 1} for index in range(31)]):
            with self.subTest(values=str(values)[:100]), self.assertRaises(ValidationError):
                ProjectSheetPayload(plan=self.payload(project), journal_entries=values)
        self.assertEqual(JournalSheetSelection(id=entry["id"], revision=1).revision, 1)

    def test_archived_plan_and_stale_device_export_keep_selected_entries_and_photos(self):
        project = self.project()
        photo = self.photo(project["id"])
        entry = self.entry(project)
        update_project_archive(project["id"], ProjectArchivePayload(archived=True, archive_revision=1))
        update_project(project["id"], self.payload(project, notes="Newer phone plan notes"))
        before = storage.backup_data()
        sheet = self.sheet(project, journal_entries=self.selection(entry), photo_ids=[photo["id"]])
        self.assertIn("Newer changes", sheet["warning"])
        self.assertIn("A session reflection", sheet["html"])
        self.assertIn('src="data:image/png;base64,', sheet["html"])
        self.assertNotIn("Newer phone plan notes", sheet["html"])
        self.assertEqual(storage.backup_data(), before)

    def test_plan_and_journal_use_one_read_snapshot_during_a_concurrent_write(self):
        project = self.project()
        entry = self.entry(project, body="Entry at the start of the snapshot")
        with closing(storage.connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")

        def read_then_write(db, project_id):
            result = read_project(db, project_id)
            update_journal_entry(project_id, entry["id"], JournalUpdate(
                entry_date=entry["entry_date"], body="Entry written during the export", revision=entry["revision"]))
            return result

        with patch("project_sheets.read_project", side_effect=read_then_write):
            sheet = self.sheet(project, journal_entries=self.selection(entry))
        self.assertIn("Entry at the start of the snapshot", sheet["text"])
        self.assertNotIn("Entry written during the export", sheet["text"])
        self.assertEqual(get_journal_entry(project["id"], entry["id"])["body"], "Entry written during the export")
