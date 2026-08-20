import unittest
from unittest.mock import patch

from app import ChatMessage, chat_reply


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


if __name__ == "__main__":
    unittest.main()
