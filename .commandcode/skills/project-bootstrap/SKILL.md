---
name: project-bootstrap
description: Choose the tech stack for this repository and scaffold it. Use when the repo is fresh (docs/product.md is unfilled, docs/decisions.md D-001 is pending) or when the user asks to set up, scaffold, bootstrap, initialize, or "start" the project.
license: MIT
metadata:
  template: template-open-source-tool
  version: "1"
---

# Bootstrap the project

The repository ships without a stack on purpose. Your job: turn the user's idea into a chosen
stack, recorded in the docs, scaffolded and verified. Do not write product code before step 5.

## Step 0 — Rename the template (once)

If the repo still says `template-open-source-tool` / "Open Source Tool" anywhere (README,
AGENTS.md, docs, skills), fix that before anything else. The slug is the repository name; the
title is the human name for the tool.

```bash
node scripts/init.mjs --name <repo-slug> --title "<Tool Name>"
```

If the user hasn't named the tool yet, ask — do not invent one. After the rename, re-read
`README.md` and `AGENTS.md` (they now say the real name), delete `scripts/init.mjs`, and continue.

## Step 1 — Get the brief (ask, do not assume)

Ask only the questions whose answers change the design:

- What does the tool do, in one sentence? Who runs it?
- **How do users get it?** Registry (`npm i -g`, `cargo install`, `pipx`, `go install`), release
  binaries, a container, or a script? This decides the language more than taste does.
- Which platforms must it run on? Any single-binary requirement (no runtime installed)?
- Does it need network access, credentials, or a daemon? Long-running or one-shot?
- Is it also a library (importable API), or strictly a CLI?
- Constraints already fixed: language, license, dependencies you refuse, an existing ecosystem to
  fit into?

Write the answers into `docs/product.md` **before** choosing anything (rule 2).

## Step 2 — Choose the smallest stack that fits

- **Distribution first.** A single static binary (Go/Rust/Zig) when users shouldn't install a
  runtime; Node/TypeScript when the audience already has npm; Python when the audience lives in
  Python. Read `references/stack-notes.md` — shapes only, **no versions**.
- Prefer boring, widely-used tooling with a real release process and a maintained community.
- CLI parsing, config, logging: use the ecosystem's standard libraries; do not hand-roll.
- Keep runtime dependencies to a minimum — every one is a supply-chain and packaging liability.
- If two options are genuinely close, say so and let the user pick.
- When the choice is load-bearing, check current practice with a web search — guidance in this
  repo may be old; the search is the check.

## Step 3 — Resolve versions live (mandatory)

**Never write a version from memory, from this skill, from `docs/`, or from anything in
`examples/`.** Packages ship daily; anything you "remember" is wrong.

| Ecosystem | Resolve with |
|---|---|
| npm | `npm view <pkg> version` (and `npm view <pkg> dist-tags` when latest is a prerelease) |
| Rust | `cargo search <crate> --limit 1`, or `cargo add <crate>` and read Cargo.toml |
| Python | `uv add <pkg>` (or `python -m pip index versions <pkg>`) |
| Go | `go list -m -versions <module>@latest` |
| Other | the ecosystem's `add` command, or the registry's API |

Pin exact versions in the lockfile; keep ranges in the manifest. Record the resolved set in the
decision entry (step 6). Prefer the previous stable over an RC/beta unless the user asks.

## Step 4 — Propose, then wait

Present, in one short message:

1. **Shape** — executable/library layout, one line each.
2. **Stack + versions** — language, runtime, CLI/HTTP libraries, test runner, lint/format, build
   tool, package manager.
3. **Distribution** — where users install it from and how CI produces that artifact.
4. **Why** — one line per choice, tied to the brief.
5. **Rejected** — the alternatives and why not (one line each).
6. **Cost/risk** — learning curve, cross-compilation, signing, registry accounts.

Wait for confirmation. Do not scaffold before the user agrees.

## Step 5 — Scaffold

- Create the structure from the proposal (source, tests, packaging).
- Install dependencies; get the tool running end to end for its simplest command (`--help` is a
  real milestone).
- Create and push the `dev` branch, then set it as the GitHub default branch. If repository
  permissions prevent changing the default, tell the user to set it in the repository's GitHub
  settings. Configure branch protection for `dev` and `main` where available.
- Feature work targets `dev` through pull requests. Promote releases with a pull request from
  `dev` to `main` that declares a `patch`, `minor`, or `major` bump and updates the version source
  of truth and changelog.
- Wire the checks: typecheck (if applicable), lint, tests, build — one command each, plus a
  single `check` command that runs them all.
- Add `.github/workflows/ci.yml` running the check command and the build, using current action
  versions (resolve them — same rule as packages).
- Add the release workflow so every merge to `main` validates the declared version and
  automatically publishes or deploys. Release-related workflows must not run for changes to
  `dev`. Create a version tag on the merged `main` commit only if the chosen ecosystem requires
  one. Resolve the workflow and publishing/deployment details for the chosen stack; do not assume
  them before bootstrap.
- If it is a library: make the public API explicit and exported; nothing else is public.
- Do not copy an example project wholesale. Write what this tool needs.

## Step 6 — Record (rule 2)

- `docs/decisions.md` — replace D-001 with the real decision: stack + exact versions +
  distribution + rejected options + why.
- `docs/architecture.md` — shape, components, contracts (commands/flags/output/exit codes),
  invariants.
- `docs/development.md` — prerequisites, setup, and the exact commands (only ones you ran).
- `docs/status.md` — phase 0 complete, phase 1 current, handoff written.

## Step 7 — Verify before declaring done

- Run the check command, the build, and the tool's `--help` yourself.
- Delegate to the `verifier` subagent with the decision entry and `docs/development.md` as
  acceptance criteria. Its report is what "scaffolded" means — not your own summary.
- If verification fails, fix and re-verify. Do not mark the phase complete on a red check.

## Anti-patterns

- Picking a language out of habit when distribution argues otherwise.
- Writing a version you did not resolve live in this session.
- Scaffolding before the user confirmed the choice.
- Adding subcommands, config systems, or abstractions the tool does not need yet.
- Documenting a command you did not run.
- Leaving `docs/decisions.md` at "pending" after scaffolding.
