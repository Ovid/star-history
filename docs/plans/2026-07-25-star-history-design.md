# Star History — Design

Date: 2026-07-25
Status: agreed; revised after adversarial review

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
   Any fetcher must cross-check the returned edge count against
   `stargazerCount` and abort, or it will silently render a history of zero
   stars.

## Non-goals

- No AI/LLM anywhere: not at install, not at update, not at render.
- No hosted service, no marketplace Action, no PyPI package.
- No pull-request mode for protected branches. That is a second product.
- No backfill-on-a-schedule. Backfill is a one-time local operation.

## Accuracy: what the two data sources mean

**Snapshots** record `stargazers_count` at a real timestamp. Public,
unrestricted, works on any repo, captures decreases, and once written a point
is never rewritten.

**Backfill** returns *accounts still starred today, grouped by the date they
starred*. Anyone who unstarred is erased from history entirely. Therefore the
reconstructed curve:

- is monotonically increasing by construction and can never show a dip,
- runs below what the count actually was at the time,
- degrades the further back it goes and the more churn the repo has had,
- **changes retroactively** — re-running backfill next year rewrites 2019.

Backfill buys *coverage*, not accuracy. It is a reconstruction; snapshots are
a record.

**Where the snapshot path also lies**, stated here rather than left implied:

- **The line between two points is interpolation.** A missed run, a disabled
  workflow, or a delayed cron leaves a gap the polyline draws as a straight
  ramp — indistinguishable from measured segments. The same sin backfill is
  convicted of, at smaller scale.
- **`stargazers_count` is not ground truth.** Spam-account purges produce
  drops that are not unstars, and the number is served from a cache.
- **Deleting `history.json`, squashing, or force-pushing** truncates the
  record silently. Nothing detects it.
- **All dates are UTC**, including on a local `backfill` run.

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

**Slug resolution.** `$GITHUB_REPOSITORY` exists only in CI, so it covers
`update` and nothing else. `backfill` and `snippet` run locally, where it is
unset. Resolution order, ~10 lines: `--repo` flag, then `$GITHUB_REPOSITORY`,
then parse `git remote get-url origin`. There is still no bootstrapper and no
placeholder substitution — that absence is what removes the reference
implementation's ~2,400-line materialization layer.

A repo rename or transfer leaves `repo` in `history.json` stale. `update`
warns and rewrites it; it does not discard the history.

## Subcommands

- **`update`** — the CI path. One public API call for `stargazers_count`,
  append a point, render both SVGs. No timestamps, so it works on any repo
  forever.
- **`backfill`** — one-time, local, owner-only. GraphQL `starredAt`,
  paginated DESC. Token from `$GITHUB_TOKEN`, falling back to `gh auth token`
  via subprocess. Refuses to run twice without `--force`. Only fills dates
  *before* the earliest snapshot, so it can never overwrite a measurement.
  Aborts if the returned edge count disagrees with `stargazerCount`.
- **`snippet`** — prints the README block. **Refuses to print until
  `history.json` exists**, so nobody pastes a block pointing at files that
  aren't there yet.
- **`--selfcheck`** — assert-based, no framework. The one runnable check.

## Data format

```json
{"repo": "owner/name",
 "points": [{"date": "2019-03-02", "stars": 41,   "src": "backfill"},
            {"date": "2026-07-25", "stars": 3011, "src": "snapshot"}]}
```

**A point is written on every run, deduped by UTC date** — if the last point
already carries today's date, replace it in place.

An earlier draft appended only when the count *changed*, to avoid a daily bot
commit. That was wrong in three ways: a quiet repo's history stays at one
point and a one-vertex polyline renders nothing (and divides by zero on the
x-scale); the chart's right edge freezes at the last change date, so a reader
sees a chart that appears to have died in March; and GitHub **automatically
disables scheduled workflows in a public repo after 60 days with no repository
activity**, so the optimization breaks exactly the quiet repos it was meant to
help. Popular repos — the actual audience — gain stars most days and would get
a daily commit regardless. The saving was illusory in both directions.

The cost is one bot commit per day. Stated plainly in the README rather than
engineered around. (Whether a bot commit resets the 60-day timer is
undocumented; if GitHub disables the workflow, re-enable it in the Actions
tab.)

## Rendering

Clean style. No hand-drawn/xkcd aesthetic, no embedded font.

