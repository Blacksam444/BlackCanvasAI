import unittest

from app import create_image_prompt


class PromptRuleTests(unittest.TestCase):
    def test_graffitix_is_a_clean_copy_ready_prompt(self):
        collection, prompt = create_image_prompt(
            "Create an image prompt for a street dancer in the GraffitiX style"
        )
        self.assertEqual(collection, "GraffitiX")
        self.assertTrue(prompt.startswith("Full-body"))
        self.assertNotIn("/imagine prompt", prompt.lower())
        self.assertNotIn("--", prompt)
        self.assertNotIn("no frame", prompt.lower())
        self.assertIn("one dominant hero symbol", prompt.lower())
        self.assertIn("one or two small supporting symbols", prompt.lower())
        self.assertIn("raw black canvas", prompt.lower())

    def test_requested_aspect_ratio_does_not_add_model_code(self):
        _, prompt = create_image_prompt(
            "Create an image prompt for a cosmic queen in the AfroNova style. Aspect ratio: 16:9."
        )
        self.assertNotIn("--ar", prompt)
        self.assertNotIn("--v", prompt)

    def test_unknown_aspect_ratio_does_not_add_model_code(self):
        _, prompt = create_image_prompt(
            "Create an image prompt for a cosmic queen in the AfroNova style. Aspect ratio: 99:1."
        )
        self.assertNotIn("--ar", prompt)
        self.assertNotIn("--v", prompt)

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
