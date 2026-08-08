# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue; its **child tickets** are
GitHub sub-issues of it. Everything below stays in issue-number space — `gh`
resolves database ids itself, so no raw `gh api` call is needed.

**Prerequisite, once per repo.** `gh` rejects an unknown label rather than
creating it, so create them before the first map:

```bash
gh label create wayfinder:map --force --description "Wayfinding map"
for t in research prototype grilling task; do
  gh label create "wayfinder:$t" --force
done
```

- **Map**: `gh issue create --label wayfinder:map --title "..." --body "..."`.
  The body holds the Notes / Decisions-so-far / Fog sections.
- **Child ticket**: `gh issue create --parent <map-number> --label wayfinder:<type>`,
  where `<type>` is `research` / `prototype` / `grilling` / `task`. Attach an
  existing issue later with `gh issue edit <number> --parent <map-number>`.
- **Blocking**: `gh issue edit <number> --add-blocked-by <blocker-number>`, or
  `gh issue create --blocked-by <number>,<number>` at creation time. Remove an
  edge with `--remove-blocked-by`.
- **Frontier query**: the map's open children, minus the blocked and the
  claimed. First list the children:

  ```bash
  gh issue view <map-number> --json subIssues \
    --jq '.subIssues.nodes[] | select(.state == "OPEN") | .number'
  ```

  then keep a child only if it survives both filters:

  ```bash
  gh issue view <number> --json number,title,assignees,blockedBy \
    --jq 'select((.assignees | length) == 0)
          | select([.blockedBy.nodes[] | select(.state == "OPEN")] | length == 0)'
  ```

  **`blockedBy.totalCount` counts closed blockers too**, so it cannot answer
  "is this unblocked" — always filter the nodes on `state == "OPEN"`. Take the
  survivors in the order the map body lists them; do not rely on the order the
  API returns them in.
- **Claim**: `gh issue edit <number> --add-assignee @me` — the session's first
  write. It does not fail when someone else has already claimed the ticket, so
  re-read `assignees` straight after and stand down if you are not alone on it.
- **Resolve**: `gh issue comment <number> --body "<answer>"`, then
  `gh issue close <number>`, then record the decision on the map. `gh issue edit
  --body` replaces the whole body, so read the map, append your pointer, and
  write it back as one step — and re-read first if another session may have
  resolved a ticket in the meantime.
