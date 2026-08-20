import unittest

from app import create_image_prompt


class PromptRuleTests(unittest.TestCase):
    def test_graffitix_has_v82_raw_and_clear_hierarchy(self):
        collection, prompt = create_image_prompt(
            "Create an image prompt for a street dancer in the GraffitiX style"
        )
        self.assertEqual(collection, "GraffitiX")
        self.assertTrue(prompt.endswith("--ar 4:5 --raw --v 8.2"))
        self.assertNotIn("--style raw", prompt)
        self.assertIn("one dominant hero symbol", prompt.lower())
        self.assertIn("one or two small supporting symbols", prompt.lower())
        self.assertIn("no digital smoothness", prompt.lower())

    def test_supported_aspect_ratio_is_used(self):
        _, prompt = create_image_prompt(
            "Create an image prompt for a cosmic queen in the AfroNova style. Aspect ratio: 16:9."
        )
        self.assertTrue(prompt.endswith("--ar 16:9 --raw --v 8.2"))

    def test_unknown_aspect_ratio_defaults_to_portrait(self):
        _, prompt = create_image_prompt(
            "Create an image prompt for a cosmic queen in the AfroNova style. Aspect ratio: 99:1."
        )
        self.assertTrue(prompt.endswith("--ar 4:5 --raw --v 8.2"))

    def test_graffitix_builder_direction_is_honored(self):
        _, prompt = create_image_prompt(
            "Create an image prompt for a street oracle in the GraffitiX style. "
            "Pose: low crouched stance with a compressed S-curve; "
            "Camera: pavement-level tracking shot; Hero symbol: distorted crown."
        )
        self.assertIn("Engineer low crouched stance with a compressed S-curve", prompt)
        self.assertIn("Use pavement-level tracking shot", prompt)
        self.assertIn("one dominant hero symbol—distorted crown", prompt)


if __name__ == "__main__":
    unittest.main()
