import tempfile
import sqlite3
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import (
    PromptPayload, ThinkTankPayload, create_prompt, generate_think_tank_ideas,
    list_prompts, think_tank, think_tank_options,
)
from storage import backup_data, initialize


class ThinkTankTests(unittest.TestCase):
    def payload(self, **changes):
        return ThinkTankPayload(**{
            "materials": ["acrylic", "collage", "pastel"],
            "direction": "An ancestral portrait in quiet strength",
            "collection": "Quiet Nova", **changes,
        })

    def generate(self, **changes):
        with patch("app.list_styles", return_value={}):
            return generate_think_tank_ideas(self.payload(**changes))

    def test_three_distinct_plans_keep_the_brief_and_material_order(self):
        result = self.generate(materials=["pastel", "collage", "acrylic", "acrylic"])
        self.assertEqual(result["engine"], "local")
        ideas = result["ideas"]
        self.assertEqual(len(ideas), 3)
        self.assertEqual(len({idea["composition"] for idea in ideas}), 3)
        for idea in ideas:
            self.assertEqual(idea["category"], "Quiet Nova")
            self.assertEqual(idea["materials"], ["Acrylic paint", "Paper collage", "Oil pastel"])
            self.assertIn("An ancestral portrait in quiet strength", idea["text"])
            self.assertIn("Keep oil pastel for the final marks", idea["text"])
            self.assertIn("STUDIO PLAN", idea["text"])
            self.assertIn("OPTIONAL IMAGE REFERENCE PROMPT", idea["text"])

    def test_remix_changes_all_compositions_and_keeps_inputs(self):
        original = self.generate()["ideas"]
        remixed = self.generate(variation=1)["ideas"]
        for before, after in zip(original, remixed):
            self.assertNotEqual(before["composition"], after["composition"])
            self.assertEqual(before["materials"], after["materials"])
            self.assertEqual(before["category"], after["category"])
            self.assertEqual(before["surface"], after["surface"])

    def test_saved_style_rules_and_palette_reach_the_plan(self):
        style = {"colors": ["#123456", "#ABCDEF"], "mood": ["Joyful"],
                 "ingredients": ["Handmade geometry"], "dos": ["Keep dignity"], "donts": ["Neon"]}
        with patch("app.list_styles", return_value={"Quiet Nova": style}):
            ideas = generate_think_tank_ideas(self.payload())["ideas"]
        for idea in ideas:
            self.assertEqual(idea["palette"], "#123456, #ABCDEF")
            self.assertEqual(idea["mood"], "Joyful")
            self.assertIn("Handmade geometry", idea["text"])
            self.assertIn("Always include: Keep dignity", idea["text"])
            self.assertIn("Avoid: Neon", idea["text"])
            self.assertIn("#123456, #ABCDEF", idea["reference_prompt"])

    def test_every_supported_material_surface_and_collection_works(self):
        options = think_tank_options()
        for material in options["materials"]:
            for surface in options["surfaces"]:
                for collection in ("AfroNova", "Quiet Nova", "GraffitiX"):
                    with self.subTest(material=material, surface=surface, collection=collection):
                        idea = self.generate(materials=[material], surface=surface, collection=collection)["ideas"][0]
                        self.assertEqual(idea["materials"], [options["materials"][material]])
                        self.assertEqual(idea["surface"], options["surfaces"][surface])

    def test_invalid_or_empty_inputs_are_rejected(self):
        for change in ({"materials": []}, {"materials": ["unknown"]}, {"surface": "wall"},
                       {"direction": "   "}, {"direction": "x" * 601}, {"collection": "unknown"},
                       {"variation": -1}, {"variation": 10001}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.payload(**change)
        self.assertEqual(self.payload(direction="  A portrait  ").direction, "A portrait")

    def test_save_uses_existing_library_backup_and_duplicate_protection(self):
        idea = self.generate()["ideas"][0]
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)

            @contextmanager
            def test_connection():
                # sqlite's transaction context does not close connections on Windows.
                with closing(sqlite3.connect(data / "test.db")) as db:
                    db.row_factory = sqlite3.Row
                    with db:
                        yield db

            with patch("storage.DATA_DIR", data), patch("storage.UPLOAD_DIR", data / "uploads"), \
                    patch("storage.connect", test_connection):
                initialize()
                payload = PromptPayload(title=idea["title"], category=idea["category"], text=idea["text"])
                created = create_prompt(payload)
                saved = next(item for item in list_prompts() if item["id"] == created["id"])
                self.assertEqual(saved["text"], idea["text"])
                self.assertTrue(any(item["id"] == created["id"] for item in backup_data()["prompts"]))
                with self.assertRaises(HTTPException) as error:
                    create_prompt(payload)
                self.assertEqual(error.exception.status_code, 409)

    def test_page_and_navigation_are_available(self):
        self.assertTrue(Path(think_tank().path).is_file())
        for name in ("dashboard", "chat", "prompts", "image-studio", "style-bible", "connections"):
            self.assertIn('href="/think-tank"', Path(f"templates/{name}.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
