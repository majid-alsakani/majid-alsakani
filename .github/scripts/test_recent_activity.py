"""Checks for the README activity renderer without using the network."""

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "recent_activity", Path(__file__).with_name("recent_activity.py")
)
activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activity)


class RecentActivityTests(unittest.TestCase):
    def test_render_events_and_limit(self):
        events = [
            {"type": "PushEvent", "repo": {"name": "owner/repo"}},
            {
                "type": "PullRequestEvent",
                "repo": {"name": "owner/repo"},
                "payload": {"action": "opened", "pull_request": {"number": 12}},
            },
        ]
        self.assertEqual(
            activity.render(events, limit=1),
            "- Pushed commits to [owner/repo](https://github.com/owner/repo)",
        )
        self.assertIn("[PR #12](https://github.com/owner/repo/pull/12)", activity.render(events))

    def test_replaces_only_marked_section(self):
        original = "before\n<!--START_SECTION:activity-->\nold\n<!--END_SECTION:activity-->\nafter\n"
        updated = activity.update_readme(original, "new")
        self.assertEqual(
            updated, "before\n<!--START_SECTION:activity-->\nnew\n<!--END_SECTION:activity-->\nafter\n"
        )
        with self.assertRaises(ValueError):
            activity.update_readme("no markers", "new")

    def test_rejects_untrusted_repository_name(self):
        self.assertIsNone(
            activity.event_line({"type": "PushEvent", "repo": {"name": "owner/[link]"}})
        )


if __name__ == "__main__":
    unittest.main()
