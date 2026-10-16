# Open Source Tool

A repository template for an open-source **CLI, library, or small service** — docs, agent rules,
subagents, and a release-shaped skeleton. No tech stack is baked in: the stack is chosen when the
tool's requirements are known.

## Getting started

1. **Create the repo** — "Use this template → Create a new repository" on GitHub, or locally:

   ```powershell
   .\scripts\new-project.ps1 -Template template-open-source-tool -Name my-tool -Title "My Tool"
   ```

   ```bash
   bash scripts/new-project.sh template-open-source-tool my-tool "My Tool"
   ```

2. **Rename** (skip if you used the script above):

   ```bash
   node scripts/init.mjs --name my-tool --title "My Tool"
   ```

3. **Bootstrap it.** Open an AI session in the repo, describe the tool in plain words, then say
   *"bootstrap this project"*. The agent follows `AGENTS.md` and the `project-bootstrap` skill:
   it asks the questions that matter, picks the smallest stack that fits, resolves current
   package versions **live**, records the decision in `docs/`, and scaffolds the repo with checks,
   CI, and the release path.

## Branches and releases

Generated projects use `dev` as the GitHub default branch. Feature work goes through pull requests
into `dev`; a release is promoted by a `dev`-to-`main` pull request declaring the version bump and
updating the version and changelog. Every merge to `main` automatically publishes or deploys;
release workflows do not run for `dev` changes. Bootstrap configures the stack-specific workflow
for this behavior. A version tag is created on the merged `main` commit only when the chosen
ecosystem requires one.

## What's in here

- `AGENTS.md` — the four rules, the PM/subagent model, and the no-stack-assumed workflow.
- `docs/` — `product.md` (the brief), `architecture.md`, `decisions.md`, `status.md`,
  `development.md`.
- `.commandcode/agents/` — `implementer`, `verifier`, `docs-writer`.
- `.commandcode/skills/` — `project-bootstrap` (choose + scaffold the stack), `ship-release`.
- `scripts/init.mjs` — renames the template once; delete it after.

## Why nothing is pinned

Templates that ship a pinned stack go stale in weeks and force yesterday's tools onto today's
project. This template ships the **shape** — docs-first, PM + subagents, one check command, and a
documented release-on-`main` policy. Bootstrap creates the stack-specific release workflow and
leaves the stack to be decided with you at project start, with versions resolved on that day.

## License

[MIT](./LICENSE)
