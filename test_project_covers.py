import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import storage
import test_projects as fixtures
from app import dashboard_summary, delete_artwork
from project_covers import CoverPayload, get_cover, restore_covers, update_cover, validate_cover_backups
from projects import (ProjectArtworkPayload, ProjectDirectCreatePayload, create_direct_project, get_project,
                      link_project_artwork, list_projects, restore_project_artworks, restore_projects,
                      unlink_project_artwork, update_project, validate_project_artwork_backups, validate_project_backups)


class ProjectCoverTests(TestCase):
    setUp = fixtures.ProjectTests.setUp
    photo = fixtures.ProjectTests.photo
    payload = fixtures.ProjectTests.payload

    def project(self, suffix="1"):
        return create_direct_project(ProjectDirectCreatePayload(id="direct_" + suffix * 32, title=f"My study {suffix}"))["project"]

    def choose(self, project_id, artwork_id, revision=None):
        if revision is None:
            revision = get_cover(project_id)["cover_revision"]
        return update_cover(project_id, CoverPayload(artwork_id=artwork_id, cover_revision=revision))

    def test_user_can_choose_a_reference_and_keep_it_after_new_progress_photos(self):
        project = self.project()
        reference = self.photo(project["id"], "reference")
        progress = self.photo(project["id"], "progress")
        self.assertEqual(get_cover(project["id"])["cover"]["artwork_id"], progress["id"])
        before = get_project(project["id"])
        chosen = self.choose(project["id"], reference["id"])
        self.assertEqual(chosen["cover"]["mode"], "chosen")
        self.assertEqual(chosen["cover"]["stage"], "reference")
        self.assertEqual(chosen["cover_revision"], 2)
        self.photo(project["id"], "finished")
        self.assertEqual(get_project(project["id"])["cover"]["artwork_id"], reference["id"])
        self.assertEqual(list_projects()[0]["cover"]["artwork_id"], reference["id"])
        self.assertEqual(dashboard_summary()["projects"]["recent"][0]["cover"]["artwork_id"], reference["id"])
        after = get_project(project["id"])
        for key in ("title", "status", "materials", "notes", "surface", "checklist", "revision", "updated_at", "archive_revision", "archived"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(len(list(storage.UPLOAD_DIR.iterdir())), 3)

    def test_revision_conflict_noop_and_automatic_reset(self):
        project = self.project()
        photo = self.photo(project["id"], "progress")
        automatic = self.choose(project["id"], None)
        self.assertEqual(automatic["cover_revision"], 1)
        chosen = self.choose(project["id"], photo["id"], 1)
        self.assertEqual(self.choose(project["id"], photo["id"], 2), chosen)
        with self.assertRaises(HTTPException) as error:
            self.choose(project["id"], None, 1)
        self.assertEqual(error.exception.status_code, 409)
        reset = self.choose(project["id"], None, 2)
        self.assertEqual(reset["cover_revision"], 3)
        self.assertEqual(reset["cover"]["mode"], "automatic")
        self.assertIsNone(reset["cover_artwork_id"])

    def test_choices_are_independent_when_an_image_is_linked_to_two_projects(self):
        first, second = self.project(), self.project("2")
        photo = self.photo(first["id"], "reference")
        link_project_artwork(second["id"], ProjectArtworkPayload(artwork_id=photo["id"], stage="reference"))
        self.choose(first["id"], photo["id"])
        self.assertIsNone(get_cover(second["id"])["cover"])
        self.choose(second["id"], photo["id"])
        result = unlink_project_artwork(first["id"], photo["id"])
        self.assertIsNone(result["cover_artwork_id"])
        self.assertEqual(result["cover_revision"], 3)
        self.assertEqual(get_cover(second["id"])["cover_artwork_id"], photo["id"])
        delete_artwork(photo["id"])
        self.assertIsNone(get_cover(second["id"])["cover_artwork_id"])
        self.assertEqual(get_cover(second["id"])["cover_revision"], 3)

    def test_unlinked_missing_and_unsafe_images_cannot_be_chosen(self):
        project = self.project()
        other = self.photo()
        for project_id, artwork_id in ((project["id"], other["id"]), (project["id"], 999999), ("missing", other["id"])):
            with self.subTest(project_id=project_id), self.assertRaises(HTTPException) as error:
                self.choose(project_id, artwork_id, 1)
            self.assertEqual(error.exception.status_code, 404)
        photo = self.photo(project["id"])
        filename = storage.rows("SELECT filename FROM artworks WHERE id=?", (photo["id"],))[0]["filename"]
        (storage.UPLOAD_DIR / filename).unlink()
        with self.assertRaises(HTTPException) as error:
            self.choose(project["id"], photo["id"])
        self.assertEqual(error.exception.status_code, 422)
        (self.directory / "outside.png").write_bytes(b"Fixture outside uploads")
        storage.execute("UPDATE artworks SET filename = '../outside.png' WHERE id = ?", (photo["id"],))
        with self.assertRaises(HTTPException) as error:
            self.choose(project["id"], photo["id"])
        self.assertEqual(error.exception.status_code, 422)

    def test_missing_chosen_image_is_identified_without_silently_switching_the_choice(self):
        project = self.project()
        chosen, other = self.photo(project["id"]), self.photo(project["id"])
        state = self.choose(project["id"], chosen["id"])
        filename = storage.rows("SELECT filename FROM artworks WHERE id=?", (chosen["id"],))[0]["filename"]
        (storage.UPLOAD_DIR / filename).unlink()
        missing = get_cover(project["id"])
        self.assertTrue(missing["cover_unavailable"])
        self.assertEqual(missing["cover_artwork_id"], chosen["id"])
        self.assertIsNone(missing["cover"])
        automatic = self.choose(project["id"], None, state["cover_revision"])
        self.assertEqual(automatic["cover"]["artwork_id"], other["id"])

    def test_only_one_concurrent_cover_choice_can_replace_a_viewed_revision(self):
        project = self.project()
        photos = [self.photo(project["id"]), self.photo(project["id"])]
        def attempt(photo):
            try:
                return self.choose(project["id"], photo["id"], 1)["cover_revision"]
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, photos)), [2, 409])

    def test_cover_choice_does_not_invalidate_plan_edits_or_change_when_plan_saves(self):
        project = self.project()
        photo = self.photo(project["id"])
        self.choose(project["id"], photo["id"])
        saved = update_project(project["id"], self.payload(project, notes="Plan edited independently"))
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["cover_revision"], 2)
        self.assertEqual(saved["cover_artwork_id"], photo["id"])
        storage.initialize()
        self.assertEqual(get_cover(project["id"])["cover_artwork_id"], photo["id"])

    def test_backup_restores_by_filename_after_artwork_ids_change_and_keeps_later_choices(self):
        project = self.project()
        photo = self.photo(project["id"], "reference")
        self.choose(project["id"], photo["id"])
        manifest = storage.backup_data()
        self.assertEqual(manifest["version"], 12)
        self.assertNotIn("artwork_id", manifest["project_covers"][0])
        covers = validate_cover_backups(json.loads(json.dumps(manifest)))
        with patch("storage.DB_PATH", self.directory / "restored.db"):
            storage.initialize()
            self.photo()  # Occupy the old numeric artwork ID with an unrelated image.
            with closing(storage.connect()) as db, db:
                for item in manifest["artworks"]:
                    db.execute("INSERT INTO artworks(title,collection,filename) VALUES (?,?,?)", (item["title"], item["collection"], item["filename"]))
                restore_projects(db, validate_project_backups(manifest), manifest, lambda text: text)
                restore_project_artworks(db, validate_project_artwork_backups(manifest), {project["id"]})
                self.assertEqual(restore_covers(db, covers, {project["id"]}), 1)
            restored = get_cover(project["id"])
            self.assertNotEqual(restored["cover_artwork_id"], photo["id"])
            self.assertEqual(restored["cover"]["url"], photo["url"])
            self.choose(project["id"], None)
            with closing(storage.connect()) as db, db:
                self.assertEqual(restore_covers(db, covers, set()), 0)
            self.assertIsNone(get_cover(project["id"])["cover_artwork_id"])

    def test_old_backups_and_invalid_payloads_are_handled_without_changes(self):
        self.assertEqual(validate_cover_backups({"version": 10}), [])
        for data in ({"artwork_id": None, "cover_revision": 0}, {"artwork_id": True, "cover_revision": 1},
                     {"artwork_id": -1, "cover_revision": 1}, {"artwork_id": 1}, {"cover_revision": 1}):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                CoverPayload(**data)
        valid = {"project_id": "safe", "filename": "safe.png", "revision": 2}
        for values in ({}, [{**valid, "filename": "../unsafe.png"}], [{**valid, "filename": "C:\\unsafe.png"}],
                       [{**valid, "revision": 0}], [valid, valid]):
            with self.subTest(values=values), self.assertRaises(HTTPException) as error:
                validate_cover_backups({"project_covers": values})
            self.assertEqual(error.exception.status_code, 400)
