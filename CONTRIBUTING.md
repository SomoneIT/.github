# Contributing

Thanks for taking the time to contribute.

## Reporting issues

Use the issue templates to report a bug or propose a feature. Search existing
issues first to avoid duplicates. Report security problems privately, see
[SECURITY.md](SECURITY.md).

## Pull requests

1. Fork the repository or create a branch from the default branch.
2. Keep each pull request focused on one change.
3. Add or update tests and documentation when behavior changes.
4. Make sure the CI checks pass.
5. Fill in the pull request template and request a review.

Never push directly to the default branch.

## Commit messages

Write short, imperative commit messages that explain the change
(for example "Add retry limit to auto-fix workflow").

## Workflows

Workflows should follow least privilege: pin actions to commit SHAs, declare
minimal `permissions`, set `timeout-minutes`, use `persist-credentials: false`
on checkout and pass untrusted values through `env:` only.
