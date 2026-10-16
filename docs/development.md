# Development

> Empty until the stack is chosen. The `project-bootstrap` skill fills this in with the real
> commands — and only commands that were actually run belong here.

## Prerequisites

(What a new contributor installs first.)

## Setup

(Clone, install, configure env — the exact commands.)

## Commands

| Command | What it does |
|---|---|
| (check) | typecheck + lint + tests — the one command that must pass before anything is "done" |
| (test) | — |
| (build) | — |
| (run / dev) | — |

## Environment

(Env vars, where they come from, what happens when they are missing.)

## Branches and pull requests

Generated projects use `dev` as the GitHub default branch and integration branch. Bootstrap must
create and push `dev`, then set it as the repository default; if repository permissions do not
allow the agent to change that setting, it must tell the user how to set it in GitHub. Configure
branch protection for `dev` and `main` where available.

Feature branches start from `dev`. AI agents must not commit directly to `dev` or `main`; they
open a PR for their work targeting `dev`, with a clear title and description, checks performed,
and relevant documentation or changelog updates. Release promotion is a PR from `dev` to `main`
and must declare the version bump (`patch`, `minor`, or `major`) and update the version source of
truth and changelog.

## Releases and deploys

Every merge to `main` is a release. The release workflow runs only after changes reach `main`,
validates the declared version, and automatically publishes or deploys. It creates a version tag
on the merged `main` commit only when required by the selected ecosystem. Changes merged into
`dev` do not run release workflows. The stack-specific workflow and commands are added during
bootstrap.

## Troubleshooting

| Symptom | Fix |
|---|---|
| — | — |
