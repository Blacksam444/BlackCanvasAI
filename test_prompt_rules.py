import unittest
import json
import sqlite3
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app import (
    ChatGPTImportPayload,
    PromptIdsPayload,
    PromptBulkPayload,
    PromptPayload,
    MidJourneyRulesPayload,
    bulk_delete_prompts,
    bulk_update_prompts,
    bulk_restore_prompts,
    bulk_repair_prompt_syntax,
    bulk_copy_prompts_to_active_midjourney_version,
    create_image_prompt,
    create_prompt,
    copy_prompt_to_active_midjourney_version,
    format_prompt_pack,
    format_version_test_pair,
    get_midjourney_rules,
    import_chatgpt_prompts,
    midjourney_verification_status,
    midjourney_syntax_issues,
    midjourney_parameter_summary,
    prompt_version_comparison,
    repair_midjourney_syntax,
    restore_previous_midjourney_rules,
    restore_midjourney_rules_from_manifest,
    save_midjourney_rules,
)
from storage import backup_data


class PromptRuleTests(unittest.TestCase):
    def test_version_comparison_returns_original_and_migrated_copy(self):
        migrated = {"id": 9, "title": "Guardian (MJ v8.2)", "category": "GraffitiX",
                    "text": "Guardian --raw --v 8.2", "parent_prompt_id": 4, "migrated_from_version": "8.1"}
        original = {"id": 4, "title": "Guardian", "category": "GraffitiX", "text": "Guardian --raw --v 8.1"}
        with patch("app.rows", side_effect=[[migrated], [original]]):
            result = prompt_version_comparison(9)

        self.assertEqual(result["original"]["version"], "8.1")
        self.assertEqual(result["original"]["text"], original["text"])
        self.assertEqual(result["migrated"]["version"], "8.2")
        self.assertEqual(result["migrated"]["text"], migrated["text"])
        self.assertTrue(result["creative_body_preserved"])
        self.assertEqual(result["parameter_changes"], [
            {"parameter": "Version", "original": "8.1", "migrated": "8.2"},
        ])
        self.assertIn("ORIGINAL — MIDJOURNEY V8.1", result["test_pair"])
        self.assertIn("ACTIVE COPY — MIDJOURNEY V8.2", result["test_pair"])

    def test_version_test_pair_keeps_prompts_clearly_separated(self):
        pair = format_version_test_pair(
            {"title": "Original", "text": "Prompt one"},
            {"title": "Copy", "text": "Prompt two"},
            "8.1",
            "8.2",
        )
        self.assertLess(pair.index("Prompt one"), pair.index("ACTIVE COPY"))
        self.assertLess(pair.index("ACTIVE COPY"), pair.index("Prompt two"))

    def test_midjourney_parameter_summary_identifies_legacy_raw_mode(self):
        self.assertEqual(midjourney_parameter_summary("Guardian --ar 4:5 --style raw --v 8.1"), {
            "Aspect ratio": "4:5", "Raw mode": "--style raw", "Version": "8.1",
        })

    def test_active_version_migration_creates_copy_and_keeps_original(self):
        original = {"id": 7, "title": "Archive Guardian", "category": "GraffitiX",
                    "text": "Guardian --style raw --v 8.1"}
        with patch("app.rows", return_value=[original]), patch("app.execute", return_value=44) as execute_mock:
            result = copy_prompt_to_active_midjourney_version(7)

        saved_values = execute_mock.call_args.args[1]
        self.assertEqual(saved_values[0], "Archive Guardian (MJ v8.2)")
        self.assertEqual(saved_values[2], "Guardian --raw --v 8.2")
        self.assertEqual(original["text"], "Guardian --style raw --v 8.1")
        self.assertEqual(result["id"], 44)
        self.assertEqual(saved_values[3:], (7, "8.1"))
        self.assertEqual(result["parent_prompt_id"], 7)
        self.assertEqual(result["migrated_from_version"], "8.1")
        self.assertEqual(result["syntax_issues"], [])

    def test_prompts_using_another_midjourney_version_are_flagged_without_rewrite(self):
        prompt = "Archive portrait --ar 4:5 --raw --v 8.1"

        self.assertEqual(
            midjourney_syntax_issues(prompt),
            ["Uses MidJourney v8.1; active verified rules are v8.2"],
        )
        self.assertEqual(repair_midjourney_syntax(prompt), prompt)

    def test_midjourney_verification_status_has_review_thresholds(self):
        with patch.dict("app.MIDJOURNEY_RULES", {"version": "8.2", "verified_at": "2026-01-01"}, clear=True):
            self.assertEqual(midjourney_verification_status(date(2026, 3, 2))["status"], "current")
            self.assertEqual(midjourney_verification_status(date(2026, 3, 3))["status"], "due")
            self.assertEqual(midjourney_verification_status(date(2026, 4, 2))["status"], "overdue")

    def test_backups_include_and_restore_midjourney_rules(self):
        original_rules = get_midjourney_rules().copy()
        with tempfile.TemporaryDirectory() as directory:
            rules_path = Path(directory) / "midjourney_rules.json"
            rules_path.write_text(json.dumps(original_rules), encoding="utf-8")
            with patch("storage.MIDJOURNEY_RULES_PATH", rules_path), patch("storage.rows", return_value=[]):
                backup = backup_data()
            self.assertEqual(backup["version"], 3)
            self.assertEqual(backup["midjourney_rules"]["version"], original_rules["version"])
            with patch("app.MIDJOURNEY_RULES_PATH", rules_path):
                try:
                    restored = restore_midjourney_rules_from_manifest({"midjourney_rules": {
                        **original_rules,
                        "version": "8.3",
                        "verified_at": "2026-08-17",
                    }})
                    self.assertTrue(restored)
                    self.assertEqual(get_midjourney_rules()["version"], "8.3")
                finally:
                    import app
                    app.MIDJOURNEY_RULES.clear()
                    app.MIDJOURNEY_RULES.update(original_rules)
                    app.DEFAULT_ASPECT_RATIO = original_rules["default_aspect_ratio"]
                    app.SUPPORTED_ASPECT_RATIOS = set(original_rules["supported_aspect_ratios"])

    def test_midjourney_rules_editor_validates_and_persists(self):
        original_rules = get_midjourney_rules().copy()
        with tempfile.TemporaryDirectory() as directory, patch("app.MIDJOURNEY_RULES_PATH", Path(directory) / "rules.json"):
            try:
                result = save_midjourney_rules(MidJourneyRulesPayload(
                    version="8.3",
                    default_aspect_ratio="4:5",
                    supported_aspect_ratios=["4:5", "1:1", "4:5"],
                    raw_parameter="--raw",
                    verified_at="2026-08-17",
                    verification_source="https://docs.midjourney.com/",
                    update_note="Verified test update",
                ))
                self.assertEqual(result["version"], "8.3")
                self.assertEqual(result["supported_aspect_ratios"], ["4:5", "1:1"])
                self.assertEqual(result["verified_at"], "2026-08-17")
                self.assertEqual(result["previous_rules"]["version"], original_rules["version"])
                self.assertEqual(json.loads((Path(directory) / "rules.json").read_text())["version"], "8.3")
                restored = restore_previous_midjourney_rules()
                self.assertEqual(restored["version"], original_rules["version"])
                self.assertEqual(restored["previous_rules"]["version"], "8.3")
            finally:
                import app
                app.MIDJOURNEY_RULES.clear()
                app.MIDJOURNEY_RULES.update(original_rules)
                app.DEFAULT_ASPECT_RATIO = original_rules["default_aspect_ratio"]
                app.SUPPORTED_ASPECT_RATIOS = set(original_rules["supported_aspect_ratios"])

    def test_midjourney_rules_are_centralized_and_exposed(self):
        rules = get_midjourney_rules()

        self.assertEqual(rules["version"], "8.2")
        self.assertEqual(rules["raw_parameter"], "--raw")
        self.assertEqual(rules["deprecated_parameters"]["--style raw"], "--raw")
        self.assertIn(rules["default_aspect_ratio"], rules["supported_aspect_ratios"])

    def test_manual_prompt_save_normalizes_legacy_v82_syntax(self):
        payload = PromptPayload(
            title="Legacy recipe",
            category="GraffitiX",
            text="A raw mixed-media guardian --ar 4:5 --style raw --v 8.2",
        )
        with patch("app.execute", return_value=444) as execute_mock:
            result = create_prompt(payload)
        saved_values = execute_mock.call_args.args[1]
        expected = "A raw mixed-media guardian --ar 4:5 --raw --v 8.2"
        self.assertEqual(saved_values[2], expected)
        self.assertEqual(result["text"], expected)

    def test_chatgpt_import_normalizes_legacy_v82_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "prompts.db"
            cache = root / "candidates.json"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE prompts (id INTEGER PRIMARY KEY, title TEXT, category TEXT, text TEXT UNIQUE, "
                "favorite INTEGER, source TEXT, reviewed INTEGER)"
            )
            connection.commit()
            connection.close()
            cache.write_text(json.dumps([{
                "id": "legacy-444",
                "conversation": "Legacy GraffitiX",
                "text": "A street oracle --ar 4:5 --style raw --v 8.2",
            }]), encoding="utf-8")
            opened_connections = []

            def test_connect():
                opened_connection = sqlite3.connect(database)
                opened_connections.append(opened_connection)
                return opened_connection

            with patch("app.CHATGPT_IMPORT_CACHE", cache), patch("app.connect", test_connect):
                result = import_chatgpt_prompts(ChatGPTImportPayload(candidate_ids=["legacy-444"]))
            for opened_connection in opened_connections:
                opened_connection.close()
            self.assertEqual(result, {"imported": 1, "selected": 1})
            check = sqlite3.connect(database)
            try:
                saved = check.execute("SELECT text FROM prompts").fetchone()[0]
                self.assertEqual(saved, "A street oracle --ar 4:5 --raw --v 8.2")
            finally:
                check.close()

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

    def test_pasted_parameters_are_removed_from_generated_prompt_body(self):
        for collection in ("GraffitiX", "AfroNova"):
            with self.subTest(collection=collection):
                _, prompt = create_image_prompt(
                    f"Create an image prompt for a street guardian --style raw --ar 1:1 --raw --v 7 "
                    f"in the {collection} style. Aspect ratio: 16:9."
                )
                lowered = prompt.lower()
                self.assertNotIn("--style raw", lowered)
                self.assertEqual(lowered.count("--ar"), 1)
                self.assertEqual(lowered.count("--raw"), 1)
                self.assertEqual(lowered.count("--v"), 1)
                self.assertTrue(prompt.endswith("--ar 16:9 --raw --v 8.2"))

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
    def test_bulk_active_version_copy_preserves_originals_and_skips_ineligible(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "prompts.db"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE prompts (id INTEGER PRIMARY KEY, title TEXT, category TEXT, text TEXT, favorite INTEGER DEFAULT 0, "
                "source TEXT DEFAULT 'manual', reviewed INTEGER DEFAULT 1, trashed INTEGER DEFAULT 0, "
                "parent_prompt_id INTEGER, migrated_from_version TEXT, UNIQUE(title, text))"
            )
            connection.executemany("INSERT INTO prompts(id, title, category, text) VALUES (?, ?, ?, ?)", [
                (1, "Old Guardian", "GraffitiX", "Guardian --style raw --v 8.1"),
                (2, "Current Guardian", "GraffitiX", "Guardian --raw --v 8.2"),
            ])
            connection.commit()
            connection.close()

            opened_connections = []

            def test_connect():
                opened = sqlite3.connect(database)
                opened.row_factory = sqlite3.Row
                opened_connections.append(opened)
                return opened

            with patch("app.connect", test_connect):
                result = bulk_copy_prompts_to_active_midjourney_version(PromptIdsPayload(prompt_ids=[1, 2, 1, 99]))
            for opened in opened_connections:
                opened.close()

            self.assertEqual(result, {"selected": 3, "copied": 1, "skipped": 2})
            check = sqlite3.connect(database)
            try:
                self.assertEqual(check.execute("SELECT COUNT(*) FROM prompts").fetchone()[0], 3)
                self.assertEqual(check.execute("SELECT text FROM prompts WHERE id = 1").fetchone()[0],
                                 "Guardian --style raw --v 8.1")
                self.assertEqual(check.execute("SELECT text FROM prompts WHERE id = 3").fetchone()[0],
                                 "Guardian --raw --v 8.2")
                self.assertEqual(check.execute("SELECT parent_prompt_id, migrated_from_version FROM prompts WHERE id = 3").fetchone(),
                                 (1, "8.1"))
            finally:
                check.close()

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


class BackupRestoreSyntaxTests(unittest.TestCase):
    def test_google_restore_normalizes_legacy_midjourney_syntax(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn(
            'repair_midjourney_syntax(str(prompt.get("text", "")).strip())',
            source,
        )


if __name__ == "__main__":
    unittest.main()
