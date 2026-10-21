# OpenDART MCP

Local Streamable HTTP server using the [official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/run/).
It exposes one tool, `ping`, which returns `pong` without an API key or network calls.
OpenDART tools will use the async `OpenDart` client from `opendart-sdk`.

## Table of contents

- [Run locally](#run-locally)
- [Connect an MCP client](#connect-an-mcp-client)
- [Docker](#docker)
- [Image metadata](#image-metadata)
- [Publish to GHCR](#publish-to-ghcr)

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

Expected output: `MCP smoke test passed: ping -> pong`.

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

Lint the Dockerfile with the pinned Hadolint image (Docker required):

```sh
uv run prek run hadolint-docker --all-files
```

Use Docker with BuildKit and Compose v2 or newer. From the repository root, validate the
Compose configuration, build `opendart-mcp:dev`, then start the HTTP service:

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

Compose forwards `OPENDART_API__API_KEY` from your shell. To load the root `.env`
file explicitly, use [Compose's `--env-file` option](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/):

```sh
docker compose --env-file .env -f packages/mcp/docker-compose.yml up --detach --wait mcp
```

The `ping` tool does not require a key; add one when implementing OpenDART tools.
The build context excludes `.env`, local virtual environments, and other files
outside the package sources and workspace manifests.

The image pins Python 3.14.8 on Debian Trixie slim and uv 0.11.20 by version and
digest. The [official Python image](https://github.com/docker-library/python/blob/master/3.14/slim-trixie/Dockerfile)
already builds CPython with PGO and LTO on amd64 and arm64. Dependencies are locked,
installed without development groups, and compiled to bytecode for faster startup.
The builder installs dependencies before copying package source, so source-only
edits reuse the dependency layer. BuildKit caches uv downloads; CI also caches
build layers between runs. See [uv's Docker guidance](https://docs.astral.sh/uv/guides/integration/docker/).

Only the installed runtime environment is copied from the builder. Package code
stays owned by root, and the runtime does not contain uv, the build cache, or the
source checkout. Keep the base-image digest current through the existing weekly
Dependabot Docker updates; a pinned digest must change to receive base-image fixes.

Compose runs as UID/GID `10001:10001` with a read-only root filesystem, all Linux
capabilities dropped, and privilege escalation disabled. Temporary files use a
16 MiB `/tmp` mount with execution disabled. Limits are one CPU, 256 MiB of memory
with swap disabled, and 64 processes/threads. Adjust these limits in a Compose
override when tools need more resources. Docker's init process forwards signals
and reaps child processes; shutdown has a 10-second grace period. See the
[Compose service reference](https://docs.docker.com/reference/compose-file/services/)
and [tmpfs options](https://docs.docker.com/engine/storage/tmpfs/).

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
**Actions → MCP container → Run workflow**. The workflow builds a Linux amd64 image,
checks the SDK import and CA certificates, verifies `ping` with the Compose
restrictions, and scans OS and Python dependencies with Trivy. Fixable high or
critical vulnerabilities block publication. Local builds also support native
arm64; the publishing workflow currently targets amd64.

Images in `ghcr.io/orestxherija/opendart-mcp` receive `sha-<full-commit>` and
`run-<run-id>-<attempt>` tags. Default-branch runs also update `test`. OCI labels
record the source, revision, and build date. The image includes
[SBOM and provenance attestations](https://docs.docker.com/build/ci/github-actions/attestations/).
The workflow pulls and smoke-tests the published digest and records it in its
summary. Pin consumers to that digest for an immutable image selection; a commit
tag can be updated when the same commit is rebuilt.
It uses the built-in `GITHUB_TOKEN` with `packages: write`; no extra secret is needed.

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
