# star-history

Put a star-history chart in your README, generated inside your own repository,
with no hosted service and no AI in the loop.

Copy two files, commit, paste one snippet. A daily GitHub Action records your
star count and redraws two SVGs — one for light mode, one for dark.

## Why this exists now

On 2026-06-30 GitHub restricted stargazer *timestamps* to a repository's admins
and collaborators. Hosted chart services read those timestamps for repos they
don't own, so that path is closed to them. The maintainer of a repo is now the
only person who can read its star history — which is why this tool runs in your
repo instead of someone else's.

Verified against the live API on 2026-07-25, using `psf/requests`:

| Call | Result |
|------|--------|
| `GET /repos/psf/requests` → `stargazers_count` | `54172` — still public |
| GraphQL `stargazers { edges { starredAt } }` | `[]` — empty, for a repo reporting 54,172 stars |
| `GET /repos/psf/requests/stargazers` with `Accept: vnd.github.star+json` | `404` |

Note the second row: the restricted response is an **empty list, not an error**.
A tool that trusts it renders a history of zero stars and calls it a success.
This one cross-checks the number of timestamps it received against
`stargazerCount` and refuses to write anything if they disagree.

The count itself is still public, so the daily snapshot works on any repository,
forever.

## Install

1. Copy `star_history.py` and `.github/workflows/star-history.yml` into your
   repository, keeping the workflow's path.
2. Commit and push both files. The workflow's `push` trigger fires on the
   workflow file itself, so the first chart is rendered within a minute — no
   waiting for tomorrow's cron.
3. Run `python3 star_history.py snippet` and paste the output into your README.

The snippet refuses to print until the first run has produced data, so you can't
paste a block pointing at files that don't exist yet.

Nothing to install, no dependencies, no build step. One file of Python 3.12
standard library.

## Optional: backfill your existing history

A fresh install starts recording today. If you want the years before it:

```bash
gh auth login          # or export GITHUB_TOKEN
python3 star_history.py backfill
```

This is a one-time local operation. It needs admin or collaborator access to the
repository — the same restriction described above — so it works on repos you own
and fails with a clear message on repos you don't. Snapshot-only mode works
everywhere and needs none of this.

## What this costs you

Stated plainly, because you're committing to it:

- **`contents: write` permission.** A chart in a README has to be a committed
  file, and the workflow has to commit it.
- **One bot commit per day**, in your default branch's history. The workflow
  writes a point every day whether or not the count changed, because GitHub
  disables scheduled workflows in public repos after 60 days of inactivity, and
  because a chart whose right edge freezes on the last change date looks broken.
- **Branch protection will reject the push.** `github-actions[bot]` cannot be a
  ruleset bypass actor — GitHub's eligible-actor list covers admins, org owners,
  the write and maintain roles, teams, GitHub Apps, and Dependabot, and Actions
  is not on it. So required pull requests, required status checks, or required
  signed commits will each break the daily push. Required signatures are the
  common case on personal repos. The job fails loudly rather than silently
  skipping.

## What the chart means, and what it doesn't

Two kinds of data go into it, drawn differently on purpose.

**Snapshots** (solid line) are measurements: the public star count read at a
real moment and never rewritten afterward. They can show decreases.

**Backfill** (dashed line) is a reconstruction. GitHub returns the accounts that
are starred *today*, grouped by the date each one starred — so everyone who
unstarred has been erased from the past. The reconstructed curve can only go up,
sits below what the count actually was at the time, gets less accurate the
further back it goes, and **changes if you re-run it next year**.

Backfill buys coverage, not accuracy. That's why the seam is visible in the
chart itself rather than only in this file.

Two more honest limits: the line between any two points is interpolation, so a
missed run is drawn as a smooth ramp; and `stargazers_count` is not ground truth
— spam-account purges show up as drops that nobody unstarred for.

## This repo's own chart

<!-- The chart appears here after the first workflow run; see Install, step 3. -->
