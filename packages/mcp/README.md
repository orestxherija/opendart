# OpenDART MCP

Minimal stdio server using the [official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/run/).
It exposes one tool, `ping`, which returns `pong` without an API key or network calls.
OpenDART tools will use the async `OpenDart` client from `opendart-sdk`.

From the repository root, run locally:

```sh
uv sync --locked --all-packages
uv run --no-sync opendart-mcp
```

`uv run --no-sync python -m opendart_mcp` is equivalent.

To verify initialization, tool discovery, and a real tool call, run:

```sh
uv run --no-sync python scripts/check_mcp.py
```

Expected output: `MCP smoke test passed: ping -> pong`.

## Docker

From the repository root, build the image, then start it with stdin attached for
an MCP client:

```sh
docker compose -f packages/mcp/docker-compose.yml build mcp
docker compose -f packages/mcp/docker-compose.yml run --rm --no-deps -T mcp
```

Test the built container with the same MCP client:

```sh
uv run --no-sync python scripts/check_mcp.py docker run --rm -i ghcr.io/orestxherija/opendart-mcp:test
```

Compose forwards `OPENDART_API__API_KEY` from your shell. To load the root `.env`
file explicitly, use [Compose's `--env-file` option](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/):

```sh
docker compose --env-file .env -f packages/mcp/docker-compose.yml run --rm --no-deps -T mcp
```

The `ping` tool does not require a key; add one when implementing OpenDART tools.
The build context excludes `.env`, local virtual environments, and other files
outside the package sources and workspace manifests.

To connect an MCP host, configure it to launch `docker` with these arguments
(replace `/absolute/path/to/opendart` with your checkout):

```json
{
  "mcpServers": {
    "opendart": {
      "command": "docker",
      "args": [
        "compose", "-f", "/absolute/path/to/opendart/packages/mcp/docker-compose.yml",
        "run", "--rm", "--no-deps", "-T", "mcp"
      ]
    }
  }
}
```

To load the root `.env` file for this host configuration, add `"--env-file",`
`"/absolute/path/to/opendart/.env"` before `"run"` in the arguments above.

The server uses stdio, so no ports are published. Run it through an MCP host;
when launched manually, it waits for protocol messages on stdin.

## Publish to GHCR

After pushing the workflow to the repository's default branch, open GitHub
**Actions → MCP container → Run workflow**. The workflow builds the image, verifies
`ping` inside the container, publishes `ghcr.io/orestxherija/opendart-mcp:test`, then
pulls and tests the published image. Each run replaces the `test` tag.
It uses the built-in `GITHUB_TOKEN` with `packages: write`; no extra secret is needed.

To test the published image on a machine with Docker, authenticate to GHCR if the
package is private, then run:

```sh
docker pull ghcr.io/orestxherija/opendart-mcp:test
uv run --no-sync python scripts/check_mcp.py docker run --rm -i ghcr.io/orestxherija/opendart-mcp:test
```

For private packages, use a personal access token (classic) with `read:packages`
when running `docker login ghcr.io --username orestxherija`. New GHCR packages are
private by default; visibility can be changed in the package settings.
See [GitHub's Container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

An MCP host can launch the published image directly with command `docker` and args
`["run", "--rm", "-i", "ghcr.io/orestxherija/opendart-mcp:test"]`.
GHCR stores the image; the host starts the stdio server when it connects.
