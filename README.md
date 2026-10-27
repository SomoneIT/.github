# SomoneIT/.github

Organization base repository: reusable workflows, shared scripts, workflow
templates and community health files (security policy, contributing guide,
issue and pull request templates) used as defaults by the repositories of the
organization.

## Reusable workflows

Call them from `.github/workflows/` of a repository:

```yaml
jobs:
  lint:
    uses: SomoneIT/.github/.github/workflows/python-lint.yml@main
```

**Recommendation:** pin to a commit SHA or a tag instead of `@main`, for
example `...python-lint.yml@<sha> # v1`, and update deliberately.

Workflows that need scripts (`copilot-pr-auto-fix`, `eol-check`, `dast`) check out
`SomoneIT/.github` at the input `scripts-ref` (default `main`) into `.org-github`.
Pin `scripts-ref` together with the workflow ref.

Triggers such as `workflow_run`, `pull_request_target` and `schedule` cannot live
in a reusable workflow: the caller owns them (see [Templates](#workflow-templates)).

| Workflow | Inputs (default) | Secrets |
| --- | --- | --- |
| `build-image.yml` | `image-org`\*, `image-name`\*, `image-version`\*, `dockerhub-username`\*, `context-path` (`.`), `dockerfile-path` (`./Dockerfile`), `update-version-file` (`false`), `build-args` (empty, newline-separated `KEY=value`) | `dockerhub-token`\* |
| `python-lint.yml` | `working-directory` (`.`), `python-version` (`3.x`) | none |
| `copilot-lessons-on-merge.yml` | `base-branch` (empty: `vars.DEFAULT_BRANCH`, then the repository default branch) | `COPILOT_AGENT_TOKEN` (optional) |
| `copilot-pr-auto-fix.yml` | `ci-workflow-name`\*, `autofix-limit` (`3`), `scripts-ref` (`main`) | `COPILOT_AGENT_TOKEN` (optional) |
| `eol-check.yml` | `python-lock`, `python-project`, `npm-lock`, `npm-package-json`, `cargo-lock`, `cargo-toml`, `first-party-prefixes` (newline-separated), `ignore-file`, `warn-days` (`90`), `assignee` (empty: none), `python-version` (`3.12`), `scripts-ref` (`main`) | `COPILOT_AGENT_TOKEN` (optional) |
| `backport.yml` | `policy-repo` (empty: no label suggestions), `policy-path` (`docs/support-policy.json`), `policy-ref` (`main`), `release-branch-prefix` (`releases/v`) | `COPILOT_AGENT_TOKEN` (optional), `BACKPORT_TOKEN` (required only when a `backport/<version>` label is requested) |
| `dast.yml` | `context-filename` (`zap.context`), `rules-file` (`.zap/rules.tsv`), `environment` (`staging`), `allowed-hosts`, `zap-image`, `scripts-ref` (`main`) | `DAST_CONTEXT_B64`\*, `DAST_USERNAME`\* |

\* required. Secrets are passed explicitly by the caller.

`build-image.yml` and `python-lint.yml` are called with `@main` by existing
repositories: their existing inputs, defaults and secret names must not change,
only optional inputs may be added.

The backport support policy is a JSON file such as `{"supported_versions": ["1.2", "1.1"]}`.
Backports target `<release-branch-prefix><version>` for each `backport/<version>` label.

## Workflow templates

`workflow-templates/` contains thin caller workflows (with matching
`*.properties.json`) that own the triggers and call the reusable workflows:
python-lint, build-image, copilot-lessons-on-merge, copilot-pr-auto-fix,
eol-check (Python, TypeScript, Rust), backport and dast. In a repository, use
**Actions → New workflow** and pick the template, or copy the file.

## Shared scripts

`scripts/` holds `check_eol.py`, `copilot_autofix_limit.py` and `check_dast_target.py`.
Run the tests with:

```sh
python -m unittest discover -s scripts/tests
```

## Required organization setup

- Secrets: `COPILOT_AGENT_TOKEN`, `BACKPORT_TOKEN`, `DOCKERHUB_TOKEN`
- Variables: `DEFAULT_BRANCH` (default branch name), `DOCKER_USERNAME`
