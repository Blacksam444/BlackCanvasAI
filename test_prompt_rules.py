import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from app import (
    PromptIdsPayload,
    PromptBulkPayload,
    bulk_delete_prompts,
    bulk_update_prompts,
    bulk_restore_prompts,
    bulk_repair_prompt_syntax,
    create_image_prompt,
    format_prompt_pack,
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
            "Wardrobe: baggy charcoal denim with a tied bandana; "
            "Hero symbol: a distorted hand-drawn crown in thick red oil stick; "
            "Supporting symbols: two tiny xxx marks used as quiet accents; "
            "Physical media: dominant oil stick with dry charcoal drag marks and exposed raw canvas; "
            "Background marks: minimal scratched paint and faint ledger numbers; "
            "Lighting: a hot-magenta side light cut by a cold cyan rim light."
        )
        self.assertEqual(collection, "GraffitiX")
        self.assertIn("Engineer low crouched stance with a compressed S-curve", prompt)
        self.assertIn("Use a pavement-level tracking shot", prompt)
        self.assertIn("baggy charcoal denim with a tied bandana", prompt)
        self.assertIn("one dominant hero symbol—a distorted hand-drawn crown", prompt)
        self.assertIn("supporting layer with one or two small supporting symbols—two tiny xxx marks used as quiet accents", prompt)
        self.assertIn("Physical media treatment: dominant oil stick with dry charcoal drag marks and exposed raw canvas", prompt)
        self.assertIn("secondary background layer—minimal scratched paint and faint ledger numbers", prompt)
        self.assertIn("Light the scene with a hot-magenta side light cut by a cold cyan rim light", prompt)

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

    def test_prompt_pack_preserves_order_and_flags_syntax(self):
        pack = format_prompt_pack([
            {"title": "Second Idea", "category": "GraffitiX", "text": "Portrait --style raw --v 8.2"},
            {"title": "First Idea", "category": "AfroNova", "text": "Cosmic queen --raw --v 8.2"},
        ])
        self.assertIn("2 prompts", pack)
        self.assertLess(pack.index("1. Second Idea [GraffitiX]"), pack.index("2. First Idea [AfroNova]"))
        self.assertIn("SYNTAX CHECK: Legacy --style raw syntax", pack)
        self.assertEqual(pack.count("SYNTAX CHECK:"), 1)


class PromptBulkDeleteTests(unittest.TestCase):
    def test_bulk_delete_removes_only_selected_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prompts.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY, title TEXT, trashed INTEGER NOT NULL DEFAULT 0)")
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

            self.assertEqual(result, {"trashed": 1})
            check = sqlite3.connect(database)
            try:
                self.assertEqual(check.execute("SELECT id, trashed FROM prompts ORDER BY id").fetchall(),
                                 [(1, 0), (2, 1), (3, 0)])
            finally:
                check.close()


class PromptBulkUpdateTests(unittest.TestCase):
    def test_bulk_favorite_updates_only_active_selected_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prompts.db"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE prompts (id INTEGER PRIMARY KEY, favorite INTEGER NOT NULL DEFAULT 0, trashed INTEGER NOT NULL DEFAULT 0)"
            )
            connection.executemany("INSERT INTO prompts(id, favorite, trashed) VALUES (?, ?, ?)",
                                   [(1, 0, 0), (2, 0, 0), (3, 0, 1)])
            connection.commit()
            connection.close()
            opened_connections = []

            def test_connect():
                opened_connection = sqlite3.connect(database)
                opened_connections.append(opened_connection)
                return opened_connection

            with patch("app.connect", test_connect):
                result = bulk_update_prompts(PromptBulkPayload(prompt_ids=[2, 3, 3], favorite=True))
            for opened_connection in opened_connections:
                opened_connection.close()

            self.assertEqual(result, {"updated": 1})
            check = sqlite3.connect(database)
            try:
                self.assertEqual(check.execute("SELECT id, favorite FROM prompts ORDER BY id").fetchall(),
                                 [(1, 0), (2, 1), (3, 0)])
            finally:
                check.close()

    def test_bulk_restore_returns_only_trashed_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prompts.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY, trashed INTEGER NOT NULL DEFAULT 0)")
            connection.executemany("INSERT INTO prompts(id, trashed) VALUES (?, ?)", [(1, 0), (2, 1), (3, 1)])
            connection.commit()
            connection.close()
            opened_connections = []

            def test_connect():
                opened_connection = sqlite3.connect(database)
                opened_connections.append(opened_connection)
                return opened_connection

            with patch("app.connect", test_connect):
                result = bulk_restore_prompts(PromptIdsPayload(prompt_ids=[2, 2]))
            for opened_connection in opened_connections:
                opened_connection.close()

            self.assertEqual(result, {"restored": 1})
            check = sqlite3.connect(database)
            try:
                self.assertEqual(check.execute("SELECT id, trashed FROM prompts ORDER BY id").fetchall(),
                                 [(1, 0), (2, 0), (3, 1)])
            finally:
                check.close()


class PromptBulkRepairTests(unittest.TestCase):
    def test_bulk_repair_changes_only_supported_selected_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prompts.db"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE prompts (id INTEGER PRIMARY KEY, text TEXT UNIQUE, reviewed INTEGER NOT NULL DEFAULT 0, trashed INTEGER NOT NULL DEFAULT 0)"
            )
            connection.executemany("INSERT INTO prompts(id, text) VALUES (?, ?)", [
                (1, "Legacy --style raw --v 8.2"),
                (2, "Already ready --raw --v 8.2"),
                (3, "Not selected --style raw --v 8.2"),
            ])
            connection.commit()
            connection.close()

            opened_connections = []

            def test_connect():
                opened_connection = sqlite3.connect(database)
                opened_connections.append(opened_connection)
                return opened_connection

            with patch("app.connect", test_connect):
                result = bulk_repair_prompt_syntax(PromptIdsPayload(prompt_ids=[1, 2, 2]))
            for opened_connection in opened_connections:
                opened_connection.close()

            self.assertEqual(result, {"repaired": 1, "skipped": 1})
            check = sqlite3.connect(database)
            try:
                self.assertEqual(check.execute("SELECT text, reviewed FROM prompts WHERE id = 1").fetchone(),
                                 ("Legacy --raw --v 8.2", 1))
                self.assertEqual(check.execute("SELECT text FROM prompts WHERE id = 3").fetchone()[0],
                                 "Not selected --style raw --v 8.2")
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
