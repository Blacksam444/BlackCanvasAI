import tempfile
import sqlite3
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import (
    PromptPayload, ThinkTankPayload, ThinkTankRefinePayload, create_prompt, create_image_prompt, generate_think_tank_ideas,
    list_prompts, refine_think_tank_idea, think_tank, think_tank_options,
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

    def test_default_direction_does_not_inherit_owner_styles_or_subjects(self):
        payload = ThinkTankPayload(materials=["charcoal"], surface="paper", direction="A misty pine forest")
        owner_style = {"colors": ["royal purple"], "mood": ["regal"], "ingredients": ["Black cosmic royalty"]}
        with patch("app.list_styles", return_value={"AfroNova": owner_style, "My own direction": owner_style}):
            ideas = generate_think_tank_ideas(payload)["ideas"]
        for idea in ideas:
            self.assertEqual(idea["category"], "My own direction")
            self.assertEqual(idea["palette"], "")
            self.assertEqual(idea["mood"], "")
            self.assertEqual(idea["style_ingredients"], "")
            self.assertIn("A misty pine forest", idea["reference_prompt"])
            self.assertIn("Charcoal on heavy mixed-media paper", idea["reference_prompt"])
            for unwanted in ("royal purple", "Black cosmic royalty", "portrait", "acrylic", "full-body"):
                self.assertNotIn(unwanted, idea["reference_prompt"])

    def test_user_preferences_and_custom_only_materials_survive_refine_and_remix(self):
        payload = ThinkTankPayload(
            direction="Abstract tidal shapes", other_materials="Watercolor and salt", surface="paper",
            style_direction="Loose transparent washes", palette="teal and rust", mood="playful",
            avoid="faces, crowns, and neon",
        )
        with patch("app.list_styles", return_value={}):
            idea = generate_think_tank_ideas(payload)["ideas"][0]
            refined = refine_think_tank_idea(ThinkTankRefinePayload(**idea["brief"], composition_index=idea["composition_index"]))["idea"]
            remixes = generate_think_tank_ideas(ThinkTankPayload(**refined["brief"], variation=1))["ideas"]
        for item in [idea, refined, *remixes]:
            self.assertEqual(item["materials"], ["Watercolor and salt"])
            self.assertEqual(item["palette"], "teal and rust")
            self.assertEqual(item["mood"], "playful")
            self.assertEqual(item["avoid"], "faces, crowns, and neon")
            self.assertIn("Loose transparent washes", item["reference_prompt"])
            self.assertIn("Avoid: faces, crowns, and neon", item["text"])
            self.assertEqual(item["brief"]["other_materials"], "Watercolor and salt")

    def test_chat_does_not_map_user_subjects_to_owner_collections(self):
        for subject in ("a calm alpine lake", "a neon city map", "abstract urban shapes"):
            collection, prompt = create_image_prompt(f"Create an image prompt for {subject}")
            self.assertEqual(collection, "My own direction")
            self.assertIn(subject, prompt)
            self.assertNotIn("GraffitiX", prompt)
            self.assertNotIn("AfroNova", prompt)
        collection, prompt = create_image_prompt("A book titled AfroNova. Collection: My own direction.")
        self.assertEqual(collection, "My own direction")
        self.assertNotIn("expressive eyes", prompt)
        for subject in ("a book titled AfroNova", "a landscape, not in the GraffitiX style"):
            collection, _ = create_image_prompt(f"Create an image prompt for {subject}")
            self.assertEqual(collection, "My own direction")

    def test_material_or_preference_validation_rejects_empty_or_oversized_values(self):
        for changes in ({"materials": [], "other_materials": "  "}, {"other_materials": "x" * 241},
                        {"avoid": "x" * 1201}, {"style_direction": "x" * 601}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.payload(**changes)

    def test_explicit_user_medium_overrides_the_selected_preset_medium(self):
        collection, prompt = create_image_prompt(
            "Create an image prompt for a portrait in the Quiet Nova style. Visual approach: watercolor on paper."
        )
        self.assertEqual(collection, "Quiet Nova")
        self.assertIn("watercolor on paper", prompt)
        self.assertNotIn("fine-art digital painting", prompt)

    def test_refinement_preserves_selected_composition_materials_surface_and_collection(self):
        payload = ThinkTankRefinePayload(**self.payload().model_dump(), composition_index=4)
        with patch("app.list_styles", return_value={}):
            result = refine_think_tank_idea(payload)
        self.assertEqual(result["engine"], "local")
        idea = result["idea"]
        self.assertEqual(idea["composition_index"], 4)
        self.assertEqual(idea["composition"], think_tank_options()["compositions"][4])
        self.assertEqual(idea["category"], payload.collection)
        self.assertEqual(idea["brief"]["materials"], payload.materials)
        self.assertEqual(idea["brief"]["surface"], payload.surface)

    def test_refined_palette_mood_notes_and_direction_reach_the_plan_and_remixes(self):
        updates = {"palette": "copper and indigo", "mood": "warm and hopeful", "studio_notes": "Leave the lower edge raw.",
                   "direction": "A hopeful ancestral portrait"}
        payload = ThinkTankRefinePayload(**self.payload(**updates).model_dump(), composition_index=2)
        with patch("app.list_styles", return_value={"Quiet Nova": {"dos": ["Keep dignity"], "donts": ["Neon"]}}):
            idea = refine_think_tank_idea(payload)["idea"]
            remixed = generate_think_tank_ideas(ThinkTankPayload(**idea["brief"], variation=1))["ideas"]
        for item in [idea, *remixed]:
            self.assertEqual(item["palette"], updates["palette"])
            self.assertEqual(item["mood"], updates["mood"])
            self.assertIn(updates["direction"], item["text"])
            self.assertIn(updates["studio_notes"], item["text"])
            self.assertIn(updates["palette"], item["reference_prompt"])
            self.assertIn(updates["mood"], item["reference_prompt"])
            self.assertIn("Always include: Keep dignity", item["text"])
            self.assertIn("Avoid: Neon", item["text"])

    def test_refinement_rejects_unsupported_compositions_and_oversized_notes(self):
        for change in ({"composition_index": -1}, {"composition_index": 6}, {"studio_notes": "x" * 1201},
                       {"palette": "x" * 2601}, {"mood": "x" * 2601}):
            values = {**self.payload().model_dump(), "composition_index": 0, **change}
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ThinkTankRefinePayload(**values)

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
                self.assertEqual(list_prompts(), [])
                payload = PromptPayload(title=idea["title"], category=idea["category"], text=idea["text"])
                created = create_prompt(payload)
                saved = next(item for item in list_prompts() if item["id"] == created["id"])
                self.assertEqual(saved["text"], idea["text"])
                self.assertTrue(any(item["id"] == created["id"] for item in backup_data()["prompts"]))
                with self.assertRaises(HTTPException) as error:
                    create_prompt(payload)
                self.assertEqual(error.exception.status_code, 409)
                with patch("app.list_styles", return_value={}):
                    refined = refine_think_tank_idea(ThinkTankRefinePayload(
                        **self.payload(direction="A revised ancestral portrait", studio_notes="Keep the edges rough.").model_dump(),
                        composition_index=idea["composition_index"],
                    ))["idea"]
                revision = create_prompt(PromptPayload(title=refined["title"], category=refined["category"], text=refined["text"]))
                self.assertNotEqual(revision["id"], created["id"])
                library = {item["id"]: item for item in list_prompts()}
                self.assertEqual(library[created["id"]]["text"], idea["text"])
                self.assertIn("Keep the edges rough.", library[revision["id"]]["text"])

    def test_page_and_navigation_are_available(self):
        self.assertTrue(Path(think_tank().path).is_file())
        for name in ("dashboard", "chat", "prompts", "image-studio", "style-bible", "connections"):
            self.assertIn('href="/think-tank"', Path(f"templates/{name}.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
