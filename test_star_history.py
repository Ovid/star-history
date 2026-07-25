import argparse, json, os, tempfile, unittest
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

    def test_single_point_history_renders_a_card_not_a_chart(self):
        """One measurement is not a time series: state it, don't plot it."""
        svg = sh.render(ONE, "light")
        self.assertIn("</svg>", svg)
        self.assertIn(">1</text>", svg)
        self.assertIn(">star</text>", svg)
        self.assertIn("Recording since Jul 25, 2026", svg)
        for chart_only in ("<polyline", "<circle", "<line "):
            self.assertNotIn(chart_only, svg)

    def test_zero_stars_does_not_plot_a_dot_on_the_floor(self):
        svg = sh.render({"repo": "o/r", "points": [
            {"date": "2026-07-25", "stars": 0, "src": "snapshot"}]}, "light")
        self.assertIn(">0</text>", svg)
        self.assertIn(">stars</text>", svg)
        self.assertNotIn("<circle", svg)

    def test_card_becomes_a_chart_at_the_second_point(self):
        two = {"repo": "o/r", "points": [
            {"date": "2026-07-24", "stars": 1, "src": "snapshot"},
            {"date": "2026-07-25", "stars": 2, "src": "snapshot"}]}
        self.assertIn("<polyline", sh.render(two, "light"))

    def test_card_is_shorter_than_the_chart(self):
        """The whole point: don't spend 400px saying there is no data yet."""
        self.assertIn('height="150"', sh.render(ONE, "light"))
        self.assertIn('height="400"', sh.render(MIXED, "light"))

    def test_card_says_when_the_number_is_reconstructed(self):
        """A backfilled count must never read as a measurement."""
        card = sh.render({"repo": "o/r", "points": [
            {"date": "2019-01-01", "stars": 12, "src": "backfill"}]}, "light")
        self.assertIn("Reconstructed", card)
        self.assertNotIn("Recording since", card)

    def test_card_follows_the_theme_rules(self):
        light, dark = sh.render(ONE, "light"), sh.render(ONE, "dark")
        self.assertIn('<rect width="800" height="150" fill="#ffffff"', light)
        self.assertNotIn('<rect width="800"', dark)
        self.assertEqual(sh.render(ONE, "light"), light)  # deterministic

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

    def test_x_labels_do_not_crowd_each_other(self):
        """A daily history's last label used to land 10px from its neighbour."""
        import datetime, re as _re
        start = datetime.date(2026, 3, 16).toordinal()
        # Real star data clusters: sparse for months, then several days in a row.
        days = [start + 5 * i for i in range(26)] + [start + 128 + i for i in range(4)]
        clustered = {"repo": "o/r", "points": [
            {"date": datetime.date.fromordinal(d).isoformat(),
             "stars": i + 1, "src": "snapshot"} for i, d in enumerate(days)]}
        xs = [int(x) for x in _re.findall(r'<text x="(\d+)" y="370"',
                                          sh.render(clustered, "light"))]
        self.assertGreater(len(xs), 2)
        for left, right in zip(sorted(xs), sorted(xs)[1:]):
            self.assertGreaterEqual(right - left, 60, f"labels collide at {xs}")

    def test_x_labels_are_not_repeated(self):
        """Two points in one month must not stack identical labels on one tick."""
        svg = sh.render(MIXED, "light")
        self.assertEqual(svg.count(">Jul 2026<"), 1)

    def test_light_has_opaque_background_and_dark_does_not(self):
        """Light must stay legible where <picture> is stripped."""
        self.assertIn('<rect width="800" height="400" fill="#ffffff"', sh.render(MIXED, "light"))
        self.assertNotIn("<rect width=\"800\"", sh.render(MIXED, "dark"))