- **Two SVGs.** Only axis, text, and grid color differ. The line keeps one
  red-orange accent that reads on both. `light.svg` gets an opaque near-white
  background so it stays legible where `<picture>` is stripped and everything
  falls back to the light source (npmjs.com, mirrors, feed readers).
- **System font stack.** Not a named font that resolves to nothing — the
  reference sets `font-family="xkcd"` with no fallback and no `@font-face`, so
  it silently renders in the browser default on every viewer's machine.
- **800x400 viewBox**, plain polyline, round Y ticks, month labels on X,
  legend chip with the repo slug.
- **No spline.** At daily resolution a polyline is already visually smooth
  (~8px segments). Monotone-X interpolation only earns its keep on sparse
  data; the reference spends 67 lines on it.
- **No downsampling.** Measured: a 3,650-point polyline is 42 KiB raw, 13 KiB
  gzipped, and **2 KiB gzipped with integer coordinates** — which we want
  anyway for byte-determinism. Even-spaced sampling would also delete exactly
  the spikes and dips the accuracy argument is built on. If a limit is ever
  needed, bucket by integer x-pixel keeping min and max y per column; never
  even-spacing.
- **The backfill/snapshot seam is rendered**, not just recorded: backfilled
  segments are drawn with `stroke-dasharray`, with a one-word legend note.
  The `src` field exists to drive this. Without it, the SVG — the artifact
  every reader actually sees — would present a reconstruction as a
  measurement while the design doc claimed otherwise.
- No scripts, no external URLs, no `foreignObject`. GitHub sanitizes SVG and
  this keeps the output trivially safe to commit.
- Deterministic: same `history.json` -> identical bytes.

### Accessibility

An SVG loaded through `<img>` is an opaque image; its internal DOM never
reaches the accessibility tree. `<title>` and `<desc>` inside the SVG are
therefore **inert on GitHub**, and `alt` is the entire accessibility surface.
So the substance goes in `alt`, generated by `snippet`:

    alt="Star history for OWNER/REPO: 3,011 stars as of 2026-07-25"

`<title>`/`<desc>` are still emitted — they cost two lines and do work when
the SVG is opened directly — but they are not the a11y story.

### Attribution

Links inside an `<img>`-loaded SVG are dead for the same reason, so
attribution splits in two:

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
    <img alt="Star history for OWNER/REPO: N stars as of YYYY-MM-DD"
         src=".github/star-history/light.svg" width="800">
  </picture>
</a>
```

Verified against live GitHub rendering: relative `srcset` paths in `<source>`
are rewritten, `<a>` wrapping `<picture>` works, and GitHub wraps the result
in a `<themed-picture>` custom element so it follows the viewer's GitHub theme
setting rather than only OS `prefers-color-scheme`.

## Workflow

```yaml
name: star-history
on:
  schedule: [{cron: "17 3 * * *"}]
  push: {paths: ['.github/workflows/star-history.yml']}   # first run on install
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

The commit step is written as one command per line on purpose. Verified
locally:

- `git diff --quiet <path>` returns **0 for untracked files** — generated
  files are invisible to it until something stages them. An earlier draft used
  it as the change guard, so the workflow would have committed nothing on
  every run, forever, while showing a green checkmark.
- `git commit -am` stages *tracked, modified* files only (exit 1 on untracked
  input) and sweeps unrelated tracked files when it does run.
- GitHub's default shell is `bash -e` with no pipefail, and `set -e` **exempts
  a failure in the non-final position of an `&&` list**: `false || { false &&
  echo x; }` exits 0. A chained `commit && push` therefore swallows a failed
  commit — signing config, hooks, nothing staged — silently.

`git add -A <path>` + `git diff --cached --quiet` + separate lines fixes all
three, and a failed commit or push now fails the job.

Other notes:

- **No fork guard.** GitHub disables scheduled workflows on forks by default,
  so the guard was redundant. Worse, `github.event.repository` is not
  guaranteed present for `schedule` (the reference docs still list the
  schedule payload as "Not applicable"), and GitHub's `==` coerces `null` and
  `false` both to `0`, so `fork == false` would evaluate **true** on a missing
  payload — failing open, not closed.
- **`actions/checkout@v4` is used deliberately.** The reference forbids all
  `uses:` and hand-rolls a credential-free `git init` + fetch. That made sense
  for code audited line-by-line in one repo; for a tool strangers install, a
  300-line bespoke checkout reads as more alarming, not less.
