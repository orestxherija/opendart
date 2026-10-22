# OpenDART MCP

[![CI](https://github.com/orestxherija/opendart/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/orestxherija/opendart/actions/workflows/ci.yml?query=branch%3Amain)
[![codecov](https://codecov.io/github/orestxherija/opendart/branch/main/graph/badge.svg?flag=mcp&token=8TTWOC0RC4)](https://codecov.io/github/orestxherija/opendart)
![Python](https://img.shields.io/badge/python-3.14%2B-blue)
[![code style: Ruff](https://img.shields.io/badge/code%20style-ruff-46a2f1.svg)](https://github.com/astral-sh/ruff)
[![type check: mypy](https://img.shields.io/badge/type%20check-mypy-blueviolet)](https://mypy.readthedocs.io/)

[![Project coverage grid](https://codecov.io/github/orestxherija/opendart/branch/main/graphs/tree.svg?token=8TTWOC0RC4&width=700&height=250)](https://codecov.io/github/orestxherija/opendart)

Local Streamable HTTP server using the [official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/run/).
It exposes one tool, `ping`, which returns `pong` without an API key or network calls.
OpenDART tools will use the async `OpenDart` client from `opendart-sdk`.

## Table of contents

- [Design](#design)
- [Run locally](#run-locally)
- [Connect an MCP client](#connect-an-mcp-client)
- [Docker](#docker)
- [Image metadata](#image-metadata)
- [Publish to GHCR](#publish-to-ghcr)

## Design

![MCP design: local Streamable HTTP service and ping tool, listener settings, Docker deployment, validation, and signed container publishing](docs/architecture.svg)

MCP clients connect to the local `/mcp` endpoint. The server currently registers
only `ping`; it installs the SDK but makes no OpenDART calls. Native execution and
Docker Compose use the same server, with validated listener settings and localhost
Host and Origin checks.

Edit the [draw.io source](docs/architecture.drawio), then export it as SVG to
update [the README diagram](docs/architecture.svg). Keep the source and SVG together.

## Run locally

From the repository root, run locally:

```sh
uv sync --locked --all-packages
uv run --no-sync opendart-mcp
```

`uv run --no-sync python -m opendart_mcp` is equivalent. The server stays running
at `http://127.0.0.1:8000/mcp`. Stop it with Ctrl-C.

The native process binds to `127.0.0.1` by default. Set
`OPENDART_MCP_HTTP__PORT` to choose another port. Settings are validated with
Pydantic and loaded from the process environment at startup; `.env` loading stays
explicit through direnv or Compose's `--env-file` option. An API key is optional
for the current `ping` tool.

In another terminal, verify discovery, legacy initialization, and real HTTP tool calls:

```sh
uv run --no-sync python scripts/check_mcp.py --url http://127.0.0.1:8000/mcp
```

Expected output: `MCP smoke test passed: ping -> pong; hostile Host and Origin rejected`.

Without `--url`, the smoke test starts an isolated native HTTP server on an unused
loopback port and stops it afterward. This is also used in CI.

## Connect an MCP client

Start the native server or container first, then configure an MCP client that
supports Streamable HTTP to connect to `http://127.0.0.1:8000/mcp`. The repository-root
[`.mcp.json`](../../.mcp.json) provides this project connection for clients using
the `mcpServers` format with HTTP entries:

```json
{
  "mcpServers": {
    "opendart": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

The server runs independently of the client. Multiple local clients can connect
to the same running service. Update the URL in `.mcp.json` if you changed the
default port.

## Docker

Local image builds require Docker with BuildKit and Compose v2 or newer, plus a
Docker account to pull the Python base images from `dhi.io`.
[DHI Community images require registry authentication](https://docs.docker.com/dhi/how-to/use/).

1. [Create a Docker account](https://app.docker.com/signup) if needed and verify
   your email address. Use your Docker ID as the registry username.
2. In [Docker Home](https://app.docker.com), open **Account settings → Personal
   access tokens → Generate new token**. Give the token read access to public
   repositories and save it in your password manager. An existing Docker PAT
   with this permission also works. See the
   [Docker PAT guide](https://docs.docker.com/security/access-tokens/personal-access-tokens/).
3. Start Docker and authenticate to the DHI registry:

   ```sh
   docker login dhi.io --username YOUR_DOCKER_ID
   ```

   Paste the Docker PAT at the password prompt. Docker stores the credentials
   through its configured credential store. Keep the PAT out of the repository,
   Dockerfile, build arguments, and application `.env` files.

Lint the Dockerfile with the pinned Hadolint image (Docker required). The hook also
runs before pushes that change the Dockerfile:

```sh
uv run prek run hadolint-docker --all-files --stage pre-push
```

From the repository root, validate the Compose configuration, build
`opendart-mcp:dev`, then start the HTTP service:

```sh
docker compose -f packages/mcp/docker-compose.yml config --quiet
docker compose -f packages/mcp/docker-compose.yml build mcp
docker compose -f packages/mcp/docker-compose.yml up --detach --wait mcp
```

Test the running container through its localhost HTTP endpoint:

```sh
uv run --no-sync python scripts/check_mcp.py --url http://127.0.0.1:8000/mcp
```

Compose publishes `127.0.0.1:8000:8000`, making the service reachable only from
the local machine. Inside the container it binds to `0.0.0.0:8000` so Docker can
forward requests. Localhost Host and Origin checks stay enabled with either bind.
Set `OPENDART_MCP_HTTP__PORT=9000` in your shell to publish `127.0.0.1:9000`
instead; the container's internal port stays `8000`. The native server uses the
same environment variable for its listener port.

The image's health check tests TCP listener readiness; the smoke test additionally
checks the MCP protocol. Compose waits for readiness with `up --wait`, restarts
the service unless explicitly stopped, and leaves it running between client
connections. Manage the service with:

```sh
docker compose -f packages/mcp/docker-compose.yml logs --tail 100 mcp
docker compose -f packages/mcp/docker-compose.yml down
```

To make an API key available for future OpenDART tools, store only its value in a
file outside the source tree or in the ignored root `.secrets/` directory. Set
`OPENDART_API_KEY_FILE` to that file's absolute host path and add the secrets overlay:

```sh
export OPENDART_API_KEY_FILE=/absolute/path/to/opendart-api-key
docker compose -f packages/mcp/docker-compose.yml -f packages/mcp/compose.secrets.yml up --detach --wait mcp
```

Compose mounts the file read-only at `/run/secrets/OPENDART_API__API_KEY`; its
contents are absent from container environment variables and image layers.
The SDK's nested settings source reads and validates it when an authenticated
client is created. The `ping` tool needs no key and does not read it. The base
Compose file runs without the overlay or a key file.

File-backed Compose secrets retain the host file's ownership and permissions.
Ensure UID/GID `10001:10001` can read it: on a Linux host, give the file group
`10001` and mode `0440`. Keep its host directory accessible only to its owner.
The source file remains plaintext on the host; Compose does not encrypt it.
See [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

Native execution still accepts `OPENDART_API__API_KEY`. Compose's explicit
`--env-file` option can load non-secret settings such as the published port or
the secret file path. The build context excludes `.env` variants, secret files,
local virtual environments, and files outside the build allowlist.

The image uses matching Docker Hardened Images for Python 3.14.8 on Alpine 3.24:
`dhi.io/python:3.14.8-alpine3.24-dev` for the builder and
`dhi.io/python:3.14.8-alpine3.24` for the runtime. Both base images and uv 0.11.20
are pinned by version and digest. The builder uses DHI's `/usr/bin/python3.14`,
so the copied virtual environment resolves the same interpreter in the runtime.
See the [DHI Python guide](https://hub.docker.com/hardened-images/catalog/dhi/python/guides).
Dependencies are locked,
installed without development groups, and compiled to bytecode for faster startup.
The builder installs dependencies before copying package source, so source-only
edits reuse the dependency layer. BuildKit caches uv downloads; CI also caches
build layers between runs. See [uv's Docker guidance](https://docs.astral.sh/uv/guides/integration/docker/).

Only the installed runtime environment is copied from the builder. Package code
stays owned by root, and the runtime does not contain uv, the build cache, or the
source checkout. The runtime uses numeric UID/GID `10001:10001` directly because
the DHI runtime has no shell for user-management commands. It retains the packages
provided by the DHI runtime; the Dockerfile does not uninstall pip or delete
bundled libraries. When the Dockerfile changes, CI verifies both DHI bases' signed
SBOM and provenance with Docker's public key before building. CI scans every built
image for secrets, and scans for vulnerabilities when the base images or locked
dependencies change. It blocks fixable high or critical vulnerabilities and detected
secrets, and retains a full vulnerability report including unfixed findings for 30
days. Publishing always runs every check on the exact candidate.

Keep both base-image digests current through the weekly Dependabot Docker
updates; a pinned digest must change to receive base-image fixes. The two DHI
references are grouped in one update. Repository maintainers must configure
[DHI credentials for Actions and Dependabot](../../.github/README.md#docker-hardened-images-credentials).

Compose runs as UID/GID `10001:10001` with a read-only root filesystem, all Linux
capabilities dropped, and privilege escalation disabled. Temporary files use a
16 MiB `/tmp` mount with execution disabled. Limits are one CPU, 256 MiB of memory
with swap disabled, and 64 processes/threads. Adjust these limits in a Compose
override when tools need more resources. Docker's init process forwards signals
and reaps child processes; shutdown has a 10-second grace period. See the
[Compose service reference](https://docs.docker.com/reference/compose-file/services/)
and [tmpfs options](https://docs.docker.com/engine/storage/tmpfs/).

CI exercises these restrictions inside the running image, verifies installed code
is protected and CA certificates exist, and tests loading a synthetic file secret.
The HTTP smoke test also requires hostile Host and Origin requests to be rejected.

The `local` [logging driver](https://docs.docker.com/engine/logging/configure/)
retains service logs with rotation: at most three 10 MiB files. MCP responses
travel over HTTP. The image is built or pulled explicitly, so starting the
service does not fetch a mutable tag. Set `OPENDART_MCP_IMAGE` to use an already
pulled image tag or digest with the same Compose restrictions. Outbound networking
remains available for OpenDART API calls.

## Image metadata

The Dockerfile declares the standard
[OCI image labels](https://github.com/opencontainers/image-spec/blob/main/annotations.md):
title, description, authors, vendor, project URL, documentation URL, source URL,
version, revision, creation time, and licenses. Both CI workflows supply the
package version from `packages/mcp/pyproject.toml`, the source commit, and the
build timestamp. Registry tags identify a build separately from the package version.

Local builds default to package version `0.1.0`. Revision and creation time stay
empty unless supplied. To include them in a Compose build:

```sh
docker compose -f packages/mcp/docker-compose.yml build \
  --build-arg IMAGE_VERSION="$(uv run --no-sync python -c 'from importlib.metadata import version; print(version("opendart-mcp"))')" \
  --build-arg IMAGE_REVISION="$(git rev-parse HEAD)" \
  --build-arg IMAGE_CREATED="$(date -u +%Y-%m-%dT%H:%M:%SZ)" mcp
```

The repository currently declares no project license, so the Dockerfile leaves
the license label empty. `IMAGE_LICENSES` accepts an SPDX license expression when
a license has been selected. Published builds also use any license declared in
the repository's GitHub metadata.

## Publish to GHCR

After pushing the workflow to the repository's default branch, open GitHub
**Actions → MCP container → Run workflow**. The workflow builds a Linux amd64
candidate once, pushes it under `candidate-<run-id>-<attempt>`, and pulls its
immutable digest. It runs protocol and security checks and Trivy scans against
that exact digest. After those pass, it signs and verifies the digest with
[Cosign](https://docs.sigstore.dev/quickstart/quickstart-ci/) and promotes the same
image index to consumer tags without rebuilding. Candidate tags are staging
artifacts and may refer to images that failed checks; use promoted tags or their
verified digests. Local builds support native arm64; publication targets amd64.

Images in `ghcr.io/orestxherija/opendart-mcp` receive `sha-<full-commit>` and
`run-<run-id>-<attempt>` tags. Default-branch runs also update `test`. OCI labels
record the source, revision, and build date. The image includes
[SBOM and provenance attestations](https://docs.docker.com/build/ci/github-actions/attestations/).
The workflow records the verified digest in its summary. Pin consumers to that
digest for an immutable image selection; a commit
tag can be updated when the same commit is rebuilt.
Publishing to GHCR uses the built-in `GITHUB_TOKEN` with `packages: write`.
Building the image also requires the `DHI_USERNAME` and `DHI_TOKEN` repository
secrets described in the [CI setup](../../.github/README.md#docker-hardened-images-credentials).
Machines that only pull and run the published GHCR image do not need DHI
credentials; DHI authentication is needed when building from its base images.

Signing uses GitHub Actions OIDC and the public Sigstore service, with no separate
subscription or signing key secret. The signature records the repository,
publishing workflow, and branch identity in the public transparency log. Verify
a default-branch build before running it (replace `main` if necessary):

```sh
cosign verify ghcr.io/orestxherija/opendart-mcp@sha256:YOUR_DIGEST \
  --certificate-identity=https://github.com/orestxherija/opendart/.github/workflows/mcp-container.yml@refs/heads/main \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com
```

**MCP published image security** runs daily and can also run manually. It resolves
the current `test` tag once, verifies the default-branch publishing identity,
and rescans that digest for vulnerabilities and secrets without rebuilding it.
An optional manual `digest` input audits an older default-branch build. Reports
include unfixed CVEs; fixable HIGH/CRITICAL CVEs and secrets fail the job. Publish
a signed default-branch image once before enabling this daily audit. Updating a
base-image pin or lockfile and publishing again is still required to deliver fixes.

To test the published image on a machine with Docker, authenticate to GHCR if the
package is private, then run:

```sh
export OPENDART_MCP_IMAGE=ghcr.io/orestxherija/opendart-mcp:test
docker pull "$OPENDART_MCP_IMAGE"
docker compose -f packages/mcp/docker-compose.yml up --detach --wait mcp
uv run --no-sync python scripts/check_mcp.py --url http://127.0.0.1:8000/mcp
```

For private packages, use a personal access token (classic) with `read:packages`
when running `docker login ghcr.io --username orestxherija`. New GHCR packages are
private by default; visibility can be changed in the package settings.
See [GitHub's Container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

Use the same localhost client URL for published images. GHCR stores the image;
the HTTP server runs locally with the Compose restrictions when you start it.
