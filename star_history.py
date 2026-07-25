#!/usr/bin/env python3
"""Record a GitHub repository's star count over time and render it as SVG.

Standard library only. See docs/plans/2026-07-25-star-history-design.md.
"""
import json
import os
import re
import subprocess
import sys

DATA_DIR = ".github/star-history"
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


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


def validate_slug(slug):
    """The one trust boundary: the slug is interpolated straight into the SVG."""
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
