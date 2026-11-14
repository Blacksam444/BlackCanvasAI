import unittest
from cultural_intelligence import CulturalContext, guidance, CULTURAL_THEMES

class CulturalIntelligenceTests(unittest.TestCase):
    def test_opt_in_default(self):
        self.assertEqual(guidance(CulturalContext()), "")

    def test_selected_theme(self):
        self.assertIn(CULTURAL_THEMES["legacy"], guidance(CulturalContext(True, "legacy")))

    def test_unknown_theme(self):
        with self.assertRaises(ValueError):
            guidance(CulturalContext(True, "unsupported"))

class PromptIntegrationTests(unittest.TestCase):
    def test_disabled_keeps_original(self):
        from app import create_image_prompt
        self.assertEqual(create_image_prompt("a crowned portrait in the AfroNova style"),
                         create_image_prompt("a crowned portrait in the AfroNova style", False))

    def test_enabled_preserves_midjourney_suffix(self):
        from app import create_image_prompt
        _, prompt = create_image_prompt("a crowned portrait in the AfroNova style", True, "legacy")
        self.assertIn("OPTIONAL CULTURAL CONTEXT", prompt)
        self.assertIn(CULTURAL_THEMES["legacy"], prompt)
        self.assertRegex(prompt, r"--v\s+[0-9.]+$")

    def test_unknown_theme_rejected(self):
        from app import create_image_prompt
        with self.assertRaises(ValueError):
            create_image_prompt("a portrait", True, "invalid")

if __name__ == "__main__":
    unittest.main()
