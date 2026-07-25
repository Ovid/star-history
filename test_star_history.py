import json, os, tempfile, unittest
import unittest.mock
import star_history as sh


class TestHistory(unittest.TestCase):
    def test_load_missing_file_returns_empty_state(self):
        state = sh.load_history("/nonexistent/history.json")
        self.assertEqual(state, {"repo": None, "points": []})

    def test_add_point_appends(self):
        state = {"repo": "o/r", "points": []}
        sh.add_point(state, "2026-07-25", 10)
        self.assertEqual(state["points"],
                         [{"date": "2026-07-25", "stars": 10, "src": "snapshot"}])

    def test_add_point_replaces_same_date(self):
        """Two runs on one UTC day must not create two points."""
        state = {"repo": "o/r", "points": []}
        sh.add_point(state, "2026-07-25", 10)
        sh.add_point(state, "2026-07-25", 12)
        self.assertEqual(len(state["points"]), 1)
        self.assertEqual(state["points"][0]["stars"], 12)

    def test_add_point_keeps_points_sorted_by_date(self):
        state = {"repo": "o/r", "points": []}
        sh.add_point(state, "2026-07-25", 10)
        sh.add_point(state, "2019-01-01", 1, src="backfill")
        self.assertEqual([p["date"] for p in state["points"]],
                         ["2019-01-01", "2026-07-25"])

    def test_save_then_load_roundtrips(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "history.json")
            state = {"repo": "o/r",
                     "points": [{"date": "2026-07-25", "stars": 3, "src": "snapshot"}]}
            sh.save_history(state, path)
            self.assertEqual(sh.load_history(path), state)

    def test_save_leaves_no_tmp_file(self):
        """Atomic write via os.replace must not leave debris."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.json")
            sh.save_history({"repo": "o/r", "points": []}, path)
            self.assertEqual(os.listdir(d), ["history.json"])


class TestResolveRepo(unittest.TestCase):
    def test_explicit_flag_wins(self):
        self.assertEqual(sh.resolve_repo("owner/name"), "owner/name")

    def test_falls_back_to_env(self):
        with unittest.mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r"}):
            self.assertEqual(sh.resolve_repo(None), "o/r")

    def test_parses_ssh_remote(self):
        self.assertEqual(sh.parse_remote("git@github.com:Ovid/star-history.git"),
                         "Ovid/star-history")

    def test_parses_https_remote(self):
        self.assertEqual(sh.parse_remote("https://github.com/Ovid/star-history"),
                         "Ovid/star-history")

    def test_rejects_slug_that_could_break_out_of_svg(self):
        for bad in ('a"/b', "a/b<script>", "noslash", "a/b/c", ""):
            with self.assertRaises(SystemExit):
                sh.validate_slug(bad)


if __name__ == "__main__":
    unittest.main()
