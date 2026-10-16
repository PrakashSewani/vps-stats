# Architecture

> Empty until the stack is chosen. The `project-bootstrap` skill fills this in as part of
> scaffolding, together with `docs/decisions.md` (D-001) and `docs/development.md`.

## Shape

The package/executable, how it is built, and how it is distributed (registry, release binaries,
container). One line per artifact.

## Components

| Piece | Where | Responsibility |
|---|---|---|
| (entry point) | — | — |
| (core) | — | — |
| (tests) | — | — |

## Contracts

What users depend on and therefore what is versioned:

- Commands / flags / output formats (stdout for humans, `--json` for machines, exit codes).
- Public API surface, if it is a library.
- Configuration files or environment variables.

## Boundaries and invariants

The rules code must not break: no secrets in output, deterministic behavior, dependency policy,
performance envelope.
