# Star History — Design

Date: 2026-07-25
Status: agreed, not yet implemented

## Problem

Maintainers want a star-history chart in their README. Hosted services
(star-history.com and friends) have historically provided this.

On 2026-06-30 GitHub restricted stargazer timestamps to repository admins and
collaborators. Verified 2026-07-25 with an authenticated token:

    GET /repos/psf/requests/stargazers   (Accept: vnd.github.star+json)  -> 404
    GraphQL stargazers { edges { starredAt } } on psf/requests           -> edges: []
    GET /repos/psf/requests -> "stargazers_count": 54173                 -> still public

Two consequences:

1. Hosted services can no longer read timestamps for repos they do not own.
   A maintainer running the query against their *own* repo is now the only
   path that works. That gap is the reason this project exists.
2. The restricted GraphQL response is an **empty edge list, not an error**.
   Any fetcher must cross-check the returned count against `stargazerCount`
   and abort, or it will silently render a history of zero stars.

## Non-goals

- No AI/LLM anywhere: not at install, not at update, not at render.
- No hosted service, no marketplace Action, no PyPI package.
- No pull-request mode for protected branches. That is a second product.
- No backfill-on-a-schedule. Backfill is a one-time local operation.

## Accuracy: what the two data sources actually mean

**Snapshots** record `stargazers_count` at a real timestamp. This is the
actual metric, measured. It captures decreases. Once written, a point never
changes. Public, unrestricted, works on any repo.

**Backfill** returns *accounts still starred today, grouped by the date they
starred*. Anyone who unstarred is erased from history entirely. Therefore the
reconstructed curve:

- is monotonically increasing by construction and can never show a dip,
- runs below what the count actually was at the time,
- degrades the further back it goes and the more churn the repo has had,
- **changes retroactively** — re-running backfill next year rewrites 2019.

Backfill buys *coverage*, not accuracy. It is a reconstruction; snapshots are
a record. The two must stay distinguishable in the data (`src` field) so a
reconstruction is never presented as a measurement.

Architecturally: **backfill once locally under the maintainer's own
credentials, then only ever append public aggregate counts from CI.** This is
the only design that still works after the API restriction.

## Layout

Two files a user copies; one directory the tool owns.

    star_history.py                        # copy #1 - stdlib only, single file
    .github/workflows/star-history.yml     # copy #2 - edit nothing
    .github/star-history/history.json      # generated: the record
    .github/star-history/light.svg         # generated
    .github/star-history/dark.svg          # generated

The repo slug comes from `$GITHUB_REPOSITORY`. No placeholder substitution and
no bootstrapper — that absence is what removes the ~2,400-line materialization
layer the reference implementation needed.

## Subcommands

- **`update`** — the daily path. One public API call for `stargazers_count`,
  append a point, render both SVGs. No timestamps, so it works on any repo
  forever.
- **`backfill`** — one-time, local, owner-only. GraphQL `starredAt`,
  paginated DESC. Refuses to run twice without `--force`. Only fills dates
  *before* the earliest snapshot, so it can never overwrite a measurement.
  Aborts if the returned edge count disagrees with `stargazerCount`.
- **`snippet`** — prints the README block with the correct repo slug in the
  alt text. Accepts `--branch` for orphan-branch mode.
- **`--selfcheck`** — assert-based, no framework. The one runnable check.

## Data format

```json
{"repo": "owner/name",
 "points": [{"date": "2019-03-02", "stars": 41,   "src": "backfill"},
            {"date": "2026-07-25", "stars": 3011, "src": "snapshot"}]}
```

**A point is appended only when the count changes.** A flat segment between
two points renders identically to a hundred daily points, so unchanged days
are skipped. Quiet repos produce zero commits, and `git log` is not polluted
by a daily bot commit forever. This also keeps `history.json` small.

## Rendering

Clean style. No hand-drawn/xkcd aesthetic, no embedded font.

- **Two SVGs, transparent background.** Only axis, text, and grid color differ
  between them. The line keeps one red-orange accent that reads on both.
- **System font stack.** Not a named font that resolves to nothing — the
  reference sets `font-family="xkcd"` with no fallback and no `@font-face`, so
  it silently renders in the browser default on every viewer's machine.
- **800x400 viewBox**, plain polyline, round Y ticks, month labels on X,
  legend chip with the repo slug.
- **No spline.** At one point per day a polyline is already visually smooth
  (~8px segments across the plot). Monotone-X interpolation only earns its
  keep on sparse data; the reference spends 67 lines on it.
- **Downsample to ~400 points** at render time. A 10-year repo is ~3,650
  points otherwise.
