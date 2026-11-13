import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from buffer_client import BufferClient, BufferError, BufferRejected
from marketing import BufferSchedule, NewPlan, PlanEdit, create_plan, list_plans, schedule_in_buffer, update_plan
from storage import backup_data, execute, initialize


class MarketingQueueTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        data_dir = Path(temp)
        self.enterContext(patch("storage.DATA_DIR", data_dir))
        self.enterContext(patch("storage.UPLOAD_DIR", data_dir / "uploads"))
        self.enterContext(patch("storage.DB_PATH", data_dir / "test.db"))
        initialize()
        self.artwork_id = execute(
            "INSERT INTO artworks(title, collection, notes, filename) VALUES (?, ?, ?, ?)",
            ("The Burden", "AfroNova", "Private notes", "sample.png"),
        )

    def test_retry_preserves_existing_drafts_and_reuses_artwork(self):
        payload = NewPlan(
            artwork_id=self.artwork_id,
            start_date=date(2026, 11, 16),
            story="I painted this thinking about what we carry.",
            listing_url="https://www.etsy.com/listing/123/the-burden",
        )
        plan = create_plan(payload)
        self.assertEqual([post["platform"] for post in plan["posts"]],
                         ["instagram", "pinterest", "youtube", "facebook", "tiktok"])
        self.assertEqual([post["date"] for post in plan["posts"]],
                         ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-21"])
        self.assertEqual(plan["artwork_url"], "/uploads/sample.png")
        self.assertIn(payload.story, plan["posts"][2]["caption"])
        self.assertNotIn("Private notes", str(plan))
        self.assertEqual(create_plan(payload.model_copy(update={"story": "A new story."})), plan)
        self.assertEqual(list_plans(), [plan])
        self.assertEqual(backup_data()["marketing_plans"][0]["id"], plan["id"])

    def test_approval_saves_edits_and_rejects_stale_or_incomplete_updates(self):
        plan = create_plan(NewPlan(artwork_id=self.artwork_id, start_date=date(2026, 11, 16)))
        captions = {post["platform"]: post["caption"] for post in plan["posts"]}
        captions["pinterest_title"] = "The Burden | AfroNova"
        captions["facebook"] = "A painting about what we carry."
        edit = PlanEdit(start_date=date(2026, 11, 17), captions=captions,
                        revision=plan["revision"], approved=True)
        updated = update_plan(plan["id"], edit)
        self.assertTrue(updated["approved"])
        self.assertEqual(updated["posts"][0]["date"], "2026-11-17")
        self.assertEqual(next(post["caption"] for post in list_plans()[0]["posts"]
                              if post["platform"] == "facebook"), captions["facebook"])
        with self.assertRaises(HTTPException) as stale:
            update_plan(plan["id"], edit)
        self.assertEqual(stale.exception.status_code, 409)
        with self.assertRaises(HTTPException) as incomplete:
            update_plan(plan["id"], edit.model_copy(update={
                "revision": updated["revision"],
                "captions": edit.captions.model_copy(update={"facebook": "  "}),
            }))
        self.assertEqual(incomplete.exception.status_code, 400)
        self.assertEqual(list_plans(), [updated])

    def test_buffer_keeps_successes_and_avoids_retrying_unconfirmed_posts(self):
        start = (datetime.now(timezone.utc) + timedelta(days=7)).date()
        plan = create_plan(NewPlan(
            artwork_id=self.artwork_id, start_date=start, listing_url="https://www.etsy.com/listing/123",
        ))
        captions = {post["platform"]: post["caption"] for post in plan["posts"]}
        captions["pinterest_title"] = "The Burden"
        plan = update_plan(plan["id"], PlanEdit(start_date=start, revision=1, captions=captions, approved=True,
                                               listing_url=plan["listing_url"]))
        payload = BufferSchedule(revision=plan["revision"], organization_id="workspace", posts=[
            {
                "platform": post["platform"], "channel_id": post["platform"],
                "due_at": f"{post['date']}T19:00:00-06:00", "media_url": "https://cdn.example.com/art",
                "board_id": "board" if post["platform"] == "pinterest" else "",
                "youtube_privacy": "unlisted" if post["platform"] == "youtube" else "public",
            }
            for post in plan["posts"]
        ])
        channels = [
            {"id": post.platform, "platform": post.platform, "name": post.platform,
             "boards": [{"serviceId": "board", "name": "Art"}]}
            for post in payload.posts
        ]
        with patch("marketing.connected_channels", return_value=channels), patch("marketing.BufferClient") as factory:
            buffer = factory.return_value
            buffer.schedule.side_effect = [
                {"id": "reel", "status": "buffer"}, {"id": "pin", "status": "buffer"},
                {"id": "short", "status": "buffer"},
                BufferRejected("Check photo format."), BufferError("Timeout"),
            ]
            result = schedule_in_buffer(plan["id"], payload)
            self.assertEqual(set(result["errors"]), {"facebook", "tiktok"})
            self.assertEqual(result["plan"]["buffer_posts"]["tiktok"]["state"], "unconfirmed")
            self.assertNotIn("facebook", result["plan"]["buffer_posts"])
            calls = [call.args[0] for call in buffer.schedule.call_args_list]
            self.assertEqual(calls[0]["metadata"]["instagram"]["type"], "reel")
            self.assertEqual(calls[1]["metadata"]["pinterest"]["url"], plan["listing_url"])
            self.assertEqual(calls[2]["metadata"]["youtube"]["categoryId"], "26")
            self.assertEqual(calls[2]["metadata"]["youtube"]["privacy"], "unlisted")
            self.assertFalse(calls[2]["metadata"]["youtube"]["notifySubscribers"])
            self.assertEqual(calls[2]["assets"], [{"video": {"url": "https://cdn.example.com/art"}}])
            self.assertIn(plan["listing_url"], calls[3]["text"])
            self.assertTrue(calls[0]["dueAt"].endswith("01:00:00Z"))

            buffer.schedule.reset_mock()
            buffer.schedule.side_effect = None
            buffer.schedule.return_value = {"id": "photo", "status": "buffer"}
            result = schedule_in_buffer(plan["id"], payload)
            buffer.schedule.assert_called_once()
            self.assertEqual(buffer.schedule.call_args.args[0]["channelId"], "facebook")
            self.assertEqual(len(result["plan"]["buffer_posts"]), 5)
            self.assertEqual(len(backup_data()["marketing_buffer_posts"]), 5)

    def test_existing_weeks_get_a_short_without_changing_saved_captions(self):
        plan = create_plan(NewPlan(artwork_id=self.artwork_id, start_date=date(2026, 11, 16)))
        existing = {
            "instagram": "Instagram caption", "pinterest": "Pin caption", "pinterest_title": "Pin title",
            "facebook": "Facebook caption", "tiktok": "TikTok caption",
        }
        execute("UPDATE marketing_plans SET posts = ? WHERE id = ?", (json.dumps(existing), plan["id"]))
        updated = update_plan(plan["id"], PlanEdit(start_date=date(2026, 11, 16), revision=1,
                                                  captions=existing, approved=True))
        posts = {post["platform"]: post for post in updated["posts"]}
        self.assertEqual(posts["facebook"]["caption"], existing["facebook"])
        self.assertIn("The Burden", posts["youtube"]["title"])
        self.assertTrue(posts["youtube"]["caption"])

    def test_buffer_discovers_instagram_pinterest_and_youtube_together(self):
        channels = [{
            "id": service, "name": service, "displayName": service, "service": service, "type": "account",
            "isDisconnected": False, "isLocked": False, "isQueuePaused": False,
            "metadata": {"boards": [{"serviceId": "art", "name": "Art"}]} if service == "pinterest" else None,
        } for service in ("instagram", "pinterest", "youtube")]
        with patch.object(BufferClient, "request", return_value={"channels": channels}):
            connected = BufferClient().channels("workspace")
        self.assertEqual([channel["platform"] for channel in connected], ["instagram", "pinterest", "youtube"])
        self.assertEqual(connected[1]["boards"], [{"serviceId": "art", "name": "Art"}])

    def test_buffer_requires_an_approved_week(self):
        plan = create_plan(NewPlan(artwork_id=self.artwork_id, start_date=date(2026, 11, 16)))
        payload = BufferSchedule(revision=1, organization_id="workspace", posts=[{
            "platform": "facebook", "channel_id": "fb", "due_at": "2026-11-19T19:00:00-06:00",
            "media_url": "https://cdn.example.com/art.png",
        }])
        with patch("marketing.connected_channels", return_value=[]), patch("marketing.BufferClient") as factory:
            with self.assertRaises(HTTPException) as unapproved:
                schedule_in_buffer(plan["id"], payload)
            self.assertEqual(unapproved.exception.status_code, 409)
            factory.return_value.schedule.assert_not_called()
