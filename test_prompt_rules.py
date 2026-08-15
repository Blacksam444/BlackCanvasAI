import unittest

from app import create_image_prompt


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


if __name__ == "__main__":
    unittest.main()