- `role="img"` plus `<title>`/`<desc>` for screen readers.
- No scripts, no external URLs, no `foreignObject`. GitHub sanitizes SVG and
  this keeps the output trivially safe to commit.
- Deterministic: same `history.json` -> identical bytes, so no-change days
  produce no diff.

### Attribution

An SVG loaded via `<img>` cannot have working links, and GitHub renders README
images that way. So attribution splits in two:

- Inside each SVG, bottom-right: `github.com/Ovid/star-history` as small muted
  text. No logo, no clickable element.
- Outside, in the README block: a real link to
  <https://github.com/Ovid/star-history>.

Do not reproduce the `star-history.com` watermark or logo.

### README block

```html
<a href="https://github.com/Ovid/star-history">
  <picture>
    <source media="(prefers-color-scheme: dark)"  srcset=".github/star-history/dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/star-history/light.svg">
    <img alt="Star history for OWNER/REPO" src=".github/star-history/light.svg" width="800">
  </picture>
</a>
```

`<picture>` with two sources is GitHub's documented dark-mode mechanism.
Deliberately not attempting `prefers-color-scheme` inside a single SVG.

## Workflow

```yaml
name: star-history
on:
  schedule: [{cron: "17 3 * * *"}]      # daily; smoothness depends on it
  workflow_dispatch:
permissions: {contents: write}
concurrency: {group: star-history}
jobs:
  update:
    if: github.event.repository.fork == false
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 star_history.py update
        env: {GITHUB_TOKEN: "${{ github.token }}"}
      - run: |
          git diff --quiet .github/star-history || {
            git config user.name  "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git commit -am "chore: update star history" && git push
          }
```

Notes:

- **Daily is required.** Post-backfill points arrive one per scheduled run.
  Weekly gives ~55px segments and a visible kink at the seam where backfill
  ends.
- **`actions/checkout@v4` is used deliberately.** The reference forbids all
  `uses:` and hand-rolls a credential-free `git init` + fetch. That made sense
  for code audited line-by-line in one repo; for a tool strangers install, a
  300-line bespoke checkout reads as more alarming, not less.
- No `setup-python`; `ubuntu-latest` ships 3.12.
- `if: fork == false` keeps forks inert without pinning a repo slug.
- `GITHUB_TOKEN` is passed to the fetch to avoid shared-runner rate limits on
  the unauthenticated 60/hr per-IP budget.

## Branch protection

Researched 2026-07-25. **`github-actions[bot]` cannot be a ruleset bypass
actor.** GitHub's docs list eligible bypass actors as repository admins, org
and enterprise owners, the write/maintain roles, teams, GitHub Apps, and
Dependabot. Actions is excluded by design; GitHub's stated reasoning is that
allowing it would let any collaborator push anywhere by authoring a workflow.

So on a repo with required pull requests or required status checks, the push
in the workflow above fails.

Handling, in order:

1. **Usually not applicable.** The target audience is individual maintainers,
   most of whom have no branch protection on personal repos. Default path
   works.
2. **Orphan-branch mode** (documented escape hatch). Commit the generated
   files to a dedicated `star-history` branch; the README uses absolute
   `raw.githubusercontent.com` URLs, emitted by `snippet --branch
   star-history`. The default branch is never written to, so protection is
   irrelevant and `main`'s history stays completely clean. Cost: absolute URLs
   and GitHub's camo image proxy may serve a stale chart for a while.
3. **GitHub App + `actions/create-github-app-token` + ruleset bypass.** The de
   facto standard, but requires an app registration, a private key secret, and
   a third-party action. Document only; do not build.
4. **Pull-request mode.** Refused. Second product.

**The tool must fail loudly** with a message naming branch protection and
pointing at option 2. It must not silently swallow a rejected push.

## Costs stated plainly in the README

- `contents: write` is unavoidable. The README needs a committed file.
- Branch protection may reject the push; see above.
- Backfill requires write/maintain/admin on the repo and a `gh` session. It is
  optional; snapshot-only works without it.

## Deliberate omissions

Against the ~4,900-line reference implementation, these are dropped on
purpose: the bootstrapper and its templates, the skill wrapper and its prose
references, the packaging validator, SVG self-validation of
program-generated SVG, JSON self-validation of program-written JSON,
path-traversal defense around hardcoded relative constants, hand-rolled
PNG/JPEG header parsing for an embedded avatar, the snapshot-interval
machinery that `--force` bypasses everywhere, and the `initialize` subcommand
that the reference itself forbids running.

## Open items for implementation

- Exact SVG geometry (margins, tick counts, legend placement).
- Backfill pagination retry: a single unstar mid-run can invalidate a
  consistency check on a large active repo. Retry rather than fail hard.
- Whether this repo dogfoods its own chart in its README. It should.
