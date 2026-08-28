import unittest
from unittest.mock import patch

from app import (
    ChatMessage,
    PromptRefinePayload,
    agent_actions_for_request,
    artwork_agent_brief,
    artwork_content_kit,
    artwork_visual_request_body,
    chatgpt_candidate_is_prompt,
    chat_reply,
    is_likely_image_prompt,
    openai_response_text,
    refine_prompt,
)


STUDIO_SUMMARY = {
    "counts": {"artworks": 2, "to_review": 5},
    "studio": {
        "ready_to_list": 1,
        "catalog_value": 1200,
        "active_orders": 0,
    },
}


class AgentRouteTests(unittest.TestCase):
    def setUp(self):
        live_agent = patch("app.safe_live_agent_reply", return_value=None)
        live_agent.start()
        self.addCleanup(live_agent.stop)

    def test_live_agent_actions_point_to_the_requested_workspace(self):
        self.assertEqual(agent_actions_for_request("Help me price this artwork")[0]["href"], "/image-studio?focus=unpriced")
        keep_actions = agent_actions_for_request("Organize my Google Keep prompts")
        self.assertEqual(keep_actions[0]["href"], "/prompts?review=keep")

    def test_image_prompt_detection_keeps_content_drafts_out_of_visual_review(self):
        self.assertTrue(is_likely_image_prompt("Cosmic king portrait", "Unsorted", "Create an image prompt for a regal portrait."))
        self.assertTrue(is_likely_image_prompt("AfroNova idea", "AfroNova", "A short visual thought"))
        self.assertFalse(is_likely_image_prompt("Friday caption", "Content", "Share a process clip and invite a comment."))

    def test_visual_analysis_sends_the_actual_image_and_requires_structured_details(self):
        artwork = {
            "title": "Old Generic Title",
            "collection": "GraffitiX",
            "tags": "street art",
            "notes": "",
        }
        body = artwork_visual_request_body(
            artwork, "data:image/jpeg;base64,abc", {"mood": ["raw"]}, ["Concrete Crown"]
        )

        content = body["input"][0]["content"]
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(content[1]["image_url"], "data:image/jpeg;base64,abc")
        schema = body["text"]["format"]["schema"]
        self.assertIn("title", schema["required"])
        self.assertIn("generated_prompt", schema["required"])
        self.assertIn("visual_summary", schema["required"])
        self.assertIn("actual pixels", body["instructions"])
        self.assertIn("never invent clothing", body["instructions"])
        self.assertIn("Concrete Crown", content[0]["text"])
        self.assertIn("must not repeat", body["instructions"])

    def test_raw_responses_api_text_is_extracted(self):
        result = {"output": [{"content": [{"type": "output_text", "text": "{\"title\":\"Seen Image\"}"}]}]}
        self.assertEqual(openai_response_text(result), '{"title":"Seen Image"}')

    def test_refiner_removes_legacy_model_code_from_old_prompts(self):
        result = refine_prompt(PromptRefinePayload(
            prompt=("/imagine prompt: Full-body graffiti king. Museum-quality contemporary urban artwork, "
                    "no digital smoothness, no glossy CGI finish, no polished 3D render, no clean vector edges, "
                    "no random decorative symbols, no cluttered focal hierarchy, no text, no watermark, "
                    "no signature, no logo, no frame --ar 4:5 --raw --v 8.2"),
            category="GraffitiX",
            mode="cinematic",
        ))

        self.assertTrue(result["generated_prompt"].startswith("Full-body graffiti king"))
        self.assertNotIn("/imagine prompt", result["generated_prompt"].lower())
        self.assertNotIn("--ar", result["generated_prompt"])
        self.assertNotIn("--raw", result["generated_prompt"])
        self.assertNotIn("--v", result["generated_prompt"])
        self.assertNotIn("no frame", result["generated_prompt"].lower())

    def test_clean_mode_removes_old_generator_codes_without_adding_variation(self):
        result = refine_prompt(PromptRefinePayload(
            prompt="/imagine prompt: Regal Black portrait --ar 4:5 --style raw --stylize 200 --v 8.2",
            category="AfroNova",
            mode="clean",
        ))

        self.assertEqual(result["generated_prompt"], "Regal Black portrait")
        self.assertEqual(result["prompt_title"], "Clean copy-ready prompt")

    @patch("app.dashboard_summary", return_value=STUDIO_SUMMARY)
    def test_weekly_content_plan_has_save_draft_action(self, _summary):
        result = chat_reply(ChatMessage(message="Make me a weekly content plan"))

        self.assertIn("five-post content plan", result["reply"])
        self.assertIn("Friday", result["reply"])
        action_labels = [action["label"] for action in result["actions"]]
        self.assertIn("Save this plan to Prompt Library", action_labels)
        save_action = next(action for action in result["actions"] if action["label"] == "Save this plan to Prompt Library")
        self.assertIn("/prompts?new=1", save_action["href"])
        self.assertIn("category=Content", save_action["href"])

    @patch("app.dashboard_summary", return_value=STUDIO_SUMMARY)
    def test_collection_launch_plan_is_specific(self, _summary):
        result = chat_reply(ChatMessage(message="Create a collection launch plan"))

        self.assertIn("collection-launch plan", result["reply"])
        self.assertIn("7. Follow up", result["reply"])
        action_labels = [action["label"] for action in result["actions"]]
        self.assertIn("Open listing-ready artwork", action_labels)
        self.assertIn("Build a content week", action_labels)

    @patch("app.dashboard_summary", return_value=STUDIO_SUMMARY)
    def test_import_guidance_links_to_image_prompt_review(self, _summary):
        result = chat_reply(ChatMessage(message="Organize imported prompts"))

        action_labels = [action["label"] for action in result["actions"]]
        self.assertIn("Review likely image prompts", action_labels)
        image_action = next(action for action in result["actions"] if action["label"] == "Review likely image prompts")
        self.assertEqual(image_action["href"], "/prompts?review=image")

    @patch("app.dashboard_summary", return_value=STUDIO_SUMMARY)
    def test_caption_request_returns_a_draft(self, _summary):
        result = chat_reply(ChatMessage(message="Write a TikTok caption for AfroNova"))

        self.assertIn("TikTok caption draft", result["reply"])
        self.assertIn("AfroNova is a reminder", result["reply"])
        self.assertIn("#BlackCanvasArt", result["reply"])
        self.assertIn("Build a content week", [action["label"] for action in result["actions"]])
        save_action = next(action for action in result["actions"] if action["label"] == "Save caption to Prompt Library")
        self.assertIn("/prompts?new=1", save_action["href"])
        self.assertIn("category=Content", save_action["href"])

    def test_artwork_brief_prioritizes_missing_details_before_price(self):
        artwork = {
            "id": 14,
            "title": "Untitled Nova",
            "collection": "AfroNova",
            "tags": "cosmic, gold",
            "notes": "",
            "dimensions": "",
            "medium": "",
            "price": 0,
            "sale_status": "In progress",
            "fulfillment_status": "Not started",
        }
        with patch("app.connect", return_value=ArtworkConnection(artwork)):
            result = artwork_agent_brief(14)

        self.assertIn("Complete the missing", result["reply"])
        action_labels = [action["label"] for action in result["actions"]]
        self.assertIn("Edit this artwork", action_labels)
        self.assertNotIn("Open Pricing Calculator", action_labels)
        edit_action = next(action for action in result["actions"] if action["label"] == "Edit this artwork")
        self.assertEqual(edit_action["href"], "/image-studio?artwork=14&tool=edit")

    def test_complete_unpriced_artwork_opens_its_calculator(self):
        artwork = {
            "id": 15,
            "title": "Ready for Price",
            "collection": "Quiet Nova",
            "tags": "quiet, window light",
            "notes": "A quiet study in reflection.",
            "dimensions": "24 × 36 inches",
            "medium": "Acrylic on canvas",
            "price": 0,
            "sale_status": "In progress",
            "fulfillment_status": "Not started",
        }
        with patch("app.connect", return_value=ArtworkConnection(artwork)):
            result = artwork_agent_brief(15)

        pricing_action = next(action for action in result["actions"] if action["label"] == "Open Pricing Calculator")
        self.assertEqual(pricing_action["href"], "/image-studio?artwork=15&tool=pricing")

    def test_content_kit_includes_a_complete_pinterest_workflow(self):
        artwork = {
            "id": 16,
            "title": "Celestial Crown",
            "collection": "AfroNova",
            "tags": "afrofuturism, gold, portrait",
            "notes": "A regal portrait shaped by ancestral light.",
            "dimensions": "24 × 30 inches",
            "medium": "Digital mixed media",
            "price": 450,
            "sale_status": "Ready to list",
            "listing_url": "https://www.etsy.com/listing/123456789/celestial-crown",
        }
        links = {
            "shop_url": "https://www.etsy.com/shop/444GraffitiX",
            "pinterest_url": "https://www.pinterest.com/celestialhue316/",
        }
        with patch("app.rows", return_value=[artwork]), patch("app.get_gallery_settings", return_value=links):
            kit = artwork_content_kit(16)

        self.assertLessEqual(len(kit["pinterest_title"]), 100)
        self.assertLessEqual(len(kit["pinterest_description"]), 800)
        self.assertLessEqual(len(kit["pinterest_topics"]), 10)
        self.assertEqual(kit["pinterest_destination"], artwork["listing_url"])
        self.assertEqual(kit["pinterest_profile"], links["pinterest_url"])
        self.assertEqual(kit["pinterest_board"], "AfroNova")

    def test_chatgpt_auto_import_keeps_regular_conversation_out(self):
        self.assertTrue(chatgpt_candidate_is_prompt({
            "role": "assistant",
            "text": "Here is a copy-ready image prompt: a Black cosmic queen in gold armor, painted with luminous celestial textures.",
        }))
        self.assertTrue(chatgpt_candidate_is_prompt({
            "role": "user",
            "text": "Create an image prompt for an AfroNova portrait with gold, ancestral symbols, and a deep blue background.",
        }))
        self.assertFalse(chatgpt_candidate_is_prompt({"role": "user", "text": "Okay, that worked great."}))

    def test_spellcheck_knows_common_art_catalog_typos(self):
        from app import spellcheck_text, SpellCheckPayload

        result = spellcheck_text(SpellCheckPayload(text="Add a discripton for this artowrk."))
        self.assertEqual(result["corrected_text"], "Add a description for this artwork.")


class ArtworkQuery:
    def __init__(self, artwork):
        self.artwork = artwork

    def fetchone(self):
        return self.artwork


class ArtworkConnection:
    def __init__(self, artwork):
        self.artwork = artwork

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _query, _values):
        return ArtworkQuery(self.artwork)


if __name__ == "__main__":
    unittest.main()
