import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from marketing import NewPlan, PlanEdit, create_plan, list_plans, update_plan
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
                         ["instagram", "pinterest", "facebook", "tiktok"])
        self.assertEqual([post["date"] for post in plan["posts"]],
                         ["2026-11-16", "2026-11-17", "2026-11-19", "2026-11-21"])
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
        self.assertEqual(list_plans()[0]["posts"][2]["caption"], captions["facebook"])
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
