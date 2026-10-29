import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import storage
import test_projects as project_fixtures
from creative_kits import (
    CreativePreferences, KitPayload, KitUpdatePayload, create_kit, delete_kit,
    list_kits, restore_kits, update_kit, validate_kit_backups,
)


class CreativeKitTests(unittest.TestCase):
    setUp = project_fixtures.ProjectTests.setUp
    source = project_fixtures.ProjectTests.source
    project = project_fixtures.ProjectTests.project

    def kit(self, name="My graphite kit", **preferences):
        return create_kit(KitPayload(name=name, preferences=CreativePreferences(
            **{"other_materials": "Graphite", "surface": "paper", "palette": "Cool gray", **preferences})))

    def update(self, kit, **changes):
        return KitUpdatePayload(**{"name": kit["name"], "preferences": kit["preferences"], "revision": kit["revision"], **changes})

    def test_new_studios_have_no_presets_and_preferences_never_store_the_subject(self):
        self.assertEqual(list_kits(), [])
        payload = KitPayload(name="Blank starting point", preferences={"direction": "Private subject", "studio_notes": "Private idea notes"})
        kit = create_kit(payload)["kit"]
        self.assertNotIn("direction", kit["preferences"])
        self.assertNotIn("studio_notes", kit["preferences"])
        self.assertEqual(kit["preferences"]["collection"], "My own direction")
        self.assertEqual(kit["preferences"]["palette"], "")
        self.assertEqual(kit["preferences"]["materials"], [])

    def test_kits_persist_normalized_preferences_without_a_second_prompt_store(self):
        saved = self.kit(materials=["charcoal", "acrylic", "charcoal"], style_direction=" Loose marks ", avoid="Gloss")
        storage.initialize()
        self.assertEqual(list_kits()[0]["id"], saved["kit"]["id"])
        self.assertEqual(list_kits()[0]["preferences"]["materials"], ["acrylic", "charcoal"])
        self.assertEqual(list_kits()[0]["preferences"]["style_direction"], "Loose marks")
        self.assertEqual(storage.rows("SELECT id FROM prompts"), [])
        self.assertEqual(storage.rows("SELECT id FROM projects"), [])

    def test_create_retry_is_idempotent_and_case_insensitive_name_conflicts_do_not_overwrite(self):
        first = self.kit()
        repeated = self.kit(" my GRAPHITE kit ")
        self.assertFalse(repeated["created"])
        self.assertEqual(first["kit"]["id"], repeated["kit"]["id"])
        with self.assertRaises(HTTPException) as error:
            self.kit("MY graphite KIT", palette="Warm copper")
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(list_kits()), 1)
        self.assertEqual(list_kits()[0]["preferences"]["palette"], "Cool gray")

    def test_stale_updates_and_deletes_cannot_replace_another_device_save(self):
        original = self.kit()["kit"]
        saved = update_kit(original["id"], self.update(original, preferences={**original["preferences"], "palette": "Warm copper"}))
        self.assertEqual(saved["revision"], 2)
        with self.assertRaises(HTTPException) as update_error:
            update_kit(original["id"], self.update(original, name="Stale rename"))
        self.assertEqual(update_error.exception.status_code, 409)
        with self.assertRaises(HTTPException) as delete_error:
            delete_kit(original["id"], revision=original["revision"])
        self.assertEqual(delete_error.exception.status_code, 409)
        self.assertEqual(list_kits()[0]["preferences"]["palette"], "Warm copper")

    def test_rename_collisions_are_rolled_back_and_missing_kits_are_reported(self):
        first = self.kit()["kit"]
        self.kit("Another kit")
        with self.assertRaises(HTTPException) as error:
            update_kit(first["id"], self.update(first, name=" ANOTHER KIT "))
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(next(kit for kit in list_kits() if kit["id"] == first["id"])["revision"], 1)
        for missing in ("missing", "' OR 1=1 --"):
            with self.assertRaises(HTTPException) as error:
                update_kit(missing, self.update(first))
            self.assertEqual(error.exception.status_code, 404)
            with self.assertRaises(HTTPException) as error:
                delete_kit(missing, revision=1)
            self.assertEqual(error.exception.status_code, 404)

    def test_removing_a_kit_keeps_existing_prompts_and_projects(self):
        project = self.project()
        kit = self.kit()["kit"]
        self.assertEqual(delete_kit(kit["id"], revision=kit["revision"]), {"status": "removed"})
        self.assertEqual(list_kits(), [])
        self.assertEqual(storage.rows("SELECT id FROM projects")[0]["id"], project["id"])
        self.assertEqual(len(storage.rows("SELECT id FROM prompts")), 1)

    def test_backup_round_trip_restores_kits_and_keeps_existing_edits_or_names(self):
        kit = self.kit()["kit"]
        manifest = storage.backup_data()
        self.assertEqual(manifest["version"], 9)
        self.assertIsInstance(manifest["creative_kits"][0]["preferences"], dict)
        backups = validate_kit_backups(json.loads(json.dumps(manifest)))
        with patch("storage.DB_PATH", self.directory / "kits-restored.db"):
            storage.initialize()
            with storage.connect() as db:
                self.assertEqual(restore_kits(db, backups), 1)
            restored = list_kits()[0]
            self.assertEqual(restored, kit)
            update_kit(restored["id"], self.update(restored, preferences={"palette": "New choices"}))
            with storage.connect() as db:
                self.assertEqual(restore_kits(db, backups), 0)
            self.assertEqual(list_kits()[0]["preferences"]["palette"], "New choices")
        with patch("storage.DB_PATH", self.directory / "kit-name-conflict.db"):
            storage.initialize()
            self.kit(palette="Keep my existing kit")
            with storage.connect() as db:
                self.assertEqual(restore_kits(db, backups), 0)
            self.assertEqual(list_kits()[0]["preferences"]["palette"], "Keep my existing kit")

    def test_validation_rejects_bad_names_preferences_and_backup_records(self):
        for name in (" ", "x" * 81):
            with self.assertRaises(ValidationError):
                self.kit(name)
        for preferences in ({"materials": ["unknown"]}, {"surface": "unknown"}, {"palette": "x" * 2601},
                            {"style_direction": "x" * 601}, {"avoid": "x" * 1201}):
            with self.subTest(preferences=preferences), self.assertRaises(ValidationError):
                self.kit(**preferences)
        self.assertEqual(validate_kit_backups({"version": 8}), [])
        for manifest in ({"creative_kits": {}}, {"creative_kits": [{"id": "invalid"}]}):
            with self.assertRaises(HTTPException) as error:
                validate_kit_backups(manifest)
            self.assertEqual(error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
