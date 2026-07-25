# Star History Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A single stdlib-only Python script plus one GitHub Actions workflow that records a repository's star count over time and renders it as light/dark SVG charts for a README — with no AI in the loop at install, update, or render.

**Architecture:** `star_history.py` has three subcommands. `update` runs in CI: one public API call for `stargazers_count`, append a point deduped by UTC date, render two SVGs. `backfill` runs once locally under the maintainer's own credentials, reconstructing pre-install history from GraphQL `starredAt` (owner-only since GitHub's 2026-06-30 restriction). `snippet` prints the README block. Data lives in `.github/star-history/history.json`; the two data sources are tagged `src` and rendered differently so a reconstruction is never drawn as a measurement.

**Tech Stack:** Python 3.12 standard library only (`urllib`, `json`, `argparse`, `subprocess`, `datetime`, `math`, `re`). Tests use stdlib `unittest`. No third-party dependencies anywhere, ever.

**Design doc:** `docs/plans/2026-07-25-star-history-design.md` — read it before starting. It records *why* several obvious-looking shortcuts are wrong.

---

## Conventions for every task

- Run tests with `python3 -m unittest -v` from the repo root.
- Commit after each task. Small commits.
- No new files beyond those listed. No abstractions with one caller.
- The script must remain runnable as `python3 star_history.py <cmd>` with no install step.

## Files this plan creates

```
star_history.py                        # the whole program
test_star_history.py                   # stdlib unittest
.github/workflows/star-history.yml     # our own copy (we dogfood)
README.md                              # written in Task 9
```

---

### Task 1: History file read/write and point insertion

**Files:**
- Create: `star_history.py`
- Create: `test_star_history.py`

**Step 1: Write the failing tests**

```python
import json, os, tempfile, unittest
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


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run to verify failure**

Run: `python3 -m unittest -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'star_history'`

**Step 3: Write the minimal implementation**

Create `star_history.py`:

```python
#!/usr/bin/env python3
"""Record a GitHub repository's star count over time and render it as SVG.

Standard library only. See docs/plans/2026-07-25-star-history-design.md.
"""
import json
import os

DATA_DIR = ".github/star-history"
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")


def load_history(path=HISTORY_PATH):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {"repo": None, "points": []}


def save_history(state, path=HISTORY_PATH):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def add_point(state, day, stars, src="snapshot"):
    """Insert a point for ISO date string `day`, replacing any point for that date.

    Mutates `state` in place. Sorting is lexicographic, which matches
    chronological order only because the dates are zero-padded ISO.
    """
    points = [p for p in state["points"] if p["date"] != day]
    points.append({"date": day, "stars": stars, "src": src})
    points.sort(key=lambda p: p["date"])
    state["points"] = points
```

**Step 4: Run to verify pass**

Run: `python3 -m unittest -v`
Expected: 6 tests, OK

**Step 5: Commit**

```bash
git add star_history.py test_star_history.py
git commit -m "feat: history file read, write, and date-deduped point insertion"
```

---

### Task 2: Repository slug resolution

`$GITHUB_REPOSITORY` only exists in CI. `backfill` and `snippet` run locally. This is also our trust boundary — the slug lands in SVG output, so it gets validated here rather than escaped everywhere downstream.

**Files:**
- Modify: `star_history.py`
- Modify: `test_star_history.py`

**Step 1: Write the failing tests**

```python
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
```

Add `import unittest.mock` to the test imports.

**Step 2: Run to verify failure**

Run: `python3 -m unittest -v`
Expected: FAIL — `AttributeError: module 'star_history' has no attribute 'resolve_repo'`

**Step 3: Write the minimal implementation**

```python
import re
import subprocess
import sys

SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def validate_slug(slug):
    if not SLUG_RE.match(slug or ""):
        sys.exit(f"not a valid OWNER/NAME repository slug: {slug!r}")
    return slug


def parse_remote(url):
    match = re.search(r"[:/]([A-Za-z0-9._-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$", url)
    return match.group(1) if match else None


def resolve_repo(explicit=None):
    """--repo flag, then $GITHUB_REPOSITORY, then the origin remote."""
    if explicit:
        return validate_slug(explicit)
    env = os.environ.get("GITHUB_REPOSITORY")
    if env:
        return validate_slug(env)
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        url = ""
    slug = parse_remote(url)
    if not slug:
        sys.exit("cannot determine the repository; pass --repo OWNER/NAME")
    return validate_slug(slug)
