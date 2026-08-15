import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from app import (
    PromptIdsPayload,
    bulk_delete_prompts,
    create_image_prompt,
    midjourney_syntax_issues,
    repair_midjourney_syntax,
)


class PromptRuleTests(unittest.TestCase):
    def test_graffitix_uses_v82_raw_and_hierarchy(self):
        collection, prompt = create_image_prompt(
            "Create an image prompt for a street dancer in the GraffitiX style"
        )
        self.assertEqual(collection, "GraffitiX")
        self.assertTrue(prompt.endswith("--ar 4:5 --raw --v 8.2"))
        self.assertNotIn("--style raw", prompt)
        self.assertIn("one dominant hero symbol", prompt.lower())
        self.assertIn("one or two small supporting symbols", prompt.lower())
        self.assertIn("no digital smoothness", prompt.lower())
        self.assertIn("no watermark", prompt.lower())

    def test_other_collections_keep_negative_defaults_and_v82_suffix(self):
        collection, prompt = create_image_prompt(
            "Create an image prompt for a regal visionary in the AfroNova style"
        )
        self.assertEqual(collection, "AfroNova")
        self.assertTrue(prompt.endswith("--ar 4:5 --raw --v 8.2"))
        self.assertIn("no text, no watermark, no signature, no logo, no frame", prompt)

    def test_graffitix_builder_directions_are_used(self):
        collection, prompt = create_image_prompt(
            "Create an image prompt for a street oracle in the GraffitiX style. "
            "Pose: low crouched stance with a compressed S-curve; "
            "Camera: a pavement-level tracking shot; "
            "Hero symbol: a distorted hand-drawn crown in thick red oil stick."
        )
        self.assertEqual(collection, "GraffitiX")
        self.assertIn("Engineer low crouched stance with a compressed S-curve", prompt)
        self.assertIn("Use a pavement-level tracking shot", prompt)
        self.assertIn("one dominant hero symbol—a distorted hand-drawn crown", prompt)

    def test_supported_aspect_ratio_is_used(self):
        _, prompt = create_image_prompt(
            "Create an image prompt for a cosmic queen in the AfroNova style. Aspect ratio: 16:9."
        )
        self.assertTrue(prompt.endswith("--ar 16:9 --raw --v 8.2"))

    def test_unsupported_aspect_ratio_falls_back_to_portrait(self):
        _, prompt = create_image_prompt(
            "Create an image prompt for a cosmic queen in the AfroNova style. Aspect ratio: 99:1."
        )
        self.assertTrue(prompt.endswith("--ar 4:5 --raw --v 8.2"))

    def test_legacy_raw_syntax_is_detected_and_repaired(self):
        legacy = "A mixed-media portrait --ar 4:5 --style raw --v 8.2"
        self.assertEqual(midjourney_syntax_issues(legacy), ["Legacy --style raw syntax"])
        self.assertEqual(
            repair_midjourney_syntax(legacy),
            "A mixed-media portrait --ar 4:5 --raw --v 8.2",
        )

    def test_missing_raw_is_detected_and_repaired(self):
        legacy = "A mixed-media portrait --ar 4:5 --v 8.2"
        self.assertEqual(midjourney_syntax_issues(legacy), ["MidJourney v8.2 prompt is missing --raw"])
        self.assertEqual(
            repair_midjourney_syntax(legacy),
            "A mixed-media portrait --ar 4:5 --raw --v 8.2",
        )


class PromptBulkDeleteTests(unittest.TestCase):
    def test_bulk_delete_removes_only_selected_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prompts.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY, title TEXT)")
            connection.executemany("INSERT INTO prompts(id, title) VALUES (?, ?)", [(1, "Keep"), (2, "Extra"), (3, "Other")])
            connection.commit()
            connection.close()

            opened_connections = []

            def test_connect():
                connection = sqlite3.connect(database)
                opened_connections.append(connection)
                return connection

            with patch("app.connect", test_connect):
                result = bulk_delete_prompts(PromptIdsPayload(prompt_ids=[2, 2]))
            for opened_connection in opened_connections:
                opened_connection.close()

            self.assertEqual(result, {"deleted": 1})
            check = sqlite3.connect(database)
            try:
                self.assertEqual(check.execute("SELECT id FROM prompts ORDER BY id").fetchall(), [(1,), (3,)])
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