- No `setup-python`; `ubuntu-latest` is Ubuntu 24.04 with Python 3.12.3.
- `GITHUB_TOKEN` is passed to the fetch: 1,000 req/hr per repository, versus
  60/hr per IP unauthenticated on shared runners. One call/day either way.
- **Push race:** the concurrency group serializes this workflow against itself
  but not against humans. A push landing between checkout and push fails the
  job loudly with no retry. Acceptable for a daily job; not worth building for.

## Error handling in `update`

Not omitted — this is the one path that can corrupt a permanent record:

- `timeout=20` on the request, and a read cap so a hung server cannot stall a
  runner for six hours.
- Fail the step on any non-200 rather than appending a garbage point.
- Write `history.json.tmp` then `os.replace` — atomic, so an interrupted run
  cannot leave a truncated record.
- Dedupe by UTC date: `workflow_dispatch` plus cron, or a cron delayed across
  midnight, will otherwise produce two points for one day.

~7 lines total.

## Branch protection

Researched 2026-07-25. **`github-actions[bot]` cannot be a ruleset bypass
actor.** GitHub's docs list eligible bypass actors as repository admins, org
and enterprise owners, the write/maintain roles, teams, GitHub Apps, and
Dependabot. Actions is absent.

So the push fails on a repo with:

- required pull requests,
- required status checks, or
- **required signed commits** — more common on personal repos than the other
  two, and an unsigned push from the runner is rejected.

Handling, in order:

1. **Usually not applicable.** Most personal repos have no branch protection.
2. **Required-signatures only:** commit through the Contents REST API instead
   of `git push`. GitHub signs those server-side, producing a *verified*
   commit. Does not help with required PRs or status checks.
3. **Orphan-branch mode — deferred, not designed.** Committing to a dedicated
   `star-history` branch would sidestep protection entirely and keep `main`'s
   log clean. But it is a second implementation, not a documented escape
   hatch: the workflow must check out the default branch (that's where
   `star_history.py` lives) while committing to another, `update` must read
   its prior state from a branch it isn't on, and the raw URLs 404 until the
   first successful push. Correcting an earlier draft: camo is *not* the
   problem — verified that GitHub does **not** proxy raw.githubusercontent
   URLs in READMEs (`cache-control: max-age=300`, so ~5 minutes of staleness,
   versus the one-year immutable TTL on genuine camo assets).
4. **GitHub App + `actions/create-github-app-token` + ruleset bypass.** The de
   facto standard, but needs an app registration, a private key secret, and a
   third-party action. Document only.
5. **Pull-request mode.** Refused. Second product.

**The tool must fail loudly** and name branch protection in the message.

## Costs stated plainly in the README

- `contents: write` is unavoidable. The README needs a committed file.
- One bot commit per day.
- Branch protection may reject the push; see above.
- Backfill needs write/maintain/admin plus a `gh` session. Optional —
  snapshot-only works without it.
- The chart appears on the first workflow run, which the `push:` trigger fires
  as soon as the workflow file is committed. Run `snippet` after that.

## Deliberate omissions

Against the ~4,900-line reference implementation, dropped on purpose: the
bootstrapper and its templates, the skill wrapper and its prose references,
the packaging validator, SVG self-validation of program-generated SVG, JSON
self-validation of program-written JSON, path-traversal defense around
hardcoded relative constants, hand-rolled PNG/JPEG header parsing for an
embedded avatar, the snapshot-interval machinery that `--force` bypasses
everywhere, and the `initialize` subcommand the reference itself forbids
running.

Explicitly *not* omitted, because they are load-bearing rather than
ceremonial: request timeout and read cap, atomic write, non-200 handling, and
the GraphQL edge-count cross-check.

## Open items for implementation

- Exact SVG geometry (margins, tick counts, legend placement).
- Backfill pagination retry: a single unstar mid-run can invalidate the
  consistency check on a large active repo. Retry rather than fail hard.
- This repo should dogfood its own chart in its README.

## Review history

Revised 2026-07-25 after an adversarial review that found the original
workflow YAML committed nothing on every run while reporting success. Every
claim in the original that had been checked against a real system held up;
every claim reasoned about only in prose — the git commands, the fork guard's
failure direction, the purpose of the `src` field, the need for downsampling —
was wrong. Run the machinery before writing it down.
