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
        for bad in ('a"/b', "a/b<script>", "noslash", "a/b/c", "", "a/b\n"):
            with self.assertRaises(SystemExit):
                sh.validate_slug(bad)


class TestNiceStep(unittest.TestCase):
    def test_picks_round_steps(self):
        self.assertEqual(sh.nice_step(9), 2)        # ticks 0,2,4,6,8,10
        self.assertEqual(sh.nice_step(41), 10)      # ticks 0..50
        self.assertEqual(sh.nice_step(3011), 1000)  # ticks 0..4000

    def test_never_returns_zero(self):
        self.assertEqual(sh.nice_step(0), 1)
        self.assertEqual(sh.nice_step(1), 1)


ONE = {"repo": "Ovid/star-history",
       "points": [{"date": "2026-07-25", "stars": 1, "src": "snapshot"}]}

MIXED = {"repo": "Ovid/star-history", "points": [
    {"date": "2019-01-01", "stars": 1, "src": "backfill"},
    {"date": "2019-06-01", "stars": 40, "src": "backfill"},
    {"date": "2026-07-24", "stars": 3000, "src": "snapshot"},
    {"date": "2026-07-25", "stars": 3011, "src": "snapshot"},
]}


class TestRender(unittest.TestCase):
    def test_is_deterministic(self):
        """Same input, same bytes — otherwise CI commits a diff every day."""
        self.assertEqual(sh.render(MIXED, "light"), sh.render(MIXED, "light"))

    def test_themes_differ(self):
        self.assertNotEqual(sh.render(MIXED, "light"), sh.render(MIXED, "dark"))

    def test_single_point_history_renders(self):
        """A one-point history must not divide by zero or emit an empty chart."""
        svg = sh.render(ONE, "light")
        self.assertIn("<circle", svg)
        self.assertIn("</svg>", svg)

    def test_backfill_segment_is_dashed_and_snapshot_is_not(self):
        svg = sh.render(MIXED, "light")
        self.assertIn("stroke-dasharray", svg)
        self.assertIn("reconstructed", svg)

    def test_pure_snapshot_history_has_no_dashes(self):
        svg = sh.render({"repo": "o/r", "points": [
            {"date": "2026-07-24", "stars": 1, "src": "snapshot"},
            {"date": "2026-07-25", "stars": 2, "src": "snapshot"}]}, "light")
        self.assertNotIn("stroke-dasharray", svg)

    def test_contains_attribution_and_no_active_content(self):
        svg = sh.render(MIXED, "dark")
        self.assertIn("github.com/Ovid/star-history", svg)
        for forbidden in ("<script", "foreignObject", "onload", "xlink:href"):
            self.assertNotIn(forbidden, svg)
        # The SVG namespace is the one unavoidable absolute URL; nothing is fetched.
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', svg)
        self.assertEqual(svg.count("http://"), 1)

    def test_x_labels_are_not_repeated(self):
        """Two points in one month must not stack identical labels on one tick."""
        svg = sh.render(MIXED, "light")
        self.assertEqual(svg.count(">Jul 2026<"), 1)

    def test_light_has_opaque_background_and_dark_does_not(self):
        """Light must stay legible where <picture> is stripped."""
        self.assertIn('<rect width="800" height="400" fill="#ffffff"', sh.render(MIXED, "light"))
        self.assertNotIn("<rect width=\"800\"", sh.render(MIXED, "dark"))


if __name__ == "__main__":
    unittest.main()
