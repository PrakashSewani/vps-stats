# Stack notes — guidance, not gospel

Qualitative shapes for open-source tools. **No versions here on purpose** — resolve versions
live (see the skill's step 3), and verify current practice with a search when the choice matters.

## The decision that matters most: distribution

| How users install it | What that implies |
|---|---|
| `npm i -g` / `npx` | TypeScript/Node; keep the dependency tree small; publishing is a registry release |
| `cargo install` / release binaries | Rust; single static binary; cross-compilation is part of the release work |
| `go install` / release binaries | Go; trivial cross-compilation; no runtime needed |
| `pipx` / `uv tool` | Python; declare an entry point; pin for reproducibility |
| Container image | Any language; image size and CVE surface become the product's problem |
| A script users curl | Keep it dependency-free and auditable; signing/checksums matter |

If users cannot install it in one familiar command, the tool is not shippable regardless of how
good the code is.

## CLI shape

- One executable, subcommands over multiple binaries.
- `--help` is documentation; make it honest and current.
- stdout is for data, stderr for logs. `--json` for machine output; keep it stable once shipped.
- Exit codes are a contract: 0 success, non-zero failure, distinct codes for distinct failures.
- Config: flags first, then env vars, then a config file — document the precedence.

## Library shape

- The public API is the product: small, explicit exports; everything else internal.
- Version honestly (semver); breaking changes get a major bump and a migration note.
- Ship types/signatures alongside the code.
- Prefer zero runtime dependencies; each one is a supply-chain liability.

## Testing and quality

- Unit tests for logic; one integration test that runs the real thing end to end (spawn the
  binary / call the entry point).
- Test the error paths and the `--help` output — they are what users see first.
- One `check` command that runs everything; CI runs exactly it.

## Release hygiene

- The version lives in one manifest; the release promotion PR from `dev` to `main` declares the
  bump and updates the changelog.
- Merging the promotion PR to `main` triggers the automated release workflow. Create a matching
  `v<version>` tag on that commit only when the selected ecosystem requires one.
- Scope publishing credentials narrowly. Add checksums/signatures if users download binaries,
  and provenance if the registry supports it.

## Always

- Resolve versions live. Never copy a version out of this file, `docs/`, or a blog post.
- Two similar modules beat one premature abstraction; three is when you extract.
- The README and `--help` are part of the product; keep them true.