```

**Step 4: Run to verify pass**

Run: `python3 -m unittest -v`
Expected: 11 tests, OK

**Step 5: Commit**

```bash
git add star_history.py test_star_history.py
git commit -m "feat: resolve repository slug from flag, env, or git remote"
```

---

### Task 3: Axis scaling helper

Small and pure, but it is the difference between readable tick labels and `0, 602, 1204`.

**Files:**
- Modify: `star_history.py`
- Modify: `test_star_history.py`

**Step 1: Write the failing tests**

```python
class TestNiceStep(unittest.TestCase):
    def test_picks_round_steps(self):
        self.assertEqual(sh.nice_step(9), 2)        # ticks 0,2,4,6,8,10
        self.assertEqual(sh.nice_step(41), 10)      # ticks 0..50
        self.assertEqual(sh.nice_step(3011), 1000)  # ticks 0..4000

    def test_never_returns_zero(self):
        self.assertEqual(sh.nice_step(0), 1)
        self.assertEqual(sh.nice_step(1), 1)
```

**Step 2: Run to verify failure**

Run: `python3 -m unittest -v`
Expected: FAIL — no attribute `nice_step`

**Step 3: Write the minimal implementation**

```python
import math


def nice_step(maximum, target_ticks=5):
    """Smallest 1/2/5 x 10^k step giving about `target_ticks` gridlines."""
    raw = max(maximum, 1) / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 5, 10):
        step = multiple * magnitude
        if step >= raw:
            return max(1, int(step))
    return max(1, int(magnitude * 10))
```

**Step 4: Run to verify pass**

Run: `python3 -m unittest -v`
Expected: 13 tests, OK

**Step 5: Commit**

```bash
git add star_history.py test_star_history.py
git commit -m "feat: round axis step selection"
```

---

### Task 4: SVG rendering

The largest task. Three properties matter and each gets a test: it is byte-deterministic, it survives a single-point history, and it draws the backfill seam differently from measured data.

**Files:**
- Modify: `star_history.py`
- Modify: `test_star_history.py`

**Step 1: Write the failing tests**

```python
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
        for forbidden in ("<script", "foreignObject", "onload", "http://", "xlink:href"):
            self.assertNotIn(forbidden, svg)

    def test_light_has_opaque_background_and_dark_does_not(self):
        """Light must stay legible where <picture> is stripped."""
        self.assertIn('<rect width="800" height="400" fill="#ffffff"', sh.render(MIXED, "light"))
        self.assertNotIn("<rect width=\"800\"", sh.render(MIXED, "dark"))
```

**Step 2: Run to verify failure**

Run: `python3 -m unittest -v`
Expected: FAIL — no attribute `render`

**Step 3: Write the minimal implementation**

```python
from datetime import date

WIDTH, HEIGHT = 800, 400
PAD_L, PAD_R, PAD_T, PAD_B = 60, 20, 30, 50
PLOT_W = WIDTH - PAD_L - PAD_R
PLOT_H = HEIGHT - PAD_T - PAD_B

LINE_COLOR = "#e5533d"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
ATTRIBUTION = "github.com/Ovid/star-history"

THEMES = {
    "light": {"fg": "#24292f", "muted": "#57606a", "grid": "#d0d7de", "bg": "#ffffff"},
    "dark":  {"fg": "#c9d1d9", "muted": "#8b949e", "grid": "#30363d", "bg": None},
}


