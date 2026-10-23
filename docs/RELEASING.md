# Preparing release artifacts

The SDK and HTTP MCP server are built and validated together. Release checks run locally
and in CI; publishing packages and creating release tags remain separate manual steps.

## Versions and commit messages

`opendart-sdk` and `opendart-mcp` share version `0.1.0`, recorded in their package manifests
and `cz.toml`. The virtual workspace root's `project.version` is independent. Release tags
use `v<version>`. Both distributions require Python 3.14 or newer.

New commits follow Conventional Commits, for example `feat(sdk): add a disclosure filter`
or `fix(mcp): handle an expired session`. The `commit-msg` hook checks messages against
`cz.toml`; an empty message is allowed so Git can abort a commit. Interactive commits are
available with `uv run --no-sync cz --config cz.toml commit`.

For a later release, update the three release versions together. Commitizen's
[`--version-files-only` mode](https://commitizen-tools.github.io/commitizen/commands/bump/#-version-files-only)
prepares `0.1.1` below without creating a commit or tag:

```bash
uv sync --locked --all-packages --group contracts --group release
uv run --no-sync python scripts/check_release.py
uv run --no-sync cz --config cz.toml bump 0.1.1 --check-consistency --version-files-only --yes
uv lock
uv sync --locked --all-packages --group contracts --group release
uv run --no-sync python scripts/check_release.py --tag v0.1.1
```

Review MCP's SDK dependency when versions change. Its lower bound must include the SDK
features MCP uses; its upper bound excludes the next incompatible minor release while
the packages are pre-1.0. A minor version bump needs a corresponding dependency-range
change. Keep `uv.lock` synchronized with the package manifests, and update `CHANGELOG.md`
and these version examples in the same change. The changelog starts with unreleased work;
historical commits are not presented as published releases.

`check_release.py` verifies the shared version and dependency range. Its optional `--tag`
argument checks a proposed tag string without creating or looking up a Git tag.

## Validate and build

Run from the repository root with Python 3.14, uv, Node.js, and Just installed:

```bash
uv sync --locked --all-packages --group contracts --group release
just check
just release-check
```

Use an empty `dist/` directory, moving aside artifacts from earlier builds first. The
release validator rejects missing, stale, or unrelated artifacts. Build and validate
both distribution formats with:

```bash
just release-build
```

The recipe runs release checks and the following artifact checks:

```bash
uv build --all-packages --no-sources
uv run --no-sync python scripts/check_release.py --dist dist
uv run --no-sync twine check --strict dist/*
.venv/bin/python scripts/smoke_distributions.py --dist dist
```

Disabling workspace source overrides verifies the dependencies that consumers will
resolve from package metadata. Both packages emit core metadata 2.4 for compatibility
with the locked Twine validator. Each wheel and source archive is installed in a temporary
environment, first the SDK alone and then MCP. These checks validate package assets,
exercise the SDK with mocked HTTP responses, and start the installed `opendart-mcp`
command to check HTTP protocol behavior and request security. Dependency installation
uses the package index; the smoke checks make no OpenDART requests and require no API key.

For the current version, the four deliverables are:

```text
opendart_sdk-0.1.0-py3-none-any.whl
opendart_sdk-0.1.0.tar.gz
opendart_mcp-0.1.0-py3-none-any.whl
opendart_mcp-0.1.0.tar.gz
```

## CI and publication

The release job in `.github/workflows/check-release.yml` checks versions and tests the
release helpers when release inputs change. When either package or the release tooling
changes, it also builds distributions, validates metadata with Twine, and runs installation
smoke checks. Draft pull requests skip the build until they are marked ready, and pushes to
`main` skip the job because the pull request already ran it; before tagging, run **CI**
manually on the release commit with **release** and **distributions** selected. It does not publish packages or
create tags.

After reviewing the artifacts, choose the registry and configure package ownership and
publisher credentials before publishing. Publish the SDK before MCP because MCP depends
on it. Create an annotated or signed version tag on the validated release commit as a
separate release step; do not move a tag that has already been distributed.

Pushing the version tag also releases the MCP container image. For tags matching `vX.Y.Z`,
the **Release MCP image** workflow checks that the tag matches the `opendart-mcp` version and
marks a commit on `main`, then finds the image CI published for that commit
(`ghcr.io/orestxherija/opendart-mcp:sha-<full-commit>`). It verifies that image's `main`
signature, rescans it, and adds the `vX.Y.Z` tag to the same digest without rebuilding. It
refuses to move an existing release tag to a different digest. Tag a commit that CI
published; the version bump qualifies because it changes `packages/mcp/pyproject.toml`. If
the tagged commit has no image yet, run **Publish MCP image** on `main` while that commit is
its tip, then rerun the failed release job. See the
[container guide](../packages/mcp/docs/CONTAINER.md#publish-to-ghcr) for tags and pinning.
