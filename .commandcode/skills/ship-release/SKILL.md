---
name: ship-release
description: Prepare and verify this project's release. Use when the user asks to release, ship, publish, or deploy. The main-branch workflow publishes or deploys automatically; this skill is filled in with the project's real procedure at bootstrap time.
license: MIT
metadata:
  template: template-open-source-tool
  version: "1"
---

# Ship a release

## Rules (always)

- **Version source of truth:** the manifest of the chosen stack. A release promotion PR from
  `dev` to `main` declares a `patch`, `minor`, or `major` bump and updates the manifest and
  changelog.
- **Every merge to `main` is a release:** the release workflow validates the declared version
  and automatically publishes or deploys. Release-related workflows do not run for changes to
  `dev`.
- Create a `v<version>` tag on the merged `main` commit only when the chosen ecosystem requires
  one; if created, it must match the version source of truth.
- **Record the real procedure here** when the stack is chosen (see "Procedure" below), including
  how to verify and recover from a failed release.

## Procedure — NOT YET FILLED IN

The stack has not been chosen yet (`docs/decisions.md`, D-001). At bootstrap:

1. Replace this section with the exact steps for the chosen stack: update the version and
  changelog, run checks, and open the `dev`-to-`main` release promotion PR.
2. Document how the main-branch workflow publishes or deploys automatically, and how to verify
  its result. Include a version tag only if the ecosystem requires one.
3. Add the recovery path for a failed or bad release.
4. Do not invent stack-specific commands before bootstrap; only commands that were actually run
  belong here.

## Skeleton to adapt

```text
1. Declare a patch, minor, or major bump; update <manifest> and the CHANGELOG.
2. Run the project's check command (docs/development.md) and the build.
3. Open a release promotion PR from dev to main.
4. After merge, verify the automatic publish or deployment. Create a matching version tag on
   that main commit only if the ecosystem requires one.
5. Verify from a clean install or deployment check: <the stack-specific verification>.
```