def _label_dates(points):
    """About six evenly spaced x labels; year shown only on long ranges."""
    span_days = (date.fromisoformat(points[-1]["date"]).toordinal()
                 - date.fromisoformat(points[0]["date"]).toordinal())
    fmt = "%b %Y" if span_days > 400 else "%b %d"
    count = min(6, len(points))
    step = max(1, (len(points) - 1) // max(1, count - 1)) if count > 1 else 1
    picked = points[::step]
    if picked[-1] is not points[-1]:
        picked.append(points[-1])
    return [(p, date.fromisoformat(p["date"]).strftime(fmt)) for p in picked]


def render(state, theme):
    """Return a deterministic, self-contained SVG string for one theme."""
    colors = THEMES[theme]
    points = state["points"]
    if not points:
        raise ValueError("cannot render an empty history")

    slug = validate_slug(state["repo"])
    ordinals = [date.fromisoformat(p["date"]).toordinal() for p in points]
    first, last = ordinals[0], ordinals[-1]
    span = max(1, last - first)
    peak = max(p["stars"] for p in points)
    step = nice_step(peak)
    top = max(step, math.ceil(peak / step) * step)

    def sx(ordinal):
        return PAD_L + round((ordinal - first) / span * PLOT_W)

    def sy(value):
        return PAD_T + round((1 - value / top) * PLOT_H)

    def polyline(subset):
        return " ".join(f"{sx(o)},{sy(p['stars'])}"
                        for o, p in zip([ordinals[i] for i in subset],
                                        [points[i] for i in subset]))

    backfill = [i for i, p in enumerate(points) if p["src"] == "backfill"]
    if backfill:
        cut = backfill[-1]
        dashed_idx = list(range(0, min(cut + 2, len(points))))
        solid_idx = list(range(cut + 1, len(points)))
    else:
        dashed_idx, solid_idx = [], list(range(len(points)))

    latest = points[-1]
    alt = (f"Star history for {slug}: {latest['stars']:,} stars "
           f"as of {latest['date']}")

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="{WIDTH}" height="{HEIGHT}" role="img" aria-label="{alt}">',
        f"<title>{alt}</title>",
        f"<desc>Cumulative GitHub stars for {slug} over time.</desc>",
    ]
    if colors["bg"]:
        out.append(f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{colors["bg"]}"/>')

    value = 0
    while value <= top:
        y = sy(value)
        out.append(f'<line x1="{PAD_L}" y1="{y}" x2="{PAD_L + PLOT_W}" y2="{y}" '
                   f'stroke="{colors["grid"]}" stroke-width="1"/>')
        out.append(f'<text x="{PAD_L - 8}" y="{y + 4}" text-anchor="end" '
                   f'font-family="{FONT}" font-size="12" '
                   f'fill="{colors["muted"]}">{value:,}</text>')
        value += step

    for point, text in _label_dates(points):
        x = sx(date.fromisoformat(point["date"]).toordinal())
        out.append(f'<text x="{x}" y="{PAD_T + PLOT_H + 20}" text-anchor="middle" '
                   f'font-family="{FONT}" font-size="12" '
                   f'fill="{colors["muted"]}">{text}</text>')

    if len(dashed_idx) > 1:
        out.append(f'<polyline fill="none" stroke="{LINE_COLOR}" stroke-width="2" '
                   f'stroke-dasharray="5 4" points="{polyline(dashed_idx)}"/>')
    if len(solid_idx) > 1:
        out.append(f'<polyline fill="none" stroke="{LINE_COLOR}" stroke-width="2" '
                   f'points="{polyline(solid_idx)}"/>')
    out.append(f'<circle cx="{sx(last)}" cy="{sy(latest["stars"])}" r="3.5" '
               f'fill="{LINE_COLOR}"/>')

    out.append(f'<rect x="{PAD_L}" y="10" width="10" height="10" fill="{LINE_COLOR}"/>')
    legend = f"{slug} — dashed is reconstructed" if backfill else slug
    out.append(f'<text x="{PAD_L + 16}" y="19" font-family="{FONT}" font-size="13" '
               f'fill="{colors["fg"]}">{legend}</text>')
    out.append(f'<text x="{WIDTH - PAD_R}" y="{HEIGHT - 10}" text-anchor="end" '
               f'font-family="{FONT}" font-size="11" '
               f'fill="{colors["muted"]}">{ATTRIBUTION}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_all(state, data_dir=DATA_DIR):
    os.makedirs(data_dir, exist_ok=True)
    for theme in ("light", "dark"):
        with open(os.path.join(data_dir, f"{theme}.svg"), "w", encoding="utf-8") as handle:
            handle.write(render(state, theme))
```

**Step 4: Run to verify pass**

Run: `python3 -m unittest -v`
Expected: 20 tests, OK

**Step 5: Eyeball the output**

```bash
python3 - <<'EOF'
import json, star_history as sh
state = {"repo": "Ovid/star-history", "points": [
    {"date": "2026-04-01", "stars": 1, "src": "snapshot"},
    {"date": "2026-05-15", "stars": 12, "src": "snapshot"},
    {"date": "2026-07-25", "stars": 55, "src": "snapshot"}]}
sh.render_all(state, "/tmp/sh-preview")
EOF
open /tmp/sh-preview/light.svg
```

Expected: readable chart, round y ticks, labels not overlapping. Adjust padding constants if they collide. This is the one step where judgment beats a test.

**Step 6: Commit**

```bash
git add star_history.py test_star_history.py
git commit -m "feat: deterministic light and dark SVG rendering with backfill seam"
```

---

### Task 5: Fetching the current star count

**Files:**
- Modify: `star_history.py`
- Modify: `test_star_history.py`

**Step 1: Write the failing tests**

```python
class TestFetch(unittest.TestCase):
    def test_extracts_star_count(self):
        with unittest.mock.patch.object(sh, "http_json",
                                        return_value={"stargazers_count": 42}):
            self.assertEqual(sh.fetch_star_count("o/r"), 42)

    def test_missing_field_raises_rather_than_recording_garbage(self):
        with unittest.mock.patch.object(sh, "http_json", return_value={}):
            with self.assertRaises(SystemExit):
                sh.fetch_star_count("o/r")
```

**Step 2: Run to verify failure**

Run: `python3 -m unittest -v`
Expected: FAIL — no attribute `fetch_star_count`

**Step 3: Write the minimal implementation**

```python
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 1_000_000
API_ROOT = "https://api.github.com"


def http_json(url, token=None, data=None, accept="application/vnd.github+json"):
    """One bounded, timed HTTP call. Any failure is fatal by design: a bad
    response must never be recorded as a data point."""
    headers = {"Accept": accept, "User-Agent": "star-history"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    if body:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read(MAX_RESPONSE_BYTES))
    except urllib.error.HTTPError as error:
        sys.exit(f"GitHub returned HTTP {error.code} for {url}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        sys.exit(f"could not reach GitHub: {error}")


def fetch_star_count(repo, token=None):
    payload = http_json(f"{API_ROOT}/repos/{repo}", token)
    if "stargazers_count" not in payload:
        sys.exit(f"no stargazers_count in the API response for {repo}")
    return int(payload["stargazers_count"])
```

**Step 4: Run to verify pass**

Run: `python3 -m unittest -v`
Expected: 22 tests, OK

**Step 5: Verify against the real API**

```bash
python3 -c "import star_history as sh; print(sh.fetch_star_count('psf/requests'))"
```
Expected: a number in the tens of thousands.

**Step 6: Commit**

```bash
git add star_history.py test_star_history.py
git commit -m "feat: bounded star count fetch with fatal error handling"
```

---

### Task 6: The `update` and `snippet` subcommands

**Files:**
- Modify: `star_history.py`
- Modify: `test_star_history.py`

**Step 1: Write the failing tests**

```python
class TestSnippet(unittest.TestCase):
    def test_includes_count_and_date_in_alt_text(self):
        block = sh.snippet_block(MIXED)
        self.assertIn('alt="Star history for Ovid/star-history: 3,011 stars '
                      'as of 2026-07-25"', block)

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
```

Add `import argparse` to the test imports.

**Step 2: Run to verify failure**

Run: `python3 -m unittest -v`
Expected: FAIL — no attribute `snippet_block`

**Step 3: Write the minimal implementation**

```python
from datetime import datetime, timezone

PROJECT_URL = "https://github.com/Ovid/star-history"


def today_utc():
    return datetime.now(timezone.utc).date().isoformat()


def snippet_block(state, data_dir=DATA_DIR):
    latest = state["points"][-1]
    alt = (f"Star history for {state['repo']}: {latest['stars']:,} stars "
           f"as of {latest['date']}")
    return (
        f'<a href="{PROJECT_URL}">\n'
        f"  <picture>\n"
        f'    <source media="(prefers-color-scheme: dark)"  srcset="{data_dir}/dark.svg">\n'
        f'    <source media="(prefers-color-scheme: light)" srcset="{data_dir}/light.svg">\n'
        f'    <img alt="{alt}" src="{data_dir}/light.svg" width="800">\n'
        f"  </picture>\n"
        f"</a>\n"
    )


def cmd_update(args):
    data_dir = args.data_dir or DATA_DIR
    path = os.path.join(data_dir, "history.json")
    repo = resolve_repo(args.repo)
    state = load_history(path)
    if state.get("repo") and state["repo"] != repo:
        print(f"note: repository renamed {state['repo']} -> {repo}", file=sys.stderr)
    state["repo"] = repo
    count = fetch_star_count(repo, os.environ.get("GITHUB_TOKEN"))
    add_point(state, today_utc(), count)
    save_history(state, path)
    render_all(state, data_dir)
    print(f"{repo}: {count} stars, {len(state['points'])} points")


def cmd_snippet(args):
    data_dir = args.data_dir or DATA_DIR
    state = load_history(os.path.join(data_dir, "history.json"))
    if not state["points"]:
        sys.exit("no history yet — run the workflow once, then try again")
    print(snippet_block(state, data_dir))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="OWNER/NAME (default: env or git remote)")
    parser.add_argument("--data-dir", default=DATA_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("update", help="record today's count and render")
    sub.add_parser("snippet", help="print the README block")
    args = parser.parse_args(argv)
    {"update": cmd_update, "snippet": cmd_snippet}[args.command](args)


if __name__ == "__main__":
    main()
```

Add `import argparse` at the top of `star_history.py`.

**Step 4: Run to verify pass**

Run: `python3 -m unittest -v`
Expected: 26 tests, OK

**Step 5: Commit**

```bash
git add star_history.py test_star_history.py
git commit -m "feat: update and snippet subcommands"
```

---

### Task 7: `backfill`

Owner-only, run once, locally. The critical behaviour: GitHub returns an **empty edge list rather than an error** when you lack access, so a naive implementation writes a history of zero stars. That case gets its own test.

**Files:**
- Modify: `star_history.py`
- Modify: `test_star_history.py`

**Step 1: Write the failing tests**

```python
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
```

**Step 2: Run to verify failure**

Run: `python3 -m unittest -v`
Expected: FAIL — no attribute `cumulative_points`

**Step 3: Write the minimal implementation**

```python
GRAPHQL_URL = "https://api.github.com/graphql"
STARGAZER_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    stargazerCount
    stargazers(first:100, after:$cursor,
               orderBy:{field:STARRED_AT, direction:ASC}) {
      pageInfo { hasNextPage endCursor }
      edges { starredAt }
    }
  }
}
"""


def cumulative_points(timestamps):
    """One point per day on which the star count changed."""
    running = 0
    per_day = {}
    for stamp in sorted(timestamps):
        running += 1
        per_day[stamp[:10]] = running
    return [{"date": day, "stars": total, "src": "backfill"}
            for day, total in sorted(per_day.items())]


def check_backfill_complete(collected, reported):
    if reported > 0 and collected == 0:
        sys.exit(
            "GitHub returned no star timestamps. Since 2026-06-30 these are "
            "restricted to repository admins and collaborators, and the API "
            "returns an empty list rather than an error. Backfill only works "
            "on repositories you own or help maintain; snapshot-only mode "
            "works everywhere."
        )
    if reported and abs(collected - reported) > max(5, reported * 0.01):
        sys.exit(f"only {collected} of {reported} stars retrieved; "
                 f"re-run backfill")


def merge_backfill(state, points):
    """Fill only dates the measured record does not already cover."""
    measured = {p["date"] for p in state["points"] if p["src"] == "snapshot"}
    earliest = min(measured) if measured else None
    for point in points:
        if point["date"] in measured:
            continue
        if earliest and point["date"] >= earliest:
            continue
        add_point(state, point["date"], point["stars"], src="backfill")


def backfill_token():
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        sys.exit("no credentials: set GITHUB_TOKEN or run 'gh auth login'")


def fetch_star_timestamps(repo, token):
    owner, name = repo.split("/")
    cursor, stamps, reported = None, [], 0
    while True:
        payload = http_json(GRAPHQL_URL, token, data={
            "query": STARGAZER_QUERY,
            "variables": {"owner": owner, "name": name, "cursor": cursor}})
        if "errors" in payload:
            sys.exit(f"GraphQL error: {payload['errors']}")
        node = payload["data"]["repository"]["stargazers"]
        reported = payload["data"]["repository"]["stargazerCount"]
        stamps.extend(edge["starredAt"] for edge in node["edges"])
        print(f"  {len(stamps)}/{reported}", file=sys.stderr)
        if not node["pageInfo"]["hasNextPage"]:
            return stamps, reported
        cursor = node["pageInfo"]["endCursor"]


def cmd_backfill(args):
    data_dir = args.data_dir or DATA_DIR
    path = os.path.join(data_dir, "history.json")
    repo = resolve_repo(args.repo)
    state = load_history(path)
    if any(p["src"] == "backfill" for p in state["points"]) and not args.force:
        sys.exit("history already contains backfilled points; pass --force")
    stamps, reported = fetch_star_timestamps(repo, backfill_token())
    check_backfill_complete(len(stamps), reported)
    state["repo"] = repo
    merge_backfill(state, cumulative_points(stamps))
    save_history(state, path)
    render_all(state, data_dir)
    print(f"{repo}: backfilled {len(stamps)} stars")
```

Register the subcommand in `main`:

```python
    backfill = sub.add_parser("backfill", help="one-time local history rebuild")
    backfill.add_argument("--force", action="store_true")
```
and add `"backfill": cmd_backfill` to the dispatch dict.

**Step 4: Run to verify pass**

Run: `python3 -m unittest -v`
Expected: 30 tests, OK

**Step 5: Verify the restriction message against a real repo you do not own**

```bash
python3 star_history.py --repo psf/requests --data-dir /tmp/sh-x backfill
```
Expected: exits with the "restricted to repository admins" message, not a traceback and not a zero-star chart.

**Step 6: Commit**

```bash
git add star_history.py test_star_history.py
git commit -m "feat: one-time local backfill with restriction detection"
```

---

### Task 8: The workflow

**Files:**
- Create: `.github/workflows/star-history.yml`

**Step 1: Write the file**

```yaml
name: star-history
on:
  schedule: [{cron: "17 3 * * *"}]
  push: {paths: ['.github/workflows/star-history.yml']}
  workflow_dispatch:
permissions: {contents: write}
concurrency: {group: star-history}
jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 star_history.py update
        env: {GITHUB_TOKEN: "${{ github.token }}"}
      - run: |
          git add -A .github/star-history
          git diff --cached --quiet && exit 0
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git commit -m "chore: update star history"
          git push
```

**Step 2: Verify the commit logic locally before trusting it**

The previous draft of this workflow committed nothing on every run while
reporting success. Prove this one works:

```bash
cd /tmp && rm -rf wf && mkdir wf && cd wf && git init -q .
git commit -q --allow-empty -m init
mkdir -p .github/star-history && echo '<svg/>' > .github/star-history/light.svg
git add -A .github/star-history
git diff --cached --quiet && echo "WRONG: sees no change" || echo "ok: sees the new file"
```
Expected: `ok: sees the new file`. If it prints WRONG, stop — the guard is broken again.

**Step 3: Commit**

```bash
git add .github/workflows/star-history.yml
git commit -m "ci: daily star history workflow"
```

---

### Task 9: README

**Files:**
- Create: `README.md`

**REQUIRED SKILL:** Use `talk-about-us:talk-about-us` — this is the public face of a repo meant to be shared, so it must be written so someone else can describe it accurately without us in the room.

**Content it must cover, honestly:**

- What it does, in one sentence, above the fold.
- **Why it exists now:** GitHub restricted star timestamps on 2026-06-30, so hosted chart services can no longer read them for repos they do not own. Include the verified evidence.
- Install: copy two files, commit, the `push` trigger renders the first chart, then run `python3 star_history.py snippet` and paste the output.
- Optional backfill: needs write access and `gh`; snapshot-only works without it.
- **The costs, stated plainly and not buried:** `contents: write`, one bot commit per day, and that branch protection (required PRs, required status checks, or required signed commits) will reject the push because `github-actions[bot]` cannot be a ruleset bypass actor.
- **What the chart does and does not mean:** snapshots are measurements, backfilled history is a reconstruction that cannot show unstars and changes if re-run. The dashed segment marks it.
- A live example — this repo's own chart (Task 10).

**Commit**

```bash
git add README.md
git commit -m "docs: README"
```

---

### Task 10: Dogfood

**Files:**
- Modify: `README.md`
- Creates: `.github/star-history/*`

**Steps**

1. `python3 star_history.py backfill` — this repo is owned by the maintainer, so timestamps are available.
2. `python3 star_history.py update` — end on a measured point.
3. `python3 star_history.py snippet` and paste the output into `README.md`.
4. Open both SVGs and confirm the dashed backfill segment meets the solid snapshot segment cleanly.
5. Commit:

```bash
git add README.md .github/star-history
git commit -m "docs: add this repo's own star history chart"
```

---

## Definition of done

- `python3 -m unittest -v` passes with 30 tests.
- `python3 star_history.py update` on a fresh directory produces `history.json`, `light.svg`, `dark.svg`.
- `python3 star_history.py --repo psf/requests backfill` fails with the restriction message, not a traceback.
- The workflow's `git add -A` + `git diff --cached --quiet` guard verified by hand (Task 8, Step 2).
- `README.md` states the three costs without euphemism.
- The repo renders its own chart.

## Explicitly not built

Orphan-branch mode, pull-request mode, GitHub App tokens, `setup-python`,
downsampling, spline interpolation, embedded fonts, avatars, and a `--selfcheck`
flag (tests live here, not in the user's repo).