class TestFetch(unittest.TestCase):
    def test_extracts_star_count(self):
        with unittest.mock.patch.object(sh, "http_json",
                                        return_value={"stargazers_count": 42}):
            self.assertEqual(sh.fetch_star_count("o/r"), 42)

    def test_untokened_404_names_the_private_repo_case(self):
        """A private repo 404s exactly like a missing one; say so."""
        import urllib.error
        error = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with unittest.mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(SystemExit) as caught:
                sh.http_json("https://api.github.com/repos/o/r")
            self.assertIn("GITHUB_TOKEN", str(caught.exception))
            with self.assertRaises(SystemExit) as with_token:
                sh.http_json("https://api.github.com/repos/o/r", token="t")
            self.assertNotIn("GITHUB_TOKEN", str(with_token.exception))

    def test_missing_field_raises_rather_than_recording_garbage(self):
        with unittest.mock.patch.object(sh, "http_json", return_value={}):
            with self.assertRaises(SystemExit):
                sh.fetch_star_count("o/r")


class TestSnippet(unittest.TestCase):
    def test_includes_count_and_date_in_alt_text(self):
        block = sh.snippet_block(MIXED)
        self.assertIn('alt="Star history for Ovid/star-history: 3,011 stars '
                      'as of 2026-07-25"', block)

    def test_a_single_star_is_not_described_as_1_stars(self):
        self.assertIn('alt="Star history for Ovid/star-history: 1 star '
                      'as of 2026-07-25"', sh.snippet_block(ONE))
        self.assertIn("1 star as of", sh.render(ONE, "light"))

    def test_links_to_the_project(self):
        self.assertIn('<a href="https://github.com/Ovid/star-history">',
                      sh.snippet_block(MIXED))

    def test_references_both_themes(self):
        block = sh.snippet_block(MIXED)
        self.assertIn(".github/star-history/dark.svg", block)
        self.assertIn(".github/star-history/light.svg", block)


class TestUpdate(unittest.TestCase):
    def test_records_todays_count_and_writes_both_svgs(self):
        with tempfile.TemporaryDirectory() as d:
            with unittest.mock.patch.object(sh, "fetch_star_count", return_value=7), \
                 unittest.mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r"}):
                sh.cmd_update(argparse.Namespace(repo=None, data_dir=d))
            state = sh.load_history(os.path.join(d, "history.json"))
            self.assertEqual(state["points"][-1]["stars"], 7)
            self.assertEqual(state["repo"], "o/r")
            self.assertTrue(os.path.exists(os.path.join(d, "light.svg")))
            self.assertTrue(os.path.exists(os.path.join(d, "dark.svg")))


class TestBackfill(unittest.TestCase):
    def test_builds_cumulative_points_from_timestamps(self):
        stamps = ["2019-01-01T00:00:00Z", "2019-01-01T12:00:00Z",
                  "2019-03-02T00:00:00Z"]
        self.assertEqual(sh.cumulative_points(stamps), [
            {"date": "2019-01-01", "stars": 2, "src": "backfill"},
            {"date": "2019-03-02", "stars": 3, "src": "backfill"},
        ])

    def test_empty_edges_with_nonzero_count_is_fatal(self):
        """The 2026-06-30 restriction returns [] rather than an error."""
        with self.assertRaises(SystemExit):
            sh.check_backfill_complete(collected=0, reported=54173)

    def test_small_drift_is_tolerated(self):
        """Stars change during a multi-minute paginated run."""
        sh.check_backfill_complete(collected=999, reported=1000)

    def test_merge_never_overwrites_a_measured_point(self):
        state = {"repo": "o/r", "points": [
            {"date": "2026-07-25", "stars": 3011, "src": "snapshot"}]}
        sh.merge_backfill(state, [
            {"date": "2019-01-01", "stars": 1, "src": "backfill"},
            {"date": "2026-07-25", "stars": 9, "src": "backfill"},
        ])
        dates = [(p["date"], p["src"]) for p in state["points"]]
        self.assertEqual(dates, [("2019-01-01", "backfill"),
                                 ("2026-07-25", "snapshot")])


if __name__ == "__main__":
    unittest.main()
