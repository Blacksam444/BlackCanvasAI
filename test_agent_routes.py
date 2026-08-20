import unittest
from unittest.mock import patch

from app import ChatMessage, artwork_agent_brief, chat_reply


STUDIO_SUMMARY = {
    "counts": {"artworks": 2, "to_review": 5},
    "studio": {
        "ready_to_list": 1,
        "catalog_value": 1200,
        "active_orders": 0,
    },
}


class AgentRouteTests(unittest.TestCase):
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
