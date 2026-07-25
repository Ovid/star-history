#!/usr/bin/env python3
"""Record a GitHub repository's star count over time and render it as SVG.

Standard library only. See docs/plans/2026-07-25-star-history-design.md.
"""
import json
import math
import os
import re
import subprocess
import sys
from datetime import date

DATA_DIR = ".github/star-history"
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
SLUG_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")

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


def nice_step(maximum, target_ticks=5):
    """Smallest 1/2/5 x 10^k step giving about `target_ticks` gridlines."""
    raw = max(maximum, 1) / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 5):
        step = multiple * magnitude
        # Ticks are integers; sub-decade repos truncate to 0 and floor to 1.
        if step >= raw:
            return max(1, int(step))
    return max(1, int(10 * magnitude))


def validate_slug(slug):
    """The one trust boundary: the slug goes straight into SVG text and API URLs."""
    if not SLUG_RE.fullmatch(slug or ""):
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
    labelled = {}  # text -> point; the last point wins so the right edge is labelled
    for point in picked:
        labelled[date.fromisoformat(point["date"]).strftime(fmt)] = point
    return [(point, text) for text, point in labelled.items()]


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
        return " ".join(f"{sx(ordinals[i])},{sy(points[i]['stars'])}" for i in subset)

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
        # Centered text at the plot edge would clip; keep it inside the canvas.
        x = min(max(sx(date.fromisoformat(point["date"]).toordinal()), 32), WIDTH - 32)
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
