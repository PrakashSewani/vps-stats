# Contributing

Thanks for wanting to help. This project is small on purpose — please keep it that way.

## Setup

The stack is chosen when the project starts; the commands that actually work live in
[docs/development.md](./docs/development.md). If that file is still empty, the project has not
been scaffolded yet — see the `project-bootstrap` skill.

## Branches and releases

Generated projects use `dev` as the default integration branch. Start feature branches from
`dev` and target feature-work PRs to `dev`. Release promotion is a PR from `dev` to `main`; declare
the `patch`, `minor`, or `major` version bump and update the version source of truth and changelog.
Every merge to `main` triggers automated publishing or deployment. Release workflows do not run
for changes merged into `dev`.

## Before you open a PR

Run the project's check command (documented in `docs/development.md`) and make sure the build
passes. Include a clear PR title and body explaining the rationale, checks performed, and relevant
documentation or changelog updates. CI runs the same commands.

## What a good PR looks like

- One focused change, described in the PR template.
- Docs updated when behavior changes (`docs/` is the source of truth).
- No new dependencies without a note explaining why.

## Reporting bugs

Open an issue with what you did, what you expected, and what happened — versions included.
Screenshots or logs help.
