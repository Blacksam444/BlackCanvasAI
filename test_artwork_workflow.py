import unittest

from fastapi import HTTPException
from pydantic import ValidationError

import storage
import test_projects as fixtures
from app import (ArtworkDetailsPayload, artwork_details_version, delete_artwork, favorite_artwork, list_artworks, update_artwork)
from projects import ProjectArtworkPayload, get_project, link_project_artwork


class ArtworkWorkflowTests(unittest.TestCase):
    setUp = fixtures.ProjectTests.setUp
    photo = fixtures.ProjectTests.photo
    source = fixtures.ProjectTests.source
    project = fixtures.ProjectTests.project

    def artwork(self, project_id=None):
        result = self.photo(project_id)
        return next(item for item in list_artworks() if item["id"] == result["id"])

    def payload(self, artwork, **changes):
        values = {key: artwork[key] for key in ("title", "collection", "tags", "notes")}
        return ArtworkDetailsPayload(**{**values, "expected_details_version": artwork["details_version"], **changes})

    def test_created_and_listed_artwork_have_matching_details_versions(self):
        created = self.photo()
        listed = list_artworks()[0]
        self.assertEqual(created["details_version"], listed["details_version"])
        self.assertEqual(listed["details_version"], artwork_details_version(listed))
        self.assertEqual(len(created["details_version"]), 64)

    def test_fresh_edits_save_with_a_version_matching_the_actual_trimmed_fields(self):
        artwork = self.artwork()
        saved = update_artwork(artwork["id"], self.payload(artwork, title="  My renamed study  ", notes="  Updated notes  "))
        listed = list_artworks()[0]
        self.assertEqual(listed["title"], "My renamed study")
        self.assertEqual(listed["notes"], "Updated notes")
        self.assertEqual(saved["details_version"], listed["details_version"])
        self.assertNotEqual(saved["details_version"], artwork["details_version"])

    def test_stale_device_cannot_overwrite_newer_artwork_details(self):
        original = self.artwork()
        saved = update_artwork(original["id"], self.payload(original, notes="Newer phone notes"))
        with self.assertRaises(HTTPException) as error:
            update_artwork(original["id"], self.payload(original, notes="Older computer notes"))
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(list_artworks()[0]["notes"], "Newer phone notes")
        # Explicitly reviewed newer details can be the base for a new save.
        reviewed = {**original, **saved}
        update_artwork(original["id"], self.payload(reviewed, notes="My reviewed changes"))
        self.assertEqual(list_artworks()[0]["notes"], "My reviewed changes")

    def test_stale_delete_preserves_the_image_and_project_links(self):
        project = self.project()
        original = self.artwork(project["id"])
        update_artwork(original["id"], self.payload(original, title="A newer title"))
        with self.assertRaises(HTTPException) as error:
            delete_artwork(original["id"], expected_details_version=original["details_version"])
        self.assertEqual(error.exception.status_code, 409)
        self.assertTrue((storage.UPLOAD_DIR / original["filename"]).is_file())
        self.assertEqual(get_project(project["id"])["artworks"][0]["id"], original["id"])
        current = list_artworks()[0]
        delete_artwork(current["id"], expected_details_version=current["details_version"])
        self.assertEqual(get_project(project["id"])["artworks"], [])

    def test_favorites_and_project_links_do_not_create_false_details_conflicts(self):
        project = self.project()
        original = self.artwork()
        favorite_artwork(original["id"], True)
        link_project_artwork(project["id"], ProjectArtworkPayload(artwork_id=original["id"], stage="reference"))
        self.assertEqual(list_artworks()[0]["details_version"], original["details_version"])
        update_artwork(original["id"], self.payload(original, notes="My caption"))
        self.assertTrue(list_artworks()[0]["favorite"])
        self.assertEqual(get_project(project["id"])["artworks"][0]["notes"], "My caption")

    def test_missing_records_and_invalid_versions_report_errors(self):
        original = self.artwork()
        with self.assertRaises(HTTPException) as error:
            update_artwork(999999, self.payload(original))
        self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as error:
            favorite_artwork(999999, True)
        self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(ValidationError):
            self.payload(original, expected_details_version="invalid")
        with self.assertRaises(HTTPException):
            update_artwork(original["id"], self.payload(original, title="   "))

    def test_legacy_api_calls_remain_compatible_and_backups_need_no_derived_version(self):
        artwork = self.artwork()
        saved = update_artwork(artwork["id"], ArtworkDetailsPayload(title="Legacy caller", collection="My collection"))
        self.assertEqual(saved["title"], "Legacy caller")
        manifest = storage.backup_data()
        self.assertEqual(manifest["version"], 10)
        self.assertNotIn("details_version", manifest["artworks"][0])
        delete_artwork(artwork["id"])
        self.assertEqual(list_artworks(), [])


if __name__ == "__main__":
    unittest.main()
