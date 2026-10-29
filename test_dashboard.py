import unittest
from unittest.mock import patch

import storage
import test_projects as fixtures
from app import PromptPayload, create_prompt, dashboard_summary
from creative_kits import KitPayload, create_kit, list_kits
from projects import ProjectCreatePayload, create_project, project_overview, update_project


class DashboardTests(unittest.TestCase):
    setUp = fixtures.ProjectTests.setUp
    payload = fixtures.ProjectTests.payload
    photo = fixtures.ProjectTests.photo

    def project(self, name="My studio plan", status="planned"):
        source = create_prompt(PromptPayload(title=name, text=f"My own idea for {name}", category="My own direction"))
        project = create_project(ProjectCreatePayload(prompt_id=source["id"], seed={
            "materials": ["My graphite"], "surface": "My paper",
            "checklist": [{"id": "first", "text": "Study the shapes.", "done": True},
                          {"id": "next", "text": "Try the next layer.", "done": False}],
        }))["project"]
        return update_project(project["id"], self.payload(project, status=status))

    def test_empty_studio_reports_real_zeros_and_no_suggested_owner_work(self):
        data = dashboard_summary()
        self.assertEqual(data["counts"]["projects"], 0)
        self.assertEqual(data["counts"]["creative_kits"], 0)
        self.assertEqual(data["projects"]["recent"], [])
        self.assertEqual(data["projects"]["counts"]["ongoing"], 0)
        self.assertEqual(data["recent_prompts"], [])
        self.assertEqual(data["recent_artworks"], [])
        self.assertIsNone(data["prompt_of_day"])

    def test_resume_projects_exclude_completed_and_use_actual_save_time_across_offsets(self):
        planned = self.project("A planned piece")
        active = self.project("A piece in progress", "in_progress")
        paused = self.project("A paused piece", "paused")
        earlier = self.project("An older plan")
        complete = self.project("A completed piece", "completed")
        for project, saved_at in ((planned, "2026-10-29T10:00:00-05:00"), (active, "2026-10-29T14:30:00+00:00"),
                                  (paused, "2026-10-29T14:00:00+00:00"), (earlier, "2026-10-29T13:00:00+00:00"),
                                  (complete, "2026-10-29T16:00:00+00:00")):
            storage.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (saved_at, project["id"]))
        overview = dashboard_summary()["projects"]
        self.assertEqual(overview["counts"], {"planned": 2, "in_progress": 1, "paused": 1, "completed": 1, "total": 5, "ongoing": 4})
        self.assertEqual([project["id"] for project in overview["recent"]], [planned["id"], active["id"], paused["id"]])
        self.assertEqual(overview["recent"][0]["progress"], {"done": 1, "total": 2, "percent": 50})
        self.assertNotIn("checklist", overview["recent"][0])

    def test_project_cover_uses_available_progress_photos_and_skips_references_or_unsafe_paths(self):
        project = self.project()
        progress = self.photo(project["id"], "progress")
        reference = self.photo(project["id"], "reference")
        missing = self.photo(project["id"], "finished")
        filename = storage.rows("SELECT filename FROM artworks WHERE id = ?", (missing["id"],))[0]["filename"]
        (storage.UPLOAD_DIR / filename).unlink()
        cover = dashboard_summary()["projects"]["recent"][0]["cover"]
        self.assertEqual(cover["url"], progress["url"])
        self.assertEqual(cover["stage"], "progress")
        storage.execute("UPDATE artworks SET filename = ? WHERE id = ?", ("../outside.png", progress["id"]))
        (self.directory / "outside.png").write_bytes(b"Not a studio image")
        self.assertIsNone(dashboard_summary()["projects"]["recent"][0]["cover"])

    def test_counts_and_library_groups_exclude_trash_and_dashboard_is_read_only(self):
        active = create_prompt(PromptPayload(title="My saved idea", category="My own direction", text='Keep “these quotes” & my own colors.', favorite=True))
        trashed = create_prompt(PromptPayload(title="In Trash", category="My own direction", text="Do not feature this", favorite=True))
        storage.execute("UPDATE prompts SET trashed = 1, reviewed = 0 WHERE id = ?", (trashed["id"],))
        photo = self.photo()
        storage.execute("UPDATE artworks SET favorite = 1 WHERE id = ?", (photo["id"],))
        create_kit(KitPayload(name="My kit", preferences={"palette": "My colors"}))
        before = storage.backup_data()
        data = dashboard_summary()
        self.assertEqual(data["counts"]["prompts"], 1)
        self.assertEqual(data["counts"]["favorites"], 2)
        self.assertEqual(data["counts"]["to_review"], 0)
        self.assertEqual(data["counts"]["creative_kits"], 1)
        self.assertEqual(data["recent_prompts"][0]["id"], active["id"])
        self.assertEqual(data["recent_artworks"][0]["id"], photo["id"])
        self.assertEqual(data["prompt_of_day"]["id"], active["id"])
        self.assertEqual(storage.backup_data(), before)

    def test_a_project_with_its_source_in_trash_still_appears_on_home(self):
        project = self.project()
        storage.execute("UPDATE prompts SET trashed = 1 WHERE id = ?", (project["source_prompt_id"],))
        data = dashboard_summary()
        self.assertEqual(data["counts"]["prompts"], 0)
        self.assertEqual(data["projects"]["recent"][0]["id"], project["id"])

    def test_dashboard_counts_use_one_snapshot_when_another_device_saves_a_kit(self):
        self.project()
        with storage.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")

        def read_during_save(db):
            result = project_overview(db)
            create_kit(KitPayload(name="A concurrent save", preferences={"mood": "My mood"}))
            return result

        with patch("app.project_overview", side_effect=read_during_save):
            data = dashboard_summary()
        self.assertEqual(data["counts"]["creative_kits"], 0)
        self.assertEqual(len(list_kits()), 1)


if __name__ == "__main__":
    unittest.main()
