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
