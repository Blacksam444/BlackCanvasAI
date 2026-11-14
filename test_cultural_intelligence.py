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

if __name__ == "__main__":
    unittest.main()
