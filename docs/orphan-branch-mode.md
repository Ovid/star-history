# Orphan-branch mode — deferred

Status: **not built.** Revisit when one of the triggers below fires.

## What it is

A git branch with no shared history — `git switch --orphan star-history` creates
a branch whose commit graph starts fresh, with no parent and no relationship to
the default branch. GitHub Pages' `gh-pages` convention is the familiar example:
generated output lives on a branch that never touches the source history.

Applied here, the generated files would live only on that branch:

    main            your code, your README. Never written to by the bot.
    star-history    orphan branch: history.json, light.svg, dark.svg. Nothing else.

The README on `main` would then reference absolute URLs instead of relative
paths:

```html
<source media="(prefers-color-scheme: dark)"
        srcset="https://raw.githubusercontent.com/OWNER/REPO/star-history/dark.svg">
```

## What it buys

**A clean default branch.** No daily bot commit, ever. `git log`, `git blame`,
`git bisect`, and release diffs never see the chart. This is the larger of the
two benefits and the one users will actually ask for.

**Branch protection stops mattering.** Required pull requests, required status
checks, and required signed commits are configured on the default branch. The
bot never pushes there, so none of them apply. This is the only workaround that
does not involve either a personal access token or a GitHub App: `github-actions[bot]`
cannot be added as a ruleset bypass actor, so there is no way to make a direct
push to a protected default branch work.

## Why it is deferred

It is a second implementation, not a flag.

**The workflow must check out one branch and commit to another.** `star_history.py`
lives on the default branch, so the job has to check that out to run at all,
then fetch and commit to `star-history`. That means `git fetch origin
star-history` plus `git worktree add`, or creating the orphan branch on first
run when it does not yet exist. Both paths need writing and testing.

**`update` must read its own prior state from a branch it is not on.**
`history.json` would live on the orphan branch. Today `update` reads and writes
one path in the working tree. Under this mode it needs the file from somewhere
else — a worktree, `git show star-history:history.json`, or a separate
checkout. That is a real code path in the Python, not just YAML.

**The README is broken until the first successful push.** Relative paths point
at files that appear in the same commit the user makes. Absolute
`raw.githubusercontent.com` URLs 404 until the workflow has run and pushed at
least once. A stranger pastes the snippet, sees a broken image, and concludes
the tool does not work.

**Absolute URLs bake `OWNER/REPO` into the README.** A repository rename or
transfer silently breaks the image. Relative paths survive both.

**It does not work on private repositories at all.** `raw.githubusercontent.com`
requires a token, which a README cannot supply.

## One thing the design doc originally got wrong

An earlier draft named camo caching as the main cost. That was incorrect, and
the correction matters if anyone re-costs this later.

GitHub does **not** proxy `raw.githubusercontent.com` URLs in rendered READMEs.
Verified by fetching a rendered README through the API: `raw.githubusercontent.com`
URLs come back unrewritten, while `img.shields.io` in the same document is
rewritten to `camo.githubusercontent.com`. And `raw.githubusercontent.com`
serves `cache-control: max-age=300`.

So the staleness cost is about **five minutes**, not the one-year `immutable`
TTL that genuine camo assets carry. For a chart that updates daily, that is
nothing. Camo is not an argument against this mode.

## Triggers for revisiting

Build it when any of these happens:

1. **Someone asks.** A user with a protected default branch, or one who does not
   want a daily bot commit in `git log`, is the whole audience for this. One
   real request outweighs all the speculation above.
2. **The daily commit becomes the top complaint.** If issues about `git log`
   noise outnumber everything else, this is the fix, not a `--quiet` flag or a
   weekly schedule (a weekly schedule visibly degrades the chart — see the
   design doc on point density).
3. **We want to support private repositories.** This mode makes that harder, not
   easier, so it would need a different answer — probably committing to the
   default branch as today.

## If we build it

Sketch, so the next person does not start from nothing:

- `--branch NAME` on `update`, defaulting to none (current behaviour).
- Workflow gains a step that fetches or creates the orphan branch into a
  worktree before running `update`, and commits inside that worktree.
- `snippet --branch NAME` already exists in the plan and emits absolute URLs;
  it needs the resolved slug, which `resolve_repo` already provides.
- `snippet` must refuse to print until the branch exists and has been pushed,
  for the broken-image reason above.
- Test: create a throwaway repo with an orphan branch and run the whole loop.
  This is the one part of the project that cannot be tested with pure functions.

Related: `docs/plans/2026-07-25-star-history-design.md`, "Branch protection".
